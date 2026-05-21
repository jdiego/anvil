from __future__ import annotations


class AnvilError(RuntimeError):
    """Base error for anvil. All package-raised errors derive from this."""


class ConfigError(AnvilError):
    """Configuration file missing, malformed, or incomplete."""


class ContextNotFoundError(AnvilError):
    """No configured context matches the requested host."""


class SecretNotFoundError(AnvilError):
    """A secret could not be retrieved from any supported backend."""


class InvalidInputError(AnvilError):
    """Input provided by the caller is not usable (e.g. malformed URL)."""


class UpstreamHTTPError(AnvilError):
    """An upstream API (Sentry/GitLab) returned an error response.

    Attributes:
        service: ``"sentry"`` or ``"gitlab"``.
        status_code: HTTP status code returned by the upstream.
        message: Human-readable summary suitable for surfacing to an agent.
    """

    def __init__(self, *, service: str, status_code: int, message: str) -> None:
        super().__init__(f"{service} returned {status_code}: {message}")
        self.service = service
        self.status_code = status_code
        self.message = message


MCPConfigError = ConfigError
