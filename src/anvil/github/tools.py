from __future__ import annotations

from typing import Any

from anvil.contexts import resolve_context
from anvil.exceptions import ContextNotFoundError
from anvil.github.client import (
    compare_refs,
    create_pull_request,
    get_pull_request,
    get_workflow_run,
    list_issue_comments,
    list_pull_request_files,
    list_pull_request_reviews,
    list_pull_requests,
    list_workflow_run_jobs,
)
from anvil.github.client import (
    get_actions_job_log as fetch_actions_job_log,
)
from anvil.github.models import (
    CompareRefsInput,
    CompareRefsOutput,
    CreatePullRequestInput,
    CreatePullRequestOutput,
    GetActionsJobLogInput,
    GetActionsJobLogOutput,
    GetPullRequestDiffInput,
    GetPullRequestDiffOutput,
    GetPullRequestInput,
    GetPullRequestOutput,
    GetWorkflowRunStatusInput,
    GetWorkflowRunStatusOutput,
    GitHubActionsJobSummary,
    GitHubWorkflowRunSummary,
    ListPullRequestsInput,
    ListPullRequestsOutput,
    PullRequestComment,
    PullRequestFileDiff,
    PullRequestReview,
    PullRequestSummary,
    ResolveGitHubContextInput,
    ResolveGitHubContextOutput,
)
from anvil.keychain import async_keychain_get
from anvil.logging import get_logger

_logger = get_logger(__name__)


def _github_service(ctx_name: str, ctx: object) -> Any:
    github = getattr(ctx, "github", None)
    if github is None:
        raise ContextNotFoundError(
            f"Context {ctx_name!r} has no GitHub service configured. "
            f"List configured contexts via the contexts://list resource, "
            f"or run doctor_report to verify setup."
        )
    return github


async def resolve_github_context(
    payload: ResolveGitHubContextInput,
) -> ResolveGitHubContextOutput:
    """Identify which configured context owns a given GitHub API URL.

    Use when:
      - You have a GitHub API URL and need to know which configured context
        owns that host.
      - You want to verify the public GitHub API base URL before calling
        upstream APIs.

    Do not use when:
      - You need to authenticate against GitHub; use doctor_report for an
        end-to-end auth check.

    Side effects:
      Read-only. No upstream calls and no secret lookup.
    """

    name, ctx = resolve_context(str(payload.url))
    github = _github_service(name, ctx)
    return ResolveGitHubContextOutput(context=name, github_base_url=github.base_url)


async def list_github_pull_requests(
    payload: ListPullRequestsInput,
) -> ListPullRequestsOutput:
    """List compact GitHub pull request summaries.

    Use when:
      - You need recent pull requests for a repository.
      - You need a bounded PR list filtered by state, base, or head.

    Returns:
      Compact PR summaries (default 25, max 100 via `limit`) plus `total`,
      `returned`, `truncated`, and `warnings` describing any trimming.

    Side effects:
      Read-only. Performs an authenticated GET request to GitHub.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    github = _github_service(name, ctx)
    token = await async_keychain_get(github.token_keychain)

    prs = await list_pull_requests(
        github.base_url,
        token,
        payload.repository,
        state=payload.state,
        base=payload.base,
        head=payload.head,
        limit=payload.limit,
    )
    total = len(prs)
    selected = prs[: payload.limit]
    summaries = [_pull_request_summary(pr) for pr in selected]
    returned = len(summaries)
    # GitHub is asked for `limit` rows; a full page means more may exist upstream.
    truncated = returned < total or returned == payload.limit
    warnings: list[str] = []
    if truncated:
        warnings.append(
            f"Returned {returned} of at least {max(total, returned)} pull requests; "
            f"raise limit (max 100) or filter by state/base/head to see more."
        )

    _logger.info(
        "list_github_pull_requests",
        context=name,
        repository=payload.repository,
        pull_requests=returned,
        total=total,
    )

    return ListPullRequestsOutput(
        context=name,
        pull_requests=summaries,
        total=total,
        returned=returned,
        truncated=truncated,
        warnings=warnings,
    )


async def create_github_pull_request(
    payload: CreatePullRequestInput,
) -> CreatePullRequestOutput:
    """Create a GitHub pull request in the configured context.

    Use when:
      - You have already pushed the head branch to GitHub.
      - You know the base branch (defaults to 'main').
      - You can produce a meaningful title and description.

    Do not use when:
      - You need to update, review, merge, or close an existing PR.
      - The head branch has not been pushed yet.
      - The user has not confirmed creation.

    Input example:
      {
        "context_url": "https://api.github.com/repos/owner/repo",
        "repository": "owner/repo",
        "head": "fix/sentry-42",
        "base": "main",
        "title": "fix: handle missing payload field",
        "body": "Root cause, fix, and test plan.",
        "draft": false,
        "confirm": false
      }

    Returns:
      A compact PR summary: context, number, html_url, title, draft, and
      dry_run. When confirm=false, no upstream call is made and number/html_url
      are null.

    Side effects:
      Destructive and non-idempotent when confirm=true. A successful call
      creates a new GitHub PR visible to other users and may trigger GitHub
      notifications. Reversing it requires manually closing the PR.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    github = _github_service(name, ctx)

    if not payload.confirm:
        _logger.info(
            "create_github_pull_request_dry_run",
            context=name,
            repository=payload.repository,
            head=payload.head,
            base=payload.base,
        )
        return CreatePullRequestOutput(
            context=name,
            number=None,
            html_url=None,
            title=payload.title,
            draft=payload.draft,
            dry_run=True,
        )

    token = await async_keychain_get(github.token_keychain)

    _logger.info(
        "create_github_pull_request",
        context=name,
        repository=payload.repository,
        head=payload.head,
        base=payload.base,
    )

    pr = await create_pull_request(
        github.base_url,
        token,
        payload.repository,
        head=payload.head,
        base=payload.base,
        title=payload.title,
        body=payload.body,
        draft=payload.draft,
    )

    return CreatePullRequestOutput(
        context=name,
        number=_int_or_none(pr.get("number")),
        html_url=_string_or_none(pr.get("html_url")),
        title=_string_or_none(pr.get("title")) or payload.title,
        draft=_bool_or_none(pr.get("draft")),
        dry_run=False,
    )


async def get_github_pull_request_diff(
    payload: GetPullRequestDiffInput,
) -> GetPullRequestDiffOutput:
    """Return GitHub pull request metadata plus bounded per-file patches.

    Use when:
      - You need to review the actual code changes of a pull request.
      - You want compact patches capped by file count and per-file line count.

    Side effects:
      Read-only. Performs authenticated GET requests to GitHub.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    github = _github_service(name, ctx)
    token = await async_keychain_get(github.token_keychain)

    pr = await get_pull_request(github.base_url, token, payload.repository, payload.pull_number)
    files = await list_pull_request_files(
        github.base_url,
        token,
        payload.repository,
        payload.pull_number,
    )
    returned = files[: payload.max_files]

    file_diffs = [
        _file_diff(file, max_lines_per_file=payload.max_lines_per_file) for file in returned
    ]

    _logger.info(
        "get_github_pull_request_diff",
        context=name,
        repository=payload.repository,
        pull_number=payload.pull_number,
        returned_files=len(file_diffs),
        total_files=len(files),
    )

    return GetPullRequestDiffOutput(
        context=name,
        pull_number=payload.pull_number,
        title=_string_or_none(pr.get("title")),
        state=_string_or_none(pr.get("state")),
        draft=_bool_or_none(pr.get("draft")),
        head_ref=_nested_string(pr, "head", "ref"),
        base_ref=_nested_string(pr, "base", "ref"),
        head_sha=_nested_string(pr, "head", "sha"),
        base_sha=_nested_string(pr, "base", "sha"),
        html_url=_string_or_none(pr.get("html_url")),
        total_files=len(files),
        returned_files=len(file_diffs),
        files_truncated=len(files) > len(file_diffs),
        files=file_diffs,
    )


async def get_github_pull_request(payload: GetPullRequestInput) -> GetPullRequestOutput:
    """Return consolidated GitHub pull request status for following up on review.

    Use when:
      - You need a PR's review state in one call: approvals, change requests,
        mergeability, and outstanding requested reviewers.
      - You want to read recent conversation comments to follow up on feedback.

    Do not use when:
      - You need the code diff; use get_github_pull_request_diff instead.
      - You only need to discover which PRs exist; use list_github_pull_requests.

    Input example:
      {
        "context_url": "https://api.github.com/repos/owner/repo",
        "repository": "owner/repo",
        "pull_number": 42,
        "max_comments": 20
      }

    Returns:
      PR metadata, mergeability, a derived review_decision plus per-reviewer
      latest review states, requested reviewers, and up to `max_comments` recent
      conversation comments.

    Side effects:
      Read-only. Performs authenticated GET requests to GitHub.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    github = _github_service(name, ctx)
    token = await async_keychain_get(github.token_keychain)

    pr = await get_pull_request(github.base_url, token, payload.repository, payload.pull_number)
    reviews = await list_pull_request_reviews(
        github.base_url, token, payload.repository, payload.pull_number
    )

    raw_comments: list[dict[str, Any]] = []
    if payload.max_comments > 0:
        raw_comments = await list_issue_comments(
            github.base_url, token, payload.repository, payload.pull_number
        )

    latest_reviews = _latest_reviews(reviews)
    approved_by = [r.user_login for r in latest_reviews if r.state == "APPROVED" and r.user_login]
    changes_requested_by = [
        r.user_login for r in latest_reviews if r.state == "CHANGES_REQUESTED" and r.user_login
    ]
    requested_reviewers = _requested_reviewers(pr)
    review_decision = _review_decision(changes_requested_by, approved_by, requested_reviewers)

    total_comments = len(raw_comments)
    comments_truncated = total_comments > payload.max_comments
    selected_comments = raw_comments[-payload.max_comments :] if payload.max_comments else []
    comments = [_pull_request_comment(comment) for comment in selected_comments]

    _logger.info(
        "get_github_pull_request",
        context=name,
        repository=payload.repository,
        pull_number=payload.pull_number,
        review_decision=review_decision,
    )

    return GetPullRequestOutput(
        context=name,
        number=_int_or_none(pr.get("number")) or payload.pull_number,
        title=_string_or_none(pr.get("title")),
        state=_string_or_none(pr.get("state")),
        draft=_bool_or_none(pr.get("draft")),
        merged=_bool_or_none(pr.get("merged")),
        user_login=_nested_string(pr, "user", "login"),
        head_ref=_nested_string(pr, "head", "ref"),
        base_ref=_nested_string(pr, "base", "ref"),
        html_url=_string_or_none(pr.get("html_url")),
        mergeable=_bool_or_none(pr.get("mergeable")),
        mergeable_state=_string_or_none(pr.get("mergeable_state")),
        review_decision=review_decision,
        approved_by=approved_by,
        changes_requested_by=changes_requested_by,
        requested_reviewers=requested_reviewers,
        reviews=latest_reviews,
        total_comments=total_comments,
        comments=comments,
        comments_truncated=comments_truncated,
    )


async def compare_github_refs(payload: CompareRefsInput) -> CompareRefsOutput:
    """Compare two GitHub refs and return a compact change summary.

    Side effects:
      Read-only. Performs an authenticated GET request to GitHub.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    github = _github_service(name, ctx)
    token = await async_keychain_get(github.token_keychain)

    compare = await compare_refs(
        github.base_url,
        token,
        payload.repository,
        payload.base_ref,
        payload.head_ref,
    )
    commits = compare.get("commits", []) if isinstance(compare.get("commits"), list) else []
    files = compare.get("files", []) if isinstance(compare.get("files"), list) else []

    return CompareRefsOutput(
        context=name,
        base_ref=payload.base_ref,
        head_ref=payload.head_ref,
        status=_string_or_none(compare.get("status")),
        ahead_by=_int_or_zero(compare.get("ahead_by")),
        behind_by=_int_or_zero(compare.get("behind_by")),
        total_commits=_int_or_zero(compare.get("total_commits")),
        files_changed=len(files),
        commit_messages=[
            message
            for commit in commits[:20]
            if (message := _nested_string(commit, "commit", "message"))
        ],
    )


async def get_github_workflow_run_status(
    payload: GetWorkflowRunStatusInput,
) -> GetWorkflowRunStatusOutput:
    """Return a compact GitHub Actions workflow run status and jobs.

    Side effects:
      Read-only. Performs authenticated GET requests to GitHub.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    github = _github_service(name, ctx)
    token = await async_keychain_get(github.token_keychain)

    run = await get_workflow_run(github.base_url, token, payload.repository, payload.run_id)
    jobs_payload = await list_workflow_run_jobs(
        github.base_url,
        token,
        payload.repository,
        payload.run_id,
    )
    jobs = [_job_summary(job) for job in jobs_payload]
    failed_jobs = [job for job in jobs if job.conclusion in {"failure", "cancelled", "timed_out"}]

    return GetWorkflowRunStatusOutput(
        context=name,
        run=GitHubWorkflowRunSummary.model_validate(run),
        jobs=jobs,
        failed_jobs=failed_jobs,
    )


async def get_github_actions_job_log(
    payload: GetActionsJobLogInput,
) -> GetActionsJobLogOutput:
    """Return the tail of a GitHub Actions job log.

    Side effects:
      Read-only. Performs an authenticated GET request to GitHub.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    github = _github_service(name, ctx)
    token = await async_keychain_get(github.token_keychain)

    log = await fetch_actions_job_log(github.base_url, token, payload.repository, payload.job_id)
    lines = log.splitlines()
    selected = lines[-payload.tail :]
    truncated = len(lines) > len(selected)

    return GetActionsJobLogOutput(
        context=name,
        job_id=payload.job_id,
        log_tail="\n".join(selected),
        returned_lines=len(selected),
        truncated=truncated,
    )


def _pull_request_summary(pr: dict[str, Any]) -> PullRequestSummary:
    return PullRequestSummary(
        number=int(pr["number"]),
        title=str(pr.get("title") or ""),
        state=str(pr.get("state") or ""),
        draft=_bool_or_none(pr.get("draft")),
        user_login=_nested_string(pr, "user", "login"),
        head_ref=_nested_string(pr, "head", "ref"),
        base_ref=_nested_string(pr, "base", "ref"),
        html_url=_string_or_none(pr.get("html_url")),
        updated_at=_string_or_none(pr.get("updated_at")),
    )


def _latest_reviews(reviews: list[dict[str, Any]]) -> list[PullRequestReview]:
    """Collapse a PR's review history to each reviewer's most recent decisive state.

    GitHub returns reviews oldest-first. A later COMMENTED review does not
    override an earlier APPROVED/CHANGES_REQUESTED, so only decisive states
    replace a reviewer's standing; pending/commented-only reviewers are dropped.
    """

    decisive = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
    latest: dict[str, PullRequestReview] = {}
    for review in reviews:
        login = _nested_string(review, "user", "login")
        state = _string_or_none(review.get("state"))
        if login is None or state is None:
            continue
        if state in decisive:
            latest[login] = PullRequestReview(
                user_login=login,
                state=state,
                submitted_at=_string_or_none(review.get("submitted_at")),
            )
    return [r for r in latest.values() if r.state != "DISMISSED"]


def _requested_reviewers(pr: dict[str, Any]) -> list[str]:
    requested = pr.get("requested_reviewers")
    if not isinstance(requested, list):
        return []
    logins: list[str] = []
    for reviewer in requested:
        login = reviewer.get("login") if isinstance(reviewer, dict) else None
        if isinstance(login, str):
            logins.append(login)
    return logins


def _review_decision(
    changes_requested_by: list[str],
    approved_by: list[str],
    requested_reviewers: list[str],
) -> str:
    if changes_requested_by:
        return "changes_requested"
    if requested_reviewers:
        return "review_required"
    if approved_by:
        return "approved"
    return "review_required"


def _pull_request_comment(comment: dict[str, Any]) -> PullRequestComment:
    return PullRequestComment(
        id=int(comment["id"]),
        user_login=_nested_string(comment, "user", "login"),
        body=str(comment.get("body") or ""),
        created_at=_string_or_none(comment.get("created_at")),
        html_url=_string_or_none(comment.get("html_url")),
    )


def _job_summary(job: dict[str, Any]) -> GitHubActionsJobSummary:
    return GitHubActionsJobSummary(
        id=int(job["id"]),
        name=str(job.get("name") or ""),
        status=_string_or_none(job.get("status")),
        conclusion=_string_or_none(job.get("conclusion")),
        started_at=_string_or_none(job.get("started_at")),
        completed_at=_string_or_none(job.get("completed_at")),
        html_url=_string_or_none(job.get("html_url")),
    )


def _file_diff(file: dict[str, Any], *, max_lines_per_file: int) -> PullRequestFileDiff:
    patch = str(file.get("patch") or "")
    lines = patch.splitlines()
    selected = lines[-max_lines_per_file:]
    return PullRequestFileDiff(
        filename=str(file.get("filename") or ""),
        status=_string_or_none(file.get("status")),
        additions=_int_or_none(file.get("additions")),
        deletions=_int_or_none(file.get("deletions")),
        changes=_int_or_none(file.get("changes")),
        patch="\n".join(selected),
        original_lines=len(lines),
        returned_lines=len(selected),
        truncated=len(lines) > len(selected),
    )


def _nested_string(payload: dict[str, Any], *keys: str) -> str | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _string_or_none(current)


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) else 0
