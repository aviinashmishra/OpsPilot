"""Structured application errors with stable error codes."""

from __future__ import annotations

from typing import Any


class OpsPilotError(Exception):
    code: str = "internal_error"
    status_code: int = 500
    retryable: bool = False

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None, code: str | None = None):
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.details = details or {}
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationFailed(OpsPilotError):
    code = "validation_failed"
    status_code = 422


class NotFound(OpsPilotError):
    code = "not_found"
    status_code = 404


class Conflict(OpsPilotError):
    code = "conflict"
    status_code = 409


class AuthenticationError(OpsPilotError):
    code = "unauthenticated"
    status_code = 401


class AuthorizationError(OpsPilotError):
    code = "forbidden"
    status_code = 403


class TenantIsolationViolation(AuthorizationError):
    code = "tenant_isolation_violation"


class PolicyDenied(OpsPilotError):
    code = "policy_denied"
    status_code = 403


class ApprovalRequired(OpsPilotError):
    code = "approval_required"
    status_code = 202


class QuotaExceeded(OpsPilotError):
    code = "quota_exceeded"
    status_code = 429


class RateLimited(OpsPilotError):
    code = "rate_limited"
    status_code = 429
    retryable = True


class IntegrationNotConfigured(OpsPilotError):
    code = "integration_not_configured"
    status_code = 424


class IntegrationError(OpsPilotError):
    code = "integration_error"
    status_code = 502


class TransientIntegrationError(IntegrationError):
    code = "integration_transient_error"
    retryable = True


class CircuitOpen(TransientIntegrationError):
    code = "circuit_open"


class ToolNotAllowed(AuthorizationError):
    code = "tool_not_allowed"


class LLMError(OpsPilotError):
    code = "llm_error"
    status_code = 502
    retryable = True


class LLMOutputInvalid(OpsPilotError):
    code = "llm_output_invalid"
    status_code = 502


class PromptInjectionDetected(OpsPilotError):
    code = "prompt_injection_detected"
    status_code = 400


class WorkflowError(OpsPilotError):
    code = "workflow_error"


class WorkflowTimeout(WorkflowError):
    code = "workflow_timeout"
    status_code = 504


class WorkflowCancelled(WorkflowError):
    code = "workflow_cancelled"
    status_code = 409


class AgentDisabled(OpsPilotError):
    code = "agent_disabled"
    status_code = 423
