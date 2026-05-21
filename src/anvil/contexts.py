from __future__ import annotations

from typing import Self
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError, model_validator

from anvil.config import load_config
from anvil.exceptions import ConfigError, ContextNotFoundError, InvalidInputError


class ServiceContext(BaseModel):
    """A single upstream service entry within a context."""

    base_url: str = Field(description="Root URL of the service, e.g. https://gitlab.example.com")
    token_keychain: str = Field(
        description="Identifier used by the secret backend (Keychain service name)."
    )


class Context(BaseModel):
    """A named context grouping configured upstream services."""

    sentry: ServiceContext | None = None
    gitlab: ServiceContext | None = None
    github: ServiceContext | None = None

    @model_validator(mode="after")
    def require_at_least_one_service(self) -> Self:
        if self.sentry is None and self.gitlab is None and self.github is None:
            raise ValueError(
                "no services configured; configure at least one of sentry, gitlab, or github"
            )
        return self


def load_contexts() -> dict[str, Context]:
    data = load_config()
    contexts: dict[str, Context] = {}
    for name, value in data["contexts"].items():
        try:
            contexts[name] = Context.model_validate(value)
        except ValidationError as exc:
            raise ConfigError(f"Invalid context {name!r}: {exc.errors()[0]['msg']}") from exc
    return contexts


def resolve_context(url: str) -> tuple[str, Context]:
    """Resolve which configured context owns the host of ``url``."""

    parsed = urlparse(url)
    host = parsed.hostname

    if not host:
        raise InvalidInputError(f"Invalid URL: {url}")

    contexts = load_contexts()

    for name, ctx in contexts.items():
        sentry_host = _host_from_base_url(ctx.sentry.base_url) if ctx.sentry else None
        gitlab_host = _host_from_base_url(ctx.gitlab.base_url) if ctx.gitlab else None
        github_host = _host_from_base_url(ctx.github.base_url) if ctx.github else None
        if host in {sentry_host, gitlab_host, github_host}:
            return name, ctx

    raise ContextNotFoundError(f"No context configured for host: {host}")


def _host_from_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    return urlparse(base_url).hostname
