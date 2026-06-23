"""Integration tests for LangChain adapter.

Tests adapter behavior with and without langchain-core installed.
"""

from __future__ import annotations

import pytest

from traject.exceptions import TrajectDependencyError


class TestLangChainAdapterImport:
    def test_raises_dependency_error_when_langchain_missing(
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


class TestLangChainAdapterIntegration:
    @pytest.fixture(autouse=True)
    def require_langchain(self) -> None:
        pytest.importorskip("langchain_core")

    def test_accepts_base_messages(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        from traject.compression.adapters.langchain import LangChainAdapter

        assert (
            LangChainAdapter.accepts(
                [SystemMessage(content="hi"), HumanMessage(content="hello")]
            )
            is True
        )

    def test_normalize_produces_canonical_dicts(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from traject.compression.adapters.langchain import LangChainAdapter

        normalized = LangChainAdapter().normalize(
            [
                SystemMessage(content="sys"),
                HumanMessage(content="user"),
                AIMessage(content="asst"),
            ]
        )
        assert normalized[0] == {"role": "system", "content": "sys"}
        assert normalized[1] == {"role": "user", "content": "user"}
        assert normalized[2] == {"role": "assistant", "content": "asst"}

    def test_compression_engine_processes_langchain_messages(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        from traject.compression.adapters.langchain import LangChainAdapter
        from traject.compression.engine import compress
        from traject.compression.strategies import CompressionStrategy, get_config

        messages = [SystemMessage(content="System."), HumanMessage(content="Question.")]
        result = compress(
            messages,
            get_config(CompressionStrategy.CONSERVATIVE),
            adapter=LangChainAdapter(),
        )
        assert result.shadow_mode is True
        assert result.segments_analyzed >= 1
