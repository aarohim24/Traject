"""Exception hierarchy for the Axon SDK.

All exceptions raised by library code within the ``axon`` package are
subclasses of :class:`AxonError`.  Callers can catch ``AxonError`` to handle
any SDK-specific failure, or catch a specific subclass when finer-grained
handling is needed.  No exception in this module imports anything beyond the
Python standard library.
"""


class AxonError(Exception):
    """Base class for all Axon SDK exceptions.

    Every exception raised by library code within the ``axon`` package is an
    instance of this class or one of its subclasses.  Catching ``AxonError``
    is sufficient to suppress all SDK-originated errors without accidentally
    masking unrelated exceptions.

    Args:
        message: Human-readable description of the error, including what went
            wrong and, where possible, what the caller can do to resolve it.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AxonConfigError(AxonError):
    """Raised when the SDK is misconfigured with invalid configuration values.

    Args:
        message: Human-readable description of the configuration problem and
            the expected valid range or value.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AxonDependencyError(AxonError):
    """Raised when a required optional framework dependency is not installed.

    Args:
        message: Human-readable description naming the missing package and the
            ``pip install`` command the caller should run to resolve it.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AxonCompressionError(AxonError):
    """Raised when the compression pipeline produces an invalid result.

    The compression engine catches this exception internally, falls back to
    returning the original messages, and logs a warning.  This exception
    never propagates to the caller of :func:`axon.compression.engine.compress`.

    Args:
        message: Human-readable description of the compression failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AxonProviderError(AxonError):
    """Raised when a provider response cannot be parsed or an unknown provider is used.

    Args:
        message: Human-readable description identifying the unknown or
            unsupported provider and listing the providers that are supported.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InsufficientDataError(AxonError):
    """Raised when a training or analytics operation lacks enough data to proceed.

    This exception signals that the operation requires a minimum number of
    labeled examples or historical records but the available dataset does not
    meet that threshold.  The caller should collect more data before retrying.

    Args:
        message: Human-readable description of why the data is insufficient,
            including the current count and the minimum required count where
            applicable.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
