"""Unit tests for axon.cli.main.

Validates: Requirements R12.1–R12.4, R13.1–R13.5
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from traject.classifier.artifact_type import ArtifactType
from traject.cli.main import app
from traject.models import InferenceSpan

runner = CliRunner()


def _span_json(**overrides: Any) -> str:
    """Build a valid InferenceSpan JSON string for test JSONL files."""
    span = InferenceSpan(
        id=uuid4(),
        trace_id="trace-1",
        parent_span_id=None,
        span_name="gen_ai.openai.gpt-4o",
        timestamp=datetime.utcnow(),
        duration_ms=150,
        provider="openai",
        model=overrides.get("model", "gpt-4o"),
        api_version=None,
        input_tokens=overrides.get("input_tokens", 100),
        output_tokens=overrides.get("output_tokens", 50),
        cached_tokens=0,
        token_count_method="exact",
        cost_usd=overrides.get("cost_usd", Decimal("0.00125000")),
        feature_tag=overrides.get("feature_tag", "test-feature"),
        prompt_hash="a" * 64,
        artifact_type=ArtifactType.USER_MESSAGE,
        compression_applied=False,
        shadow_mode=True,
        pre_compression_tokens=None,
        tokens_saved=overrides.get("tokens_saved", 10),
        cache_hit=overrides.get("cache_hit", False),
        environment="test",
    )
    return span.model_dump_json()


class TestVersionCommand:
    def test_prints_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "traject-sdk 0.1.0" in result.output


class TestDoctorCommand:
    def test_exits_with_nonzero_when_deps_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import importlib

        orig_import_module = importlib.import_module

        def mock_import_module(name: str, *args: object, **kwargs: object) -> object:
            if name == "tiktoken":
                raise ImportError("No module named 'tiktoken'")
            return orig_import_module(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(importlib, "import_module", mock_import_module)
        result = runner.invoke(app, ["doctor"])
        # exit code 1 when required dep missing
        assert result.exit_code == 1

    def test_outputs_table(self) -> None:
        result = runner.invoke(app, ["doctor"])
        # Table should contain package names regardless of exit code
        assert "sentence-transformers" in result.output or "tiktoken" in result.output


class TestAnalyzeCommand:
    def test_nonexistent_file_exits_1(self) -> None:
        result = runner.invoke(app, ["analyze", "--input", "/nonexistent/file.jsonl"])
        assert result.exit_code == 1

    def test_valid_jsonl_exits_0(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(_span_json() + "\n")
            f.write(_span_json(model="gpt-4o-mini", feature_tag="other") + "\n")
            tmp_path = f.name

        result = runner.invoke(app, ["analyze", "--input", tmp_path])
        assert result.exit_code == 0
        Path(tmp_path).unlink(missing_ok=True)

    def test_malformed_line_skipped(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(_span_json() + "\n")
            f.write("this is not valid json\n")
            f.write(_span_json() + "\n")
            tmp_path = f.name

        result = runner.invoke(app, ["analyze", "--input", tmp_path])
        # Should still exit 0, skipping the malformed line
        assert result.exit_code == 0
        Path(tmp_path).unlink(missing_ok=True)

    def test_json_format_output(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(_span_json() + "\n")
            tmp_path = f.name

        result = runner.invoke(
            app, ["analyze", "--input", tmp_path, "--format", "json"]
        )
        assert result.exit_code == 0
        # Output should be valid JSON
        try:
            data = json.loads(result.output.strip())
            assert isinstance(data, list)
        except json.JSONDecodeError:
            pytest.fail("--format json did not produce valid JSON output")
        Path(tmp_path).unlink(missing_ok=True)

    def test_aggregates_by_model_and_feature_tag(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            # Two spans with same model+feature_tag
            f.write(
                _span_json(model="gpt-4o", feature_tag="bot", input_tokens=100) + "\n"
            )
            f.write(
                _span_json(model="gpt-4o", feature_tag="bot", input_tokens=200) + "\n"
            )
            # One span with different feature_tag
            f.write(
                _span_json(model="gpt-4o", feature_tag="other", input_tokens=50) + "\n"
            )
            tmp_path = f.name

        result = runner.invoke(
            app, ["analyze", "--input", tmp_path, "--format", "json"]
        )
        data = json.loads(result.output.strip())
        # Should have 2 rows: (gpt-4o, bot) and (gpt-4o, other)
        assert len(data) == 2
        bot_row = next(r for r in data if r["feature_tag"] == "bot")
        assert bot_row["calls"] == 2
        assert bot_row["input_tokens"] == 300
        Path(tmp_path).unlink(missing_ok=True)
