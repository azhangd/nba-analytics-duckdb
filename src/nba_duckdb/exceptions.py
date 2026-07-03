"""Shared exception types for pipeline control flow."""


class LiveEndpointUnavailableError(RuntimeError):
    """Raised when a required live collection source is unavailable."""


class PipelineStateNotInitializedError(RuntimeError):
    """Raised when read-only run-state commands are used before schema init."""
