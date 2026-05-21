from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl

from anvil.contexts import Context, ServiceContext, resolve_context
from anvil.exceptions import ContextNotFoundError
from anvil.gitlab.client import create_branch
from anvil.gitlab.models import GitLabProjectInput
from anvil.keychain import async_keychain_get
from anvil.logging import get_logger
from anvil.sentry.client import fetch_issue_with_latest_event
from anvil.sentry.models import SentryIssueSummary
from anvil.sentry.tools import _extract_issue_id

_logger = get_logger(__name__)


def _sentry_service(ctx_name: str, ctx: Context) -> ServiceContext:
    if ctx.sentry is None:
        raise ContextNotFoundError(f"Context {ctx_name!r} has no Sentry service configured")
    return ctx.sentry


def _gitlab_service(ctx_name: str, ctx: Context) -> ServiceContext:
    if ctx.gitlab is None:
        raise ContextNotFoundError(f"Context {ctx_name!r} has no GitLab service configured")
    return ctx.gitlab


class OpenFixMergeRequestFromSentryInput(GitLabProjectInput):
    sentry_issue_url: HttpUrl = Field(description="Full Sentry issue URL to investigate.")
    branch_name: str = Field(
        min_length=1,
        pattern=r"^[A-Za-z0-9._/-]+$",
        description="Branch name the local agent should use for the fix.",
    )
    base_ref: str = Field(
        default="main",
        min_length=1,
        description="GitLab ref used as the branch base.",
    )
    confirm: bool = Field(
        default=False,
        description="Safety flag. The remote branch is created only when true.",
    )


class OpenFixMergeRequestFromSentryOutput(BaseModel):
    sentry_context: str
    gitlab_context: str
    issue: SentryIssueSummary
    branch_name: str
    base_ref: str
    branch_created: bool
    dry_run: bool
    prompt: str
    warnings: list[str] = Field(default_factory=list)


async def open_fix_mr_from_sentry(
    payload: OpenFixMergeRequestFromSentryInput,
) -> OpenFixMergeRequestFromSentryOutput:
    """Prepare a Sentry-to-GitLab fix workflow for a local coding agent.

    Use when:
      - You have a Sentry issue URL and want Codex to implement a fix in a
        GitLab project.
      - You want one compact prompt with issue context, branch instructions,
        verification expectations, and MR guidance.

    Do not use when:
      - You need the MCP to edit files, commit, or push. The local agent does
        that in the target checkout.
      - You have not confirmed remote branch creation.

    Input example:
      {
        "sentry_issue_url": "https://sentry.example.com/issues/42/",
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "branch_name": "fix/sentry-42",
        "base_ref": "main",
        "confirm": false
      }

    Returns:
      Sentry issue summary, branch metadata, dry-run/branch-created status, and
      a prompt for the local agent to start coding.

    Side effects:
      Destructive when confirm=true. Creates a remote GitLab branch. It does not
      edit the local checkout, commit, push code, or create the MR.
    """

    sentry_url = str(payload.sentry_issue_url)
    gitlab_url = str(payload.context_url)
    sentry_context_name, sentry_ctx = resolve_context(sentry_url)
    gitlab_context_name, gitlab_ctx = resolve_context(gitlab_url)
    sentry = _sentry_service(sentry_context_name, sentry_ctx)
    gitlab = _gitlab_service(gitlab_context_name, gitlab_ctx)
    warnings: list[str] = []
    if sentry_context_name != gitlab_context_name:
        warnings.append(
            f"Sentry context {sentry_context_name!r} differs from GitLab context "
            f"{gitlab_context_name!r}."
        )

    issue_id = _extract_issue_id(sentry_url)
    sentry_token = await async_keychain_get(sentry.token_keychain)
    issue, latest_event = await fetch_issue_with_latest_event(
        sentry.base_url,
        sentry_token,
        issue_id,
    )
    issue_summary = SentryIssueSummary.model_validate(issue)

    branch_created = False
    if payload.confirm:
        gitlab_token = await async_keychain_get(gitlab.token_keychain)
        await create_branch(
            gitlab.base_url,
            gitlab_token,
            payload.project_path,
            payload.branch_name,
            payload.base_ref,
        )
        branch_created = True

    _logger.info(
        "open_fix_mr_from_sentry",
        sentry_context=sentry_context_name,
        gitlab_context=gitlab_context_name,
        issue_id=issue_id,
        project_path=payload.project_path,
        branch_name=payload.branch_name,
        branch_created=branch_created,
    )

    return OpenFixMergeRequestFromSentryOutput(
        sentry_context=sentry_context_name,
        gitlab_context=gitlab_context_name,
        issue=issue_summary,
        branch_name=payload.branch_name,
        base_ref=payload.base_ref,
        branch_created=branch_created,
        dry_run=not payload.confirm,
        prompt=_fix_prompt(payload, issue_summary, latest_event),
        warnings=warnings,
    )


def _fix_prompt(
    payload: OpenFixMergeRequestFromSentryInput,
    issue: SentryIssueSummary,
    latest_event: dict[str, object] | None,
) -> str:
    event_hint = "Latest event was not available."
    if latest_event:
        event_id = latest_event.get("id") or latest_event.get("eventID") or "unknown"
        event_hint = f"Latest event id: {event_id}"

    return f"""Implement a fix for this Sentry issue in the local repository.

Sentry issue:
- id: {issue.id}
- short id: {issue.short_id}
- title: {issue.title}
- culprit: {issue.culprit}
- level: {issue.level}
- status: {issue.status}
- permalink: {issue.permalink}
- {event_hint}

GitLab target:
- project: {payload.project_path}
- base ref: {payload.base_ref}
- branch: {payload.branch_name}

Local workflow:
1. In the target checkout, create or switch to branch {payload.branch_name}.
2. Inspect the stack frames and request context from get_sentry_issue if more detail is needed.
3. Find the smallest code change that addresses the root cause.
4. Add or update tests that reproduce the failure.
5. Run focused tests and lint/type checks relevant to the touched code.
6. Commit locally and push the branch.
7. Use create_gitlab_merge_request with confirm=false first, then ask for user confirmation.

MR draft guidance:
- Title: fix: handle {issue.short_id or issue.id}
- Description should include root cause, fix summary, Sentry issue URL, and test plan.
"""
