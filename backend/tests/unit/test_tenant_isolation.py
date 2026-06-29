"""Tenant isolation tests (audit C4).

Proves that data and auth are scoped per tenant: a query for tenant A never
returns tenant B's rows, and API-key resolution maps to the right tenant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.core.auth import (
    INSECURE_DEFAULT_API_KEY,
    assert_secure_api_key,
    get_current_tenant,
)
from traject_backend.core.config import settings
from traject_backend.models.attribution import CostAttributionRecord
from traject_backend.models.budget import BudgetControlRecord
from traject_backend.models.span import InferenceSpanRecord
from traject_backend.models.tenant import DEFAULT_TENANT_ID, TenantRecord, hash_api_key
from traject_backend.services.budget_enforcer import check_budget
from traject_backend.services.cost_attribution import get_attribution

TENANT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _span(
    tenant: uuid.UUID, tag: str, cost: str, ts: datetime | None = None
) -> InferenceSpanRecord:
    return InferenceSpanRecord(
        id=uuid.uuid4(),
        tenant_id=tenant,
        trace_id=str(uuid.uuid4()),
        span_name="gen_ai.openai.gpt-4o",
        timestamp=ts or datetime(2026, 1, 1, 12, 0, 0),
        duration_ms=100,
        provider="openai",
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        cached_tokens=0,
        token_count_method="exact",
        cost_usd=Decimal(cost),
        feature_tag=tag,
        prompt_hash="a" * 64,
        artifact_type="user_message",
        environment="test",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )


class TestAuthResolution:
    @pytest.mark.asyncio
    async def test_bootstrap_key_maps_to_default_tenant(
        self, db_session: AsyncSession
    ) -> None:
        tid = await get_current_tenant(x_api_key=settings.api_key, db=db_session)
        assert tid == DEFAULT_TENANT_ID

    @pytest.mark.asyncio
    async def test_missing_key_401(self, db_session: AsyncSession) -> None:
        with pytest.raises(HTTPException) as exc:
            await get_current_tenant(x_api_key=None, db=db_session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_key_401(self, db_session: AsyncSession) -> None:
        with pytest.raises(HTTPException) as exc:
            await get_current_tenant(x_api_key="not-a-real-key", db=db_session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_provisioned_tenant_key_resolves(
        self, db_session: AsyncSession
    ) -> None:
        db_session.add(
            TenantRecord(
                id=TENANT_A,
                name="acme",
                api_key_hash=hash_api_key("acme-secret-key"),
                is_active=True,
                created_at=datetime(2026, 1, 1, 12, 0, 0),
            )
        )
        await db_session.flush()
        tid = await get_current_tenant(x_api_key="acme-secret-key", db=db_session)
        assert tid == TENANT_A


class TestStartupGuard:
    def test_refuses_default_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "api_key", INSECURE_DEFAULT_API_KEY)
        monkeypatch.setattr(settings, "allow_insecure_api_key", False)
        with pytest.raises(RuntimeError, match="Refusing to start"):
            assert_secure_api_key()

    def test_allows_strong_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "api_key", "a-strong-unique-key")
        assert_secure_api_key()  # no raise

    def test_allows_default_when_opted_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "api_key", INSECURE_DEFAULT_API_KEY)
        monkeypatch.setattr(settings, "allow_insecure_api_key", True)
        assert_secure_api_key()  # no raise


class TestDataScoping:
    @pytest.mark.asyncio
    async def test_budget_check_is_tenant_scoped(
        self, db_session: AsyncSession, redis_mock: object
    ) -> None:
        # Same feature_tag, a budget for each tenant.
        for tenant in (TENANT_A, TENANT_B):
            db_session.add(
                BudgetControlRecord(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    feature_tag="shared-tag",
                    period="daily",
                    budget_usd=Decimal("1.00"),
                    alert_threshold_pct=0.8,
                    hard_stop=False,
                    created_at=datetime(2026, 1, 1, 12, 0, 0),
                    updated_at=datetime(2026, 1, 1, 12, 0, 0),
                )
            )
        # Tenant A overspends; tenant B spends nothing. Use a current timestamp
        # so the span falls inside the "daily" budget window.
        from datetime import timezone

        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        db_session.add(_span(TENANT_A, "shared-tag", "5.00", ts=now))
        await db_session.flush()

        # No redis key → both compute from DB, scoped by tenant.
        status_a = await check_budget("shared-tag", db_session, redis_mock, tenant_id=TENANT_A)
        await redis_mock.delete("traject:budget:shared-tag")  # type: ignore[attr-defined]
        status_b = await check_budget("shared-tag", db_session, redis_mock, tenant_id=TENANT_B)

        assert status_a.value == "exhausted"  # A's $5 over a $1 budget
        assert status_b.value == "ok"         # B has zero spend

    @pytest.mark.asyncio
    async def test_attribution_is_tenant_scoped(self, db_session: AsyncSession) -> None:
        for tenant, cost in ((TENANT_A, "10.00"), (TENANT_B, "99.00")):
            db_session.add(
                CostAttributionRecord(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    feature_tag="svc",
                    hour_bucket=datetime(2026, 1, 1, 12, 0, 0),
                    provider="openai",
                    model="gpt-4o",
                    total_input_tokens=100,
                    total_output_tokens=50,
                    total_cost_usd=Decimal(cost),
                    call_count=1,
                    created_at=datetime(2026, 1, 1, 12, 0, 0),
                )
            )
        await db_session.flush()

        resp = await get_attribution(
            db_session,
            feature_tag=None,
            from_ts=datetime(2026, 1, 1, 0, 0, 0),
            to_ts=datetime(2026, 1, 2, 0, 0, 0),
            group_by="feature_tag",
            tenant_id=TENANT_A,
        )
        # Only tenant A's $10 — never B's $99.
        assert resp.total_cost_usd == Decimal("10.00")
