from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class SentryProjectInput(BaseModel):
    context_url: HttpUrl = Field(
        description="Any URL on the target Sentry host; used to resolve the context."
    )
    organization_slug: str = Field(min_length=1)
    project_slug: str = Field(min_length=1)


class ResolveSentryContextInput(BaseModel):
    url: HttpUrl = Field(description="Any URL pointing at a configured Sentry/GitLab host.")


class ResolveSentryContextOutput(BaseModel):
    context: str = Field(description="Name of the matched context, e.g. 'example'.")
    sentry_base_url: str
    gitlab_base_url: str | None = None


class GetSentryIssueInput(BaseModel):
    url: HttpUrl = Field(
        description=(
            "Full URL of a Sentry issue. Must contain '/issues/<id>/' in the path; "
            "the host must match a configured context."
        )
    )


class SentryIssueSummary(BaseModel):
    """Slimmed-down view of a Sentry issue, optimised for agent context windows."""

    id: str
    short_id: str | None = Field(default=None, alias="shortId")
    title: str
    culprit: str | None = None
    level: str | None = None
    status: str | None = None
    permalink: str | None = None
    count: str | int | None = None
    user_count: int | None = Field(default=None, alias="userCount")
    first_seen: str | None = Field(default=None, alias="firstSeen")
    last_seen: str | None = Field(default=None, alias="lastSeen")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GetSentryIssueOutput(BaseModel):
    context: str
    issue: SentryIssueSummary
    latest_event: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Latest event payload for the issue. Includes stack traces; can be large. "
            "Filter aggressively when forwarding to a model."
        ),
    )


class ListSentryIssuesInput(SentryProjectInput):
    query: str | None = Field(
        default=None,
        description="Optional Sentry issue search query, e.g. 'is:unresolved level:error'.",
    )
    environment: str | None = None
    age: str | None = Field(
        default=None,
        description="Optional relative age filter appended as age:<value>, e.g. '24h' or '7d'.",
    )
    limit: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Max issue summaries to return. Hard cap at 100; defaults to 25.",
    )


class ListSentryIssuesOutput(BaseModel):
    context: str
    issues: list[SentryIssueSummary]
    total: int = Field(description="Issues returned by Sentry before the limit was applied.")
    returned: int = Field(description="Issues included in this response after the limit.")
    truncated: bool = Field(
        description="True when the upstream page filled the limit, so more issues may exist."
    )
    warnings: list[str] = Field(default_factory=list)


class AssignSentryIssueInput(BaseModel):
    context_url: HttpUrl
    issue_id: str = Field(min_length=1)
    assignee: str = Field(
        min_length=1,
        description="Sentry assignee identifier, e.g. 'user:alice@example.com' or 'team:backend'.",
    )
    confirm: bool = Field(
        default=False,
        description="Safety flag. The issue is assigned only when true.",
    )


class AssignSentryIssueOutput(BaseModel):
    context: str
    issue: SentryIssueSummary | None = None
    assigned_to: str
    dry_run: bool


class ResolveSentryIssueInput(BaseModel):
    context_url: HttpUrl
    issue_id: str = Field(min_length=1)
    in_release: str | None = Field(
        default=None,
        description="Optional release version used for Sentry statusDetails.inRelease.",
    )
    confirm: bool = Field(
        default=False,
        description="Safety flag. The issue is resolved only when true.",
    )


class ResolveSentryIssueOutput(BaseModel):
    context: str
    issue: SentryIssueSummary | None = None
    in_release: str | None = None
    dry_run: bool


class LinkSentryIssueToMergeRequestInput(BaseModel):
    context_url: HttpUrl
    issue_id: str = Field(min_length=1)
    mr_url: HttpUrl
    confirm: bool = Field(
        default=False,
        description="Safety flag. The Sentry comment is created only when true.",
    )


class LinkSentryIssueToMergeRequestOutput(BaseModel):
    context: str
    issue_id: str
    mr_url: HttpUrl
    comment_id: str | None = None
    dry_run: bool


class SentryReleaseSummary(BaseModel):
    version: str
    date_created: str | None = Field(default=None, alias="dateCreated")
    date_released: str | None = Field(default=None, alias="dateReleased")
    new_groups: int | None = Field(default=None, alias="newGroups")
    projects: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GetSentryReleaseInput(SentryProjectInput):
    version: str = Field(min_length=1)


class GetSentryReleaseOutput(BaseModel):
    context: str
    release: SentryReleaseSummary
