from __future__ import annotations

from pydantic import BaseModel, Field

from anvil.contexts import load_contexts


class PublicServiceContext(BaseModel):
    """Public, non-secret view of a configured upstream service."""

    base_url: str = Field(description="Root URL of the configured upstream service.")


class PublicContext(BaseModel):
    """Public view of one configured context."""

    name: str = Field(description="Context identifier used by anvil.")
    sentry: PublicServiceContext | None = None
    gitlab: PublicServiceContext | None = None
    github: PublicServiceContext | None = None


class ContextsResource(BaseModel):
    """Discoverable list of configured contexts without secrets."""

    contexts: list[PublicContext]


def list_contexts_resource() -> dict[str, object]:
    """Return configured context names and public service URLs.

    This resource intentionally omits token keychain identifiers and secret
    values. Use it for discovery before selecting an upstream URL for a tool
    call.
    """

    contexts = load_contexts()
    payload = ContextsResource(
        contexts=[
            PublicContext(
                name=name,
                sentry=(PublicServiceContext(base_url=ctx.sentry.base_url) if ctx.sentry else None),
                gitlab=(PublicServiceContext(base_url=ctx.gitlab.base_url) if ctx.gitlab else None),
                github=(PublicServiceContext(base_url=ctx.github.base_url) if ctx.github else None),
            )
            for name, ctx in contexts.items()
        ]
    )
    return payload.model_dump(mode="json", exclude_none=True)
