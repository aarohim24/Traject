"""Unit tests for LangChain and AutoGen compression adapters.

Validates: Requirements R6.4, R6.5, R17.2
"""
from __future__ import annotations

import pytest

from traject.exceptions import TrajectDependencyError


class TestLangChainAdapterImport:
    """Tests for LangChain adapter import guard (ADR-009)."""

    def test_raises_dependency_error_when_langchain_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins
        import importlib
        import sys

        orig = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("langchain"):
                raise ImportError(f"No module named '{name}'")
            return orig(name, *args, **kwargs)

        key = "traject.compression.adapters.langchain"
        monkeypatch.delitem(sys.modules, key, raising=False)
        with monkeypatch.context() as m:
            m.setattr(builtins, "__import__", mock_import)
            with pytest.raises(TrajectDependencyError, match="langchain-core"):
                importlib.import_module(key)


class TestAutoGenAdapterImport:
    """Tests for AutoGen adapter import guard (ADR-009)."""

    def test_raises_dependency_error_when_autogen_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins
        import importlib
        import sys

        orig = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "autogen":
                raise ImportError("No module named 'autogen'")
            return orig(name, *args, **kwargs)

        key = "traject.compression.adapters.autogen"
        monkeypatch.delitem(sys.modules, key, raising=False)
        with monkeypatch.context() as m:
            m.setattr(builtins, "__import__", mock_import)
            with pytest.raises(TrajectDependencyError, match="pyautogen"):
                importlib.import_module(key)


class TestLangChainAdapterIntegration:
    """Tests that run only when langchain-core is installed."""

    @pytest.fixture(autouse=True)
    def require_langchain(self) -> None:
        pytest.importorskip("langchain_core", reason="langchain-core not installed")

    def test_accepts_base_message_list(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        from traject.compression.adapters.langchain import LangChainAdapter

        msgs = [SystemMessage(content="sys"), HumanMessage(content="user")]
        assert LangChainAdapter.accepts(msgs) is True

    def test_rejects_non_base_message_list(self) -> None:
        from traject.compression.adapters.langchain import LangChainAdapter

        assert LangChainAdapter.accepts([{"role": "user", "content": "hi"}]) is False

    def test_normalize_produces_canonical_dicts(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from traject.compression.adapters.langchain import LangChainAdapter

        normalized = LangChainAdapter().normalize([
            SystemMessage(content="sys"),
            HumanMessage(content="user"),
            AIMessage(content="asst"),
        ])
        assert normalized[0] == {"role": "system", "content": "sys"}
        assert normalized[1] == {"role": "user", "content": "user"}
        assert normalized[2] == {"role": "assistant", "content": "asst"}

    def test_denormalize_reconstructs_message_types(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        from traject.compression.adapters.langchain import LangChainAdapter

        original = [SystemMessage(content="sys"), HumanMessage(content="hi")]
        normalized = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = LangChainAdapter().denormalize(normalized, original)
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], HumanMessage)


class TestAutoGenAdapterIntegration:
    """Tests for AutoGen adapter when pyautogen is installed."""

    @pytest.fixture(autouse=True)
    def require_autogen(self) -> None:
        pytest.importorskip("autogen", reason="pyautogen not installed")

    def test_accepts_autogen_style_dicts(self) -> None:
        from traject.compression.adapters.autogen import AutoGenAdapter

        msgs = [{"role": "user", "content": "hi", "name": "alice"}]
        assert AutoGenAdapter.accepts(msgs) is True

    def test_rejects_dicts_without_name(self) -> None:
        from traject.compression.adapters.autogen import AutoGenAdapter

        msgs = [{"role": "user", "content": "hi"}]
        assert AutoGenAdapter.accepts(msgs) is False

    def test_normalize_strips_name_field(self) -> None:
        from traject.compression.adapters.autogen import AutoGenAdapter

        msgs = [{"role": "user", "content": "hi", "name": "alice"}]
        normalized = AutoGenAdapter().normalize(msgs)
        assert normalized == [{"role": "user", "content": "hi"}]

    def test_denormalize_restores_name_field(self) -> None:
        from traject.compression.adapters.autogen import AutoGenAdapter

        original = [{"role": "user", "content": "hi", "name": "alice"}]
        normalized = [{"role": "user", "content": "hi"}]
        result = AutoGenAdapter().denormalize(normalized, original)
        assert result[0].get("name") == "alice"
