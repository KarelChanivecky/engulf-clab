"""Public, non-sensitive errors returned by the local RPC service."""

from __future__ import annotations


class McpServiceError(RuntimeError):
    """An expected request failure that is safe to return to an MCP caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConfigurationError(McpServiceError):
    """The root-owned service configuration cannot be used safely."""

    def __init__(self, message: str) -> None:
        super().__init__("configuration_error", message)


class RequestError(McpServiceError):
    """A local RPC request is malformed or disallowed."""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_request", message)


class NotFoundError(McpServiceError):
    """A configured object was not found."""

    def __init__(self, message: str) -> None:
        super().__init__("not_found", message)


class BusyError(McpServiceError):
    """A lab already has an active lifecycle job."""

    def __init__(self, message: str, job_id: str) -> None:
        super().__init__("busy", message)
        self.job_id = job_id


class OperationError(McpServiceError):
    """A fixed, privileged operation could not complete."""

    def __init__(self, message: str) -> None:
        super().__init__("operation_failed", message)
