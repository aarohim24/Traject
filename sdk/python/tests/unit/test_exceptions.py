"""Unit tests for traject.exceptions."""

from __future__ import annotations

import pytest

from traject.exceptions import (
    TrajectCompressionError,
    TrajectConfigError,
    TrajectDependencyError,
    TrajectError,
    TrajectProviderError,
)


class TestTrajectErrorHierarchy:
    def test_traject_error_is_exception(self) -> None:
        assert issubclass(TrajectError, Exception)

    def test_config_error_is_traject_error(self) -> None:
        assert issubclass(TrajectConfigError, TrajectError)

    def test_dependency_error_is_traject_error(self) -> None:
        assert issubclass(TrajectDependencyError, TrajectError)

    def test_compression_error_is_traject_error(self) -> None:
        assert issubclass(TrajectCompressionError, TrajectError)

    def test_provider_error_is_traject_error(self) -> None:
        assert issubclass(TrajectProviderError, TrajectError)

    @pytest.mark.parametrize(
        "cls",
        [
            TrajectError,
            TrajectConfigError,
            TrajectDependencyError,
            TrajectCompressionError,
            TrajectProviderError,
        ],
    )
    def test_instantiable_with_message(self, cls: type) -> None:
        exc = cls("test message")
        assert str(exc) == "test message"

    def test_caught_as_traject_error(self) -> None:
        with pytest.raises(TrajectError):
            raise TrajectConfigError("bad config")

    def test_caught_specifically(self) -> None:
        with pytest.raises(TrajectProviderError, match="unknown provider"):
            raise TrajectProviderError("unknown provider")

    def test_dependency_error_message_preserved(self) -> None:
        msg = "pip install traject-sdk[langchain]"
        exc = TrajectDependencyError(msg)
        assert msg in str(exc)
