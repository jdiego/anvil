from __future__ import annotations

from urllib.parse import urlparse

from anvil.contexts import Context, ServiceContext, resolve_context
from anvil.exceptions import ContextNotFoundError, InvalidInputError
from anvil.keychain import async_keychain_get
from anvil.logging import get_logger
from anvil.sentry.client import (
    create_issue_comment,
    fetch_issue_with_latest_event,
    get_project_release,
    list_project_issues,
    update_issue,
)
from anvil.sentry.models import (
    AssignSentryIssueInput,
    AssignSentryIssueOutput,
    GetSentryIssueInput,
    GetSentryIssueOutput,
    GetSentryReleaseInput,
    GetSentryReleaseOutput,
    LinkSentryIssueToMergeRequestInput,
    LinkSentryIssueToMergeRequestOutput,
    ListSentryIssuesInput,
    ListSentryIssuesOutput,
    ResolveSentryContextInput,
    ResolveSentryContextOutput,
    ResolveSentryIssueInput,
    ResolveSentryIssueOutput,
    SentryIssueSummary,
    SentryReleaseSummary,
)

_logger = get_logger(__name__)


def _sentry_service(ctx_name: str, ctx: Context) -> ServiceContext:
    if ctx.sentry is None:
        raise ContextNotFoundError(
            f"Context {ctx_name!r} has no Sentry service configured. "
            f"List configured contexts via the contexts://list resource, "
            f"or run doctor_report to verify setup."
        )
    return ctx.sentry


async def resolve_sentry_context(payload: ResolveSentryContextInput) -> ResolveSentryContextOutput:
    """Identify which configured context owns a given Sentry/GitLab URL.

    Use when:
      - You have a Sentry or GitLab URL and need to know which configured
        organization/environment owns that host.
      - You want to verify that an issue or project URL belongs to a known
        anvil context before calling upstream APIs.

    Do not use when:
      - You need to authenticate against Sentry or GitLab; use doctor_report
        for end-to-end auth checks.

    Input example:
      {"url": "https://sentry.example.com/issues/42/"}

    Returns:
      The matched context name plus public Sentry and GitLab base URLs.

    Side effects:
      Read-only. No upstream calls and no secret lookup.
    """

    name, ctx = resolve_context(str(payload.url))
    sentry = _sentry_service(name, ctx)
    _logger.info("resolve_sentry_context", context=name)
    return ResolveSentryContextOutput(
        context=name,
        sentry_base_url=sentry.base_url,
        gitlab_base_url=ctx.gitlab.base_url if ctx.gitlab else None,
    )


async def get_sentry_issue(payload: GetSentryIssueInput) -> GetSentryIssueOutput:
    """Fetch a Sentry issue plus its latest event from a full issue URL.

    Use when:
      - You need to diagnose a production error from a full Sentry issue URL.
      - You need the issue title, culprit, level/status, counters, and the
        latest event payload for stack traces or request context.

    Do not use when:
      - You only need to know which context owns a URL; use
        resolve_sentry_context instead.
      - You do not have a URL containing /issues/<id>/.

    Input example:
      {"url": "https://sentry.example.com/issues/42/"}

    Returns:
      A compact issue summary and the latest event payload. The latest event
      can be large; extract only relevant frames/request data before showing
      it to a user or another model.

    Side effects:
      Read-only. Performs authenticated GET requests to Sentry.
    """

    url = str(payload.url)
    name, ctx = resolve_context(url)
    sentry = _sentry_service(name, ctx)
    issue_id = _extract_issue_id(url)
    token = await async_keychain_get(sentry.token_keychain)

    _logger.info(
        "get_sentry_issue",
        context=name,
        issue_id=issue_id,
        sentry_base_url=sentry.base_url,
    )

    issue, latest_event = await fetch_issue_with_latest_event(
        sentry.base_url,
        token,
        issue_id,
    )

    return GetSentryIssueOutput(
        context=name,
        issue=SentryIssueSummary.model_validate(issue),
        latest_event=latest_event,
    )


async def list_sentry_issues(payload: ListSentryIssuesInput) -> ListSentryIssuesOutput:
    """List compact Sentry issue summaries for triage.

    Use when:
      - You need recent/unresolved issues for a Sentry project.
      - You need to filter by Sentry query, environment, or relative age.

    Do not use when:
      - You already have a specific issue URL; use get_sentry_issue instead.

    Input example:
      {
        "context_url": "https://sentry.example.com/",
        "organization_slug": "example-org",
        "project_slug": "backend",
        "query": "is:unresolved level:error",
        "environment": "production",
        "age": "24h"
      }

    Returns:
      Compact issue summaries (default 25, max 100 via `limit`) plus `total`,
      `returned`, `truncated`, and `warnings` describing any trimming.

    Side effects:
      Read-only. Performs an authenticated GET request to Sentry.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    sentry = _sentry_service(name, ctx)
    token = await async_keychain_get(sentry.token_keychain)
    query = _issue_query(payload.query, payload.age)

    issues = await list_project_issues(
        sentry.base_url,
        token,
        payload.organization_slug,
        payload.project_slug,
        query=query,
        environment=payload.environment,
        limit=payload.limit,
    )

    total = len(issues)
    selected = issues[: payload.limit]
    returned = len(selected)
    # Sentry is asked for `limit` rows; a full page means more may exist upstream.
    truncated = returned < total or returned == payload.limit
    warnings: list[str] = []
    if truncated:
        warnings.append(
            f"Returned {returned} of at least {max(total, returned)} issues; "
            f"raise limit (max 100) or refine the query to see more."
        )

    _logger.info(
        "list_sentry_issues",
        context=name,
        organization_slug=payload.organization_slug,
        project_slug=payload.project_slug,
        count=returned,
        total=total,
    )
    return ListSentryIssuesOutput(
        context=name,
        issues=[SentryIssueSummary.model_validate(issue) for issue in selected],
        total=total,
        returned=returned,
        truncated=truncated,
        warnings=warnings,
    )


async def assign_sentry_issue(payload: AssignSentryIssueInput) -> AssignSentryIssueOutput:
    """Assign a Sentry issue to a user or team.

    Use when:
      - The user explicitly asks to assign ownership of a Sentry issue.
      - You know the Sentry assignee identifier, such as user email or team slug.

    Do not use when:
      - You only need triage information.
      - The user has not confirmed the assignment.

    Side effects:
      Destructive when confirm=true. Changes issue ownership in Sentry.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    sentry = _sentry_service(name, ctx)
    if not payload.confirm:
        return AssignSentryIssueOutput(
            context=name,
            issue=None,
            assigned_to=payload.assignee,
            dry_run=True,
        )

    token = await async_keychain_get(sentry.token_keychain)
    issue = await update_issue(
        sentry.base_url,
        token,
        payload.issue_id,
        {"assignedTo": payload.assignee},
    )
    return AssignSentryIssueOutput(
        context=name,
        issue=SentryIssueSummary.model_validate(issue),
        assigned_to=payload.assignee,
        dry_run=False,
    )


async def resolve_sentry_issue(payload: ResolveSentryIssueInput) -> ResolveSentryIssueOutput:
    """Resolve a Sentry issue, optionally marking the release that contains the fix.

    Use when:
      - The user explicitly confirms the Sentry issue should be resolved.
      - A fix has landed or the issue is otherwise no longer actionable.

    Do not use when:
      - The fix has not been deployed or the target release is uncertain.
      - You only want to add a link to an MR.

    Side effects:
      Destructive when confirm=true. Changes issue status in Sentry.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    sentry = _sentry_service(name, ctx)
    if not payload.confirm:
        return ResolveSentryIssueOutput(
            context=name,
            issue=None,
            in_release=payload.in_release,
            dry_run=True,
        )

    update_payload: dict[str, object] = {"status": "resolved"}
    if payload.in_release:
        update_payload["statusDetails"] = {"inRelease": payload.in_release}

    token = await async_keychain_get(sentry.token_keychain)
    issue = await update_issue(sentry.base_url, token, payload.issue_id, update_payload)
    return ResolveSentryIssueOutput(
        context=name,
        issue=SentryIssueSummary.model_validate(issue),
        in_release=payload.in_release,
        dry_run=False,
    )


async def link_sentry_issue_to_mr(
    payload: LinkSentryIssueToMergeRequestInput,
) -> LinkSentryIssueToMergeRequestOutput:
    """Add a Sentry issue comment linking it to a GitLab merge request.

    Use when:
      - A GitLab MR exists for a Sentry issue and you want the issue timeline to
        point to the fix.

    Do not use when:
      - The MR URL has not been verified.
      - The user has not confirmed creating a Sentry comment.

    Side effects:
      Destructive when confirm=true. Creates a visible Sentry issue comment.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    sentry = _sentry_service(name, ctx)
    if not payload.confirm:
        return LinkSentryIssueToMergeRequestOutput(
            context=name,
            issue_id=payload.issue_id,
            mr_url=payload.mr_url,
            dry_run=True,
        )

    token = await async_keychain_get(sentry.token_keychain)
    comment = await create_issue_comment(
        sentry.base_url,
        token,
        payload.issue_id,
        f"Fix merge request: {payload.mr_url}",
    )
    return LinkSentryIssueToMergeRequestOutput(
        context=name,
        issue_id=payload.issue_id,
        mr_url=payload.mr_url,
        comment_id=str(comment.get("id")) if comment.get("id") is not None else None,
        dry_run=False,
    )


async def get_sentry_release(payload: GetSentryReleaseInput) -> GetSentryReleaseOutput:
    """Fetch a Sentry project release summary.

    Use when:
      - You need to know whether a release exists in Sentry.
      - You need release metadata while checking whether a fix was deployed.

    Do not use when:
      - You need event details for an issue; use get_sentry_issue instead.

    Side effects:
      Read-only. Performs an authenticated GET request to Sentry.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    sentry = _sentry_service(name, ctx)
    token = await async_keychain_get(sentry.token_keychain)
    release = await get_project_release(
        sentry.base_url,
        token,
        payload.organization_slug,
        payload.project_slug,
        payload.version,
    )
    return GetSentryReleaseOutput(
        context=name,
        release=SentryReleaseSummary.model_validate(_release_summary_payload(release)),
    )


def _extract_issue_id(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    try:
        idx = parts.index("issues")
        return parts[idx + 1]
    except (ValueError, IndexError) as exc:
        raise InvalidInputError(
            f"Could not extract Sentry issue id from URL: {url}. "
            f"Provide a full issue URL containing '/issues/<id>/'; "
            f"use list_sentry_issues to discover valid issue URLs."
        ) from exc


def _issue_query(query: str | None, age: str | None) -> str | None:
    parts = []
    if query:
        parts.append(query)
    if age:
        parts.append(f"age:{age}")
    return " ".join(parts) if parts else None


def _release_summary_payload(release: dict[str, object]) -> dict[str, object]:
    projects = release.get("projects")
    project_slugs = []
    if isinstance(projects, list):
        for project in projects:
            if isinstance(project, dict) and project.get("slug") is not None:
                project_slugs.append(str(project["slug"]))

    payload = dict(release)
    payload["projects"] = project_slugs
    return payload
