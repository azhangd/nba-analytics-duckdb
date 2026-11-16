"""Shared exception types for pipeline control flow."""


class EmptyPayloadError(ValueError):
    """An NBA endpoint answered without the data asked for (often a rate-limit signal)."""


class LiveEndpointUnavailableError(RuntimeError):
    """Raised when a required live collection source is unavailable."""


class NoRunToResumeError(RuntimeError):
    """--resume-latest found no incomplete run for the command and graph."""


class PipelineStateNotInitializedError(RuntimeError):
    """Raised when read-only run-state commands are used before schema init."""


class SyntheticDataInLiveWarehouseError(RuntimeError):
    """Raised when a live pipeline points at an offline smoke warehouse."""
