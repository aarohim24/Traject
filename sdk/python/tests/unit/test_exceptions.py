"""Unit tests for axon.exceptions."""
from __future__ import annotations

import pytest

from traject.exceptions import (
    AxonCompressionError,
    TrajectConfigError,
    TrajectDependencyError,
    TrajectError,
    AxonProviderError,
)


class TestTrajectErrorHierarchy:

    def test_axon_error_is_exception(self) -> None:
        assert issubclass(TrajectError, Exception)

    def test_config_error_is_axon_error(self) -> None:
        assert issubclass(TrajectConfigError, TrajectError)

    def test_dependency_error_is_axon_error(self) -> None:
        assert issubclass(TrajectDependencyError, TrajectError)

    def test_compression_error_is_axon_error(self) -> None:
        assert issubclass(AxonCompressionError, TrajectError)

    def test_provider_error_is_axon_error(self) -> None:
        assert issubclass(AxonProviderError, TrajectError)

    @pytest.mark.parametrize("cls", [TrajectError, TrajectConfigError, TrajectDependencyError, AxonCompressionError, AxonProviderError])
    def test_instantiable_with_message(self, cls: type) -> None:
        exc = cls("test message")
        assert str(exc) == "test message"

    def test_caught_as_axon_error(self) -> None:
        with pytest.raises(TrajectError):
            raise TrajectConfigError("bad config")

    def test_caught_specifically(self) -> None:
        with pytest.raises(AxonProviderError, match="unknown provider"):
            raise AxonProviderError("unknown provider")

    def test_dependency_error_message_preserved(self) -> None:
        msg = "pip install axon-sdk[langchain]"
        exc = TrajectDependencyError(msg)
        assert msg in str(exc)
