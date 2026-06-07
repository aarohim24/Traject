"""Unit tests for axon.exceptions."""
from __future__ import annotations

import pytest

from axon.exceptions import (
    AxonCompressionError,
    AxonConfigError,
    AxonDependencyError,
    AxonError,
    AxonProviderError,
)


class TestAxonErrorHierarchy:

    def test_axon_error_is_exception(self) -> None:
        assert issubclass(AxonError, Exception)

    def test_config_error_is_axon_error(self) -> None:
        assert issubclass(AxonConfigError, AxonError)

    def test_dependency_error_is_axon_error(self) -> None:
        assert issubclass(AxonDependencyError, AxonError)

    def test_compression_error_is_axon_error(self) -> None:
        assert issubclass(AxonCompressionError, AxonError)

    def test_provider_error_is_axon_error(self) -> None:
        assert issubclass(AxonProviderError, AxonError)

    @pytest.mark.parametrize("cls", [AxonError, AxonConfigError, AxonDependencyError, AxonCompressionError, AxonProviderError])
    def test_instantiable_with_message(self, cls: type) -> None:
        exc = cls("test message")
        assert str(exc) == "test message"

    def test_caught_as_axon_error(self) -> None:
        with pytest.raises(AxonError):
            raise AxonConfigError("bad config")

    def test_caught_specifically(self) -> None:
        with pytest.raises(AxonProviderError, match="unknown provider"):
            raise AxonProviderError("unknown provider")

    def test_dependency_error_message_preserved(self) -> None:
        msg = "pip install axon-sdk[langchain]"
        exc = AxonDependencyError(msg)
        assert msg in str(exc)
