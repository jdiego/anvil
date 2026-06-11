from __future__ import annotations

import asyncio
from typing import Any

from anvil.contexts import Context, ServiceContext, resolve_context
from anvil.exceptions import ContextNotFoundError, UpstreamHTTPError
from anvil.gitlab.client import (
    approve_merge_request,
    cancel_pipeline,
    compare_refs,
    create_merge_request,
    get_job_trace,
    get_latest_pipeline_for_ref,
    get_merge_request,
    get_merge_request_approvals,
    get_merge_request_changes,
    get_pipeline,
    list_merge_request_discussions,
    list_merge_requests,
    list_pipeline_jobs,
    post_merge_request_discussion,
    post_merge_request_note,
    retry_job,
    trigger_pipeline,
    update_merge_request,
)
from anvil.gitlab.models import (
    ApproveMergeRequestInput,
    ApproveMergeRequestOutput,
    CancelPipelineInput,
    CancelPipelineOutput,
    CompareRefsInput,
    CompareRefsOutput,
    CreateMergeRequestInput,
    CreateMergeRequestOutput,
    DiagnosePipelineFailureInput,
    DiagnosePipelineFailureOutput,
    FailedJobDiagnosis,
    FailureKind,
    GetJobLogInput,
    GetJobLogOutput,
    GetMergeRequestDiffInput,
    GetMergeRequestDiffOutput,
    GetMergeRequestInput,
    GetMergeRequestOutput,
    GetPipelineStatusInput,
    GetPipelineStatusOutput,
    GitLabJobSummary,
    GitLabPipelineSummary,
    ListMergeRequestsInput,
    ListMergeRequestsOutput,
    MergeRequestFileDiff,
    MergeRequestNote,
    MergeRequestPosition,
    MergeRequestSummary,
    PostMergeRequestCommentInput,
    PostMergeRequestCommentOutput,
    PostMergeRequestLineCommentInput,
    PostMergeRequestLineCommentOutput,
    RetryFailedJobsInput,
    RetryFailedJobsOutput,
    SetMergeRequestReadyInput,
    SetMergeRequestReadyOutput,
    TriggerPipelineInput,
    TriggerPipelineOutput,
    UpdateMergeRequestInput,
    UpdateMergeRequestOutput,
)
from anvil.keychain import async_keychain_get
from anvil.logging import get_logger

_logger = get_logger(__name__)


def _gitlab_service(ctx_name: str, ctx: Context) -> ServiceContext:
    if ctx.gitlab is None:
        raise ContextNotFoundError(
            f"Context {ctx_name!r} has no GitLab service configured. "
            f"List configured contexts via the contexts://list resource, "
            f"or run doctor_report to verify setup."
        )
    return ctx.gitlab


async def get_gitlab_pipeline_status(
    payload: GetPipelineStatusInput,
) -> GetPipelineStatusOutput:
    """Return a compact GitLab pipeline status and failed jobs.

    Use when:
      - You need the current CI status for a branch/tag/ref or known pipeline id.
      - You need to identify which jobs failed before fetching logs.

    Do not use when:
      - You need full job traces; call get_gitlab_job_log for a specific job.
      - You intend to retry or cancel CI; this tool is read-only.

    Input examples:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "ref": "main"
      }
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "pipeline_id": 123
      }

    Returns:
      Pipeline id/ref/status/web_url and failed job summaries.

    Side effects:
      Read-only. Performs authenticated GET requests to GitLab.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)
    warnings: list[str] = []

    pipeline: dict[str, Any] | None
    if payload.pipeline_id is not None:
        pipeline = await get_pipeline(
            gitlab.base_url,
            token,
            payload.project_path,
            payload.pipeline_id,
        )
    else:
        pipeline = await get_latest_pipeline_for_ref(
            gitlab.base_url,
            token,
            payload.project_path,
            payload.ref or "",
        )
        if pipeline is None:
            return GetPipelineStatusOutput(
                context=name,
                pipeline=None,
                failed_jobs=[],
                warnings=[f"No pipeline found for ref: {payload.ref}"],
            )

    pipeline_id = int(pipeline["id"])
    jobs = await list_pipeline_jobs(
        gitlab.base_url,
        token,
        payload.project_path,
        pipeline_id,
    )
    failed_jobs = [_job_summary(job) for job in jobs if job.get("status") == "failed"]

    _logger.info(
        "get_pipeline_status",
        context=name,
        project_path=payload.project_path,
        pipeline_id=pipeline_id,
        failed_jobs=len(failed_jobs),
    )

    return GetPipelineStatusOutput(
        context=name,
        pipeline=GitLabPipelineSummary.model_validate(pipeline),
        failed_jobs=failed_jobs,
        warnings=warnings,
    )


async def get_gitlab_job_log(payload: GetJobLogInput) -> GetJobLogOutput:
    """Return the tail of a GitLab CI job trace.

    Use when:
      - You already know the failed GitLab job id.
      - You need a bounded log tail suitable for an agent context window.

    Do not use when:
      - You need pipeline status first; call get_gitlab_pipeline_status.
      - You need the full log; open the GitLab job URL in a browser instead.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "job_id": 456,
        "tail": 200
      }

    Returns:
      The last tail lines, line count, and whether earlier lines were omitted.

    Side effects:
      Read-only. Performs an authenticated GET request to GitLab.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)

    trace = await get_job_trace(gitlab.base_url, token, payload.project_path, payload.job_id)
    lines = trace.splitlines()
    selected = lines[-payload.tail :]
    truncated = len(lines) > len(selected)

    _logger.info(
        "get_job_log",
        context=name,
        project_path=payload.project_path,
        job_id=payload.job_id,
        returned_lines=len(selected),
        truncated=truncated,
    )

    return GetJobLogOutput(
        context=name,
        job_id=payload.job_id,
        trace_tail="\n".join(selected),
        returned_lines=len(selected),
        truncated=truncated,
    )


async def diagnose_gitlab_pipeline_failure(
    payload: DiagnosePipelineFailureInput,
) -> DiagnosePipelineFailureOutput:
    """Diagnose a failed GitLab pipeline from failed jobs and log tails.

    Use when:
      - A GitLab pipeline failed and you want one compact, agent-friendly
        diagnostic instead of manually fetching each failed job log.
      - You need a first-pass classification such as lint, test, build,
        dependency, infra, or unknown.

    Do not use when:
      - You need to retry/cancel jobs; this tool is read-only.
      - You need complete logs for every job; this returns bounded tails only.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "pipeline_id": 123,
        "tail": 120,
        "max_jobs": 5
      }

    Returns:
      Pipeline summary, failed job count, analyzed failed jobs with log tails,
      a likely failure kind, summary text, and practical next steps.

    Side effects:
      Read-only. Performs authenticated GET requests to GitLab.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)

    pipeline = await get_pipeline(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.pipeline_id,
    )
    jobs = await list_pipeline_jobs(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.pipeline_id,
    )
    failed_jobs = [job for job in jobs if job.get("status") == "failed"]
    analyzed_jobs = failed_jobs[: payload.max_jobs]

    traces = await asyncio.gather(
        *[
            get_job_trace(gitlab.base_url, token, payload.project_path, int(job["id"]))
            for job in analyzed_jobs
        ]
    )

    diagnoses = [
        _job_diagnosis(job, trace, payload.tail)
        for job, trace in zip(analyzed_jobs, traces, strict=True)
    ]
    likely_failure_kind = _dominant_failure_kind(diagnoses)
    warnings = []
    if len(failed_jobs) > len(analyzed_jobs):
        warnings.append(
            f"Analyzed {len(analyzed_jobs)} of {len(failed_jobs)} failed jobs; "
            "increase max_jobs for more detail."
        )

    _logger.info(
        "diagnose_pipeline_failure",
        context=name,
        project_path=payload.project_path,
        pipeline_id=payload.pipeline_id,
        failed_jobs=len(failed_jobs),
        analyzed_jobs=len(analyzed_jobs),
        likely_failure_kind=likely_failure_kind,
    )

    return DiagnosePipelineFailureOutput(
        context=name,
        pipeline=GitLabPipelineSummary.model_validate(pipeline),
        failed_jobs_count=len(failed_jobs),
        analyzed_jobs_count=len(analyzed_jobs),
        likely_failure_kind=likely_failure_kind,
        diagnoses=diagnoses,
        summary=_diagnosis_summary(
            pipeline_status=str(pipeline["status"]),
            failed_jobs_count=len(failed_jobs),
            likely_failure_kind=likely_failure_kind,
        ),
        next_steps=_next_steps(likely_failure_kind),
        warnings=warnings,
    )


async def retry_gitlab_failed_jobs(payload: RetryFailedJobsInput) -> RetryFailedJobsOutput:
    """Retry only failed jobs in a GitLab pipeline.

    Use when:
      - A pipeline failed due to flaky jobs or transient infrastructure.
      - You explicitly want to retry failed jobs without retrying successful jobs.

    Do not use when:
      - You have not inspected the failure or asked the user for confirmation.
      - The failure is deterministic and needs a code/config fix first.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "pipeline_id": 123,
        "confirm": false
      }

    Returns:
      Jobs that would be retried in dry-run mode, or jobs retried by GitLab when
      confirm=true.

    Side effects:
      Destructive and non-idempotent when confirm=true. Creates new retry jobs
      in GitLab and may consume runner capacity.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)
    jobs = await list_pipeline_jobs(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.pipeline_id,
    )
    failed_jobs = [job for job in jobs if job.get("status") == "failed"]

    if not payload.confirm:
        _logger.info(
            "retry_failed_jobs_dry_run",
            context=name,
            project_path=payload.project_path,
            pipeline_id=payload.pipeline_id,
            failed_jobs=len(failed_jobs),
        )
        return RetryFailedJobsOutput(
            context=name,
            pipeline_id=payload.pipeline_id,
            retried_jobs=[_job_summary(job) for job in failed_jobs],
            dry_run=True,
        )

    retried = await asyncio.gather(
        *[
            retry_job(gitlab.base_url, token, payload.project_path, int(job["id"]))
            for job in failed_jobs
        ]
    )
    _logger.info(
        "retry_failed_jobs",
        context=name,
        project_path=payload.project_path,
        pipeline_id=payload.pipeline_id,
        retried_jobs=len(retried),
    )
    return RetryFailedJobsOutput(
        context=name,
        pipeline_id=payload.pipeline_id,
        retried_jobs=[_job_summary(job) for job in retried],
        dry_run=False,
    )


async def cancel_gitlab_pipeline(payload: CancelPipelineInput) -> CancelPipelineOutput:
    """Cancel a GitLab pipeline.

    Use when:
      - The user explicitly wants to stop a running/pending pipeline.
      - The pipeline is obsolete because a newer commit or pipeline supersedes it.

    Do not use when:
      - You are only diagnosing CI status; use read-only pipeline tools.
      - The user has not confirmed cancellation.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "pipeline_id": 123,
        "confirm": false
      }

    Returns:
      Dry-run metadata or the compact cancelled pipeline summary.

    Side effects:
      Destructive when confirm=true. Stops GitLab jobs in the pipeline.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)

    if not payload.confirm:
        _logger.info(
            "cancel_pipeline_dry_run",
            context=name,
            project_path=payload.project_path,
            pipeline_id=payload.pipeline_id,
        )
        return CancelPipelineOutput(context=name, pipeline=None, dry_run=True)

    token = await async_keychain_get(gitlab.token_keychain)
    pipeline = await cancel_pipeline(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.pipeline_id,
    )
    _logger.info(
        "cancel_pipeline",
        context=name,
        project_path=payload.project_path,
        pipeline_id=payload.pipeline_id,
    )
    return CancelPipelineOutput(
        context=name,
        pipeline=GitLabPipelineSummary.model_validate(pipeline),
        dry_run=False,
    )


async def post_gitlab_mr_comment(
    payload: PostMergeRequestCommentInput,
) -> PostMergeRequestCommentOutput:
    """Post a GitLab merge request comment or line-level discussion.

    Use when:
      - The user explicitly asks you to comment on an MR.
      - You have a review note, test result, or implementation context to post.

    Do not use when:
      - The comment body has not been shown to the user.
      - You need to create or update an MR instead.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "mr_iid": 7,
        "body": "The failure appears to be in the serializer test.",
        "confirm": false
      }

    Returns:
      Dry-run metadata or GitLab note/discussion ids.

    Side effects:
      Destructive when confirm=true. Posts visible MR discussion content.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)

    if not payload.confirm:
        _logger.info(
            "post_mr_comment_dry_run",
            context=name,
            project_path=payload.project_path,
            mr_iid=payload.mr_iid,
            positioned=payload.position is not None,
        )
        return PostMergeRequestCommentOutput(
            context=name,
            mr_iid=payload.mr_iid,
            dry_run=True,
        )

    token = await async_keychain_get(gitlab.token_keychain)
    if payload.position is None:
        note = await post_merge_request_note(
            gitlab.base_url,
            token,
            payload.project_path,
            payload.mr_iid,
            payload.body,
        )
        return PostMergeRequestCommentOutput(
            context=name,
            mr_iid=payload.mr_iid,
            note_id=int(note["id"]),
            web_url=note.get("web_url") if isinstance(note.get("web_url"), str) else None,
            dry_run=False,
        )

    discussion = await post_merge_request_discussion(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.mr_iid,
        {
            "body": payload.body,
            "position": payload.position.model_dump(mode="json", exclude_none=True),
        },
    )
    return PostMergeRequestCommentOutput(
        context=name,
        mr_iid=payload.mr_iid,
        discussion_id=str(discussion["id"]),
        dry_run=False,
    )


async def post_gitlab_mr_line_comment(
    payload: PostMergeRequestLineCommentInput,
) -> PostMergeRequestLineCommentOutput:
    """Post a line-level discussion on a GitLab merge request diff.

    Use when:
      - The user has reviewed an MR diff and wants to leave inline feedback
        anchored to a specific file/line, not a top-level note.
      - You have a `new_path` + `new_line` (added/modified line) or `old_path`
        + `old_line` (removed line) from the MR diff.

    Do not use when:
      - The comment is not anchored to a specific line; use post_gitlab_mr_comment.
      - The MR has been updated since the diff was read; the SHAs are re-fetched
        each call, but the line numbers must still match the current head.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "mr_iid": 7,
        "new_path": "src/foo.py",
        "new_line": 42,
        "body": "This branch is unreachable.",
        "confirm": false
      }

    Returns:
      The created GitLab discussion id and the diff position used. In dry-run
      mode (confirm=false) the same position fields are returned but no comment
      is posted.

    Side effects:
      Destructive when confirm=true. Posts a visible MR discussion anchored to
      the diff position. Always fetches MR `diff_refs` to derive base/start/head
      SHAs, which is read-only.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)

    mr = await get_merge_request_changes(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.mr_iid,
    )
    raw_refs = mr.get("diff_refs")
    if not isinstance(raw_refs, dict):
        raise ValueError(f"MR !{payload.mr_iid} did not return diff_refs.")
    base_sha = str(raw_refs.get("base_sha") or "")
    start_sha = str(raw_refs.get("start_sha") or "")
    head_sha = str(raw_refs.get("head_sha") or "")
    if not (base_sha and start_sha and head_sha):
        raise ValueError(f"MR !{payload.mr_iid} diff_refs is missing required SHAs.")

    position = MergeRequestPosition(
        base_sha=base_sha,
        start_sha=start_sha,
        head_sha=head_sha,
        new_path=payload.new_path,
        old_path=payload.old_path,
        new_line=payload.new_line,
        old_line=payload.old_line,
    )

    if not payload.confirm:
        _logger.info(
            "post_mr_line_comment_dry_run",
            context=name,
            project_path=payload.project_path,
            mr_iid=payload.mr_iid,
            new_path=payload.new_path,
            new_line=payload.new_line,
        )
        return PostMergeRequestLineCommentOutput(
            context=name,
            mr_iid=payload.mr_iid,
            new_path=payload.new_path,
            old_path=payload.old_path,
            new_line=payload.new_line,
            old_line=payload.old_line,
            base_sha=base_sha,
            start_sha=start_sha,
            head_sha=head_sha,
            dry_run=True,
        )

    discussion = await post_merge_request_discussion(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.mr_iid,
        {
            "body": payload.body,
            "position": position.model_dump(mode="json", exclude_none=True),
        },
    )
    _logger.info(
        "post_mr_line_comment",
        context=name,
        project_path=payload.project_path,
        mr_iid=payload.mr_iid,
        new_path=payload.new_path,
        new_line=payload.new_line,
    )
    return PostMergeRequestLineCommentOutput(
        context=name,
        mr_iid=payload.mr_iid,
        discussion_id=str(discussion["id"]),
        new_path=payload.new_path,
        old_path=payload.old_path,
        new_line=payload.new_line,
        old_line=payload.old_line,
        base_sha=base_sha,
        start_sha=start_sha,
        head_sha=head_sha,
        dry_run=False,
    )


async def approve_gitlab_merge_request(
    payload: ApproveMergeRequestInput,
) -> ApproveMergeRequestOutput:
    """Approve a GitLab merge request.

    Use when:
      - The user explicitly asks you to approve a reviewed MR.
      - Required checks/review criteria have already been evaluated.

    Do not use when:
      - You have not reviewed the diff, pipeline, and context.
      - The user has not confirmed approval.

    Side effects:
      Destructive when confirm=true. Adds your GitLab approval to the MR.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    if not payload.confirm:
        return ApproveMergeRequestOutput(
            context=name,
            mr_iid=payload.mr_iid,
            approved=False,
            dry_run=True,
        )

    token = await async_keychain_get(gitlab.token_keychain)
    await approve_merge_request(gitlab.base_url, token, payload.project_path, payload.mr_iid)
    _logger.info(
        "approve_mr", context=name, project_path=payload.project_path, mr_iid=payload.mr_iid
    )
    return ApproveMergeRequestOutput(
        context=name,
        mr_iid=payload.mr_iid,
        approved=True,
        dry_run=False,
    )


async def set_gitlab_mr_ready(
    payload: SetMergeRequestReadyInput,
) -> SetMergeRequestReadyOutput:
    """Mark a draft GitLab merge request as ready.

    Use when:
      - The user explicitly asks to move an MR from Draft/WIP to ready.
      - The branch, description, and pipeline are ready for review.

    Do not use when:
      - The MR still needs local changes or validation.
      - The user has not confirmed the state change.

    Side effects:
      Destructive when confirm=true. Changes MR review state in GitLab.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    if not payload.confirm:
        return SetMergeRequestReadyOutput(context=name, mr_iid=payload.mr_iid, dry_run=True)

    token = await async_keychain_get(gitlab.token_keychain)
    mr = await update_merge_request(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.mr_iid,
        {"draft": False},
    )
    return SetMergeRequestReadyOutput(
        context=name,
        mr_iid=payload.mr_iid,
        title=str(mr["title"]) if mr.get("title") is not None else None,
        draft=bool(mr["draft"]) if mr.get("draft") is not None else None,
        web_url=mr.get("web_url") if isinstance(mr.get("web_url"), str) else None,
        dry_run=False,
    )


async def update_gitlab_merge_request(
    payload: UpdateMergeRequestInput,
) -> UpdateMergeRequestOutput:
    """Update the title and/or description of an existing GitLab merge request.

    Use when:
      - The user asks to edit an MR's description or rename its title.
      - You have the MR iid and the new text to apply.

    Do not use when:
      - You need to change MR state (close/reopen, draft/ready) or merge it;
        use set_gitlab_mr_ready or a dedicated tool. This edits text only.
      - You want to add a comment instead of replacing the description.
      - The user has not confirmed the edit.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "mr_iid": 7,
        "description": "Updated rationale, screenshots, and test plan.",
        "confirm": false
      }

    Returns:
      A compact MR summary: context, iid, title, web_url, updated_fields, and
      dry_run. When confirm=false, no upstream call is made and title/web_url
      are null.

    Side effects:
      Destructive when confirm=true: replaces the MR title and/or description in
      full, visible to other users. It does not change review or merge state.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)

    update_payload: dict[str, Any] = {}
    if payload.title is not None:
        update_payload["title"] = payload.title
    if payload.description is not None:
        update_payload["description"] = payload.description
    updated_fields = sorted(update_payload)

    if not payload.confirm:
        _logger.info(
            "update_gitlab_merge_request_dry_run",
            context=name,
            project_path=payload.project_path,
            mr_iid=payload.mr_iid,
            updated_fields=updated_fields,
        )
        return UpdateMergeRequestOutput(
            context=name,
            iid=payload.mr_iid,
            title=payload.title,
            web_url=None,
            updated_fields=updated_fields,
            dry_run=True,
        )

    token = await async_keychain_get(gitlab.token_keychain)

    _logger.info(
        "update_gitlab_merge_request",
        context=name,
        project_path=payload.project_path,
        mr_iid=payload.mr_iid,
        updated_fields=updated_fields,
    )

    mr = await update_merge_request(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.mr_iid,
        update_payload,
    )

    return UpdateMergeRequestOutput(
        context=name,
        iid=int(mr["iid"]) if mr.get("iid") is not None else payload.mr_iid,
        title=str(mr["title"]) if mr.get("title") is not None else payload.title,
        web_url=mr.get("web_url") if isinstance(mr.get("web_url"), str) else None,
        updated_fields=updated_fields,
        dry_run=False,
    )


async def trigger_gitlab_pipeline(payload: TriggerPipelineInput) -> TriggerPipelineOutput:
    """Trigger a new GitLab pipeline for a ref.

    Use when:
      - The user explicitly asks to run a new pipeline.
      - You need to pass bounded CI variables for a known ref.

    Do not use when:
      - You only need current pipeline status.
      - The variables may contain secrets; this tool logs keys indirectly via GitLab.

    Side effects:
      Destructive and non-idempotent when confirm=true. Creates a new pipeline
      and may consume runner capacity.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    if not payload.confirm:
        return TriggerPipelineOutput(context=name, pipeline=None, dry_run=True)

    token = await async_keychain_get(gitlab.token_keychain)
    pipeline = await trigger_pipeline(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.ref,
        payload.variables,
    )
    return TriggerPipelineOutput(
        context=name,
        pipeline=GitLabPipelineSummary.model_validate(pipeline),
        dry_run=False,
    )


async def list_gitlab_merge_requests(
    payload: ListMergeRequestsInput,
) -> ListMergeRequestsOutput:
    """List compact GitLab merge request summaries.

    Use when:
      - You need to discover open/merged/closed MRs for a project.
      - You need recent MRs by a specific author username.

    Do not use when:
      - You need MR diffs or comments; this returns discovery metadata only.
      - You intend to mutate an MR; this tool is read-only.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "state": "opened",
        "author": "alice"
      }

    Returns:
      Compact MR summaries (default 25, max 100 via `limit`) with iid, title,
      state, branches, author, updated_at, and web_url, plus `total`, `returned`,
      `truncated`, and `warnings` describing any trimming.

    Side effects:
      Read-only. Performs an authenticated GET request to GitLab.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)

    merge_requests = await list_merge_requests(
        gitlab.base_url,
        token,
        payload.project_path,
        state=payload.state,
        author=payload.author,
        limit=payload.limit,
    )

    total = len(merge_requests)
    selected = merge_requests[: payload.limit]
    returned = len(selected)
    # GitLab is asked for `limit` rows; a full page means more may exist upstream.
    truncated = returned < total or returned == payload.limit
    warnings: list[str] = []
    if truncated:
        warnings.append(
            f"Returned {returned} of at least {max(total, returned)} merge requests; "
            f"raise limit (max 100) or filter by state/author to see more."
        )

    _logger.info(
        "list_merge_requests",
        context=name,
        project_path=payload.project_path,
        state=payload.state,
        count=returned,
        total=total,
    )

    return ListMergeRequestsOutput(
        context=name,
        merge_requests=[_mr_summary(mr) for mr in selected],
        total=total,
        returned=returned,
        truncated=truncated,
        warnings=warnings,
    )


async def compare_gitlab_refs(payload: CompareRefsInput) -> CompareRefsOutput:
    """Compare two GitLab refs and return a compact change summary.

    Use when:
      - You need to know what changed between two branches, tags, or SHAs.
      - You are preparing release notes or checking what entered since a tag.

    Do not use when:
      - You need full file diffs for code review; this returns counts and commit
        titles only.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "from_ref": "v1.0.0",
        "to_ref": "main"
      }

    Returns:
      Commit/diff counts, whether refs are equal, timeout flag, and up to 20
      commit titles.

    Side effects:
      Read-only. Performs an authenticated GET request to GitLab.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)

    compare = await compare_refs(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.from_ref,
        payload.to_ref,
    )
    raw_commits = compare.get("commits")
    raw_diffs = compare.get("diffs")
    commits: list[object] = raw_commits if isinstance(raw_commits, list) else []
    diffs: list[object] = raw_diffs if isinstance(raw_diffs, list) else []

    _logger.info(
        "compare_refs",
        context=name,
        project_path=payload.project_path,
        from_ref=payload.from_ref,
        to_ref=payload.to_ref,
        commits_count=len(commits),
        diffs_count=len(diffs),
    )

    return CompareRefsOutput(
        context=name,
        from_ref=payload.from_ref,
        to_ref=payload.to_ref,
        compare_timeout=bool(compare.get("compare_timeout")),
        same=bool(compare.get("same")),
        commits_count=len(commits),
        diffs_count=len(diffs),
        commit_titles=[
            _commit_title(commit) for commit in commits[:20] if isinstance(commit, dict)
        ],
    )


async def get_gitlab_mr_diff(payload: GetMergeRequestDiffInput) -> GetMergeRequestDiffOutput:
    """Return a GitLab merge request diff bounded by file and per-file line caps.

    Use when:
      - You need to review the actual code changes of an MR before approving,
        commenting, or merging.
      - You want one compact, agent-friendly response with MR metadata plus
        truncated file diffs.

    Do not use when:
      - You only need MR discovery metadata; use list_gitlab_merge_requests.
      - You need ref-to-ref differences outside an MR; use compare_gitlab_refs.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "mr_iid": 7,
        "max_files": 20,
        "max_lines_per_file": 400
      }

    Returns:
      MR metadata (title, state, branches, SHAs, web_url) plus up to `max_files`
      file diffs. Each file diff is truncated to the last `max_lines_per_file`
      lines and reports its original/returned line counts and a truncation flag.

    Side effects:
      Read-only. Performs an authenticated GET request to GitLab.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)

    mr = await get_merge_request_changes(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.mr_iid,
    )

    raw_changes = mr.get("changes")
    changes: list[dict[str, Any]] = (
        [c for c in raw_changes if isinstance(c, dict)] if isinstance(raw_changes, list) else []
    )
    total_files = len(changes)
    selected = changes[: payload.max_files]
    files = [_mr_file_diff(change, payload.max_lines_per_file) for change in selected]

    warnings: list[str] = []
    if total_files > len(selected):
        warnings.append(
            f"Returned {len(selected)} of {total_files} changed files; increase max_files for more."
        )
    if any(f.truncated for f in files):
        warnings.append(
            "One or more file diffs were truncated; increase max_lines_per_file for fuller context."
        )

    raw_diff_refs = mr.get("diff_refs")
    diff_refs: dict[str, Any] = raw_diff_refs if isinstance(raw_diff_refs, dict) else {}

    _logger.info(
        "get_mr_diff",
        context=name,
        project_path=payload.project_path,
        mr_iid=payload.mr_iid,
        total_files=total_files,
        returned_files=len(files),
    )

    return GetMergeRequestDiffOutput(
        context=name,
        mr_iid=payload.mr_iid,
        title=str(mr["title"]) if mr.get("title") is not None else None,
        state=str(mr["state"]) if mr.get("state") is not None else None,
        source_branch=(str(mr["source_branch"]) if mr.get("source_branch") is not None else None),
        target_branch=(str(mr["target_branch"]) if mr.get("target_branch") is not None else None),
        base_sha=str(diff_refs["base_sha"]) if diff_refs.get("base_sha") is not None else None,
        start_sha=str(diff_refs["start_sha"]) if diff_refs.get("start_sha") is not None else None,
        head_sha=str(diff_refs["head_sha"]) if diff_refs.get("head_sha") is not None else None,
        web_url=mr.get("web_url") if isinstance(mr.get("web_url"), str) else None,
        total_files=total_files,
        returned_files=len(files),
        files_truncated=total_files > len(selected),
        files=files,
        warnings=warnings,
    )


async def get_gitlab_merge_request(payload: GetMergeRequestInput) -> GetMergeRequestOutput:
    """Return consolidated GitLab merge request status for following up on review.

    Use when:
      - You need an MR's review state in one call: approvals, mergeability, and
        whether discussion threads are still unresolved.
      - You want to read recent (non-system) discussion notes to follow up on
        reviewer feedback.

    Do not use when:
      - You need the code diff; use get_gitlab_mr_diff instead.
      - You only need to discover which MRs exist; use list_gitlab_merge_requests.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "mr_iid": 7,
        "max_notes": 20
      }

    Returns:
      MR metadata, merge/approval status, thread counts, and up to `max_notes`
      recent notes. `approved` and approval counts are null (with a warning)
      when the approvals API is unavailable for the project.

    Side effects:
      Read-only. Performs authenticated GET requests to GitLab.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)
    token = await async_keychain_get(gitlab.token_keychain)

    warnings: list[str] = []

    mr = await get_merge_request(gitlab.base_url, token, payload.project_path, payload.mr_iid)

    approvals: dict[str, Any] = {}
    try:
        approvals = await get_merge_request_approvals(
            gitlab.base_url, token, payload.project_path, payload.mr_iid
        )
    except UpstreamHTTPError as exc:
        warnings.append(f"Approval status unavailable: {exc}")

    discussions: list[dict[str, Any]] = []
    if payload.max_notes > 0:
        discussions = await list_merge_request_discussions(
            gitlab.base_url, token, payload.project_path, payload.mr_iid
        )

    author = mr.get("author")
    author_username = author.get("username") if isinstance(author, dict) else None

    total_threads, unresolved_threads, all_notes = _summarize_discussions(discussions)
    notes_truncated = len(all_notes) > payload.max_notes
    notes = all_notes[-payload.max_notes :] if payload.max_notes else []

    _logger.info(
        "get_gitlab_merge_request",
        context=name,
        project_path=payload.project_path,
        mr_iid=payload.mr_iid,
        unresolved_threads=unresolved_threads,
        approvals_left=_int_or_none(approvals.get("approvals_left")),
    )

    return GetMergeRequestOutput(
        context=name,
        iid=int(mr["iid"]) if mr.get("iid") is not None else payload.mr_iid,
        title=_str_or_none(mr.get("title")),
        state=_str_or_none(mr.get("state")),
        draft=_bool_or_none(mr.get("draft")),
        author_username=_str_or_none(author_username),
        source_branch=_str_or_none(mr.get("source_branch")),
        target_branch=_str_or_none(mr.get("target_branch")),
        web_url=mr.get("web_url") if isinstance(mr.get("web_url"), str) else None,
        merge_status=_str_or_none(mr.get("merge_status")),
        detailed_merge_status=_str_or_none(mr.get("detailed_merge_status")),
        has_conflicts=_bool_or_none(mr.get("has_conflicts")),
        blocking_discussions_resolved=_bool_or_none(mr.get("blocking_discussions_resolved")),
        approved=_bool_or_none(approvals.get("approved")) if approvals else None,
        approvals_required=_int_or_none(approvals.get("approvals_required")),
        approvals_left=_int_or_none(approvals.get("approvals_left")),
        approved_by=_approver_usernames(approvals),
        total_threads=total_threads,
        unresolved_threads=unresolved_threads,
        notes=notes,
        notes_truncated=notes_truncated,
        warnings=warnings,
    )


async def create_gitlab_merge_request(
    payload: CreateMergeRequestInput,
) -> CreateMergeRequestOutput:
    """Create a GitLab merge request in the configured context.

    Use when:
      - You have already pushed the source branch to GitLab.
      - You know the target branch (defaults to 'main').
      - You can produce a meaningful title and description.

    Do not use when:
      - You need to update, approve, merge, or close an existing MR.
      - The source branch has not been pushed yet.
      - The user has not confirmed creation.

    Input example:
      {
        "context_url": "https://gitlab.example.com/group/project",
        "project_path": "group/project",
        "source_branch": "fix/sentry-42",
        "target_branch": "main",
        "title": "fix: handle missing payload field",
        "description": "Root cause, fix, and test plan.",
        "remove_source_branch": false,
        "confirm": false
      }

    Returns:
      A compact MR summary: context, iid, web_url, title, and dry_run. When
      confirm=false, no upstream call is made and iid/web_url are null.

    Side effects:
      Destructive and non-idempotent when confirm=true. A successful call
      creates a new GitLab MR visible to other users and may trigger GitLab
      notifications. Reversing it requires manually closing the MR.
    """

    context_url = str(payload.context_url)
    name, ctx = resolve_context(context_url)
    gitlab = _gitlab_service(name, ctx)

    if not payload.confirm:
        _logger.info(
            "create_merge_request_dry_run",
            context=name,
            project_path=payload.project_path,
            source_branch=payload.source_branch,
            target_branch=payload.target_branch,
        )
        return CreateMergeRequestOutput(
            context=name,
            iid=None,
            web_url=None,
            title=payload.title,
            dry_run=True,
        )

    token = await async_keychain_get(gitlab.token_keychain)

    _logger.info(
        "create_merge_request",
        context=name,
        project_path=payload.project_path,
        source_branch=payload.source_branch,
        target_branch=payload.target_branch,
    )

    mr = await create_merge_request(
        gitlab.base_url,
        token,
        payload.project_path,
        payload.source_branch,
        payload.target_branch,
        payload.title,
        payload.description,
        payload.remove_source_branch,
    )

    return CreateMergeRequestOutput(
        context=name,
        iid=mr["iid"],
        web_url=mr["web_url"],
        title=mr["title"],
        dry_run=False,
    )


def _job_summary(job: dict[str, Any]) -> GitLabJobSummary:
    return GitLabJobSummary(
        id=int(job["id"]),
        name=str(job["name"]),
        status=str(job["status"]),
        stage=str(job["stage"]) if job.get("stage") is not None else None,
        web_url=job.get("web_url") if isinstance(job.get("web_url"), str) else None,
    )


def _mr_summary(mr: dict[str, Any]) -> MergeRequestSummary:
    author = mr.get("author") if isinstance(mr.get("author"), dict) else {}
    author_username = author.get("username") if isinstance(author, dict) else None
    return MergeRequestSummary(
        iid=int(mr["iid"]),
        title=str(mr["title"]),
        state=str(mr["state"]),
        draft=bool(mr["draft"]) if mr.get("draft") is not None else None,
        author_username=str(author_username) if author_username else None,
        source_branch=str(mr["source_branch"]) if mr.get("source_branch") is not None else None,
        target_branch=str(mr["target_branch"]) if mr.get("target_branch") is not None else None,
        web_url=mr.get("web_url") if isinstance(mr.get("web_url"), str) else None,
        updated_at=str(mr["updated_at"]) if mr.get("updated_at") is not None else None,
    )


def _str_or_none(value: object) -> str | None:
    return str(value) if isinstance(value, str) else None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _approver_usernames(approvals: dict[str, Any]) -> list[str]:
    approved_by = approvals.get("approved_by")
    if not isinstance(approved_by, list):
        return []
    usernames: list[str] = []
    for entry in approved_by:
        user = entry.get("user") if isinstance(entry, dict) else None
        username = user.get("username") if isinstance(user, dict) else None
        if isinstance(username, str):
            usernames.append(username)
    return usernames


def _summarize_discussions(
    discussions: list[dict[str, Any]],
) -> tuple[int, int, list[MergeRequestNote]]:
    """Return (total_threads, unresolved_threads, ordered non-system notes)."""

    total_threads = 0
    unresolved_threads = 0
    notes: list[MergeRequestNote] = []
    for discussion in discussions:
        raw_notes = discussion.get("notes")
        if not isinstance(raw_notes, list):
            continue
        human_notes = [n for n in raw_notes if isinstance(n, dict) and not n.get("system")]
        if not human_notes:
            continue
        total_threads += 1
        if any(n.get("resolvable") and not n.get("resolved") for n in human_notes):
            unresolved_threads += 1
        for note in human_notes:
            author = note.get("author")
            username = author.get("username") if isinstance(author, dict) else None
            notes.append(
                MergeRequestNote(
                    id=int(note["id"]),
                    author_username=_str_or_none(username),
                    body=str(note.get("body") or ""),
                    resolvable=bool(note.get("resolvable")),
                    resolved=bool(note.get("resolved")),
                    created_at=_str_or_none(note.get("created_at")),
                )
            )
    return total_threads, unresolved_threads, notes


def _mr_file_diff(change: dict[str, Any], max_lines: int) -> MergeRequestFileDiff:
    raw_diff = change.get("diff")
    diff_text = raw_diff if isinstance(raw_diff, str) else ""
    lines = diff_text.splitlines()
    selected = lines[-max_lines:] if max_lines < len(lines) else lines
    return MergeRequestFileDiff(
        old_path=str(change["old_path"]) if change.get("old_path") is not None else None,
        new_path=str(change["new_path"]) if change.get("new_path") is not None else None,
        new_file=bool(change.get("new_file", False)),
        renamed_file=bool(change.get("renamed_file", False)),
        deleted_file=bool(change.get("deleted_file", False)),
        diff="\n".join(selected),
        original_lines=len(lines),
        returned_lines=len(selected),
        truncated=len(lines) > len(selected),
    )


def _commit_title(commit: dict[str, Any]) -> str:
    title = commit.get("title") or commit.get("message") or commit.get("id")
    return str(title).splitlines()[0]


def _job_diagnosis(job: dict[str, Any], trace: str, tail: int) -> FailedJobDiagnosis:
    lines = trace.splitlines()
    selected = lines[-tail:]
    trace_tail = "\n".join(selected)
    failure_kind, hints = _classify_failure(job, trace_tail)
    return FailedJobDiagnosis(
        job=_job_summary(job),
        failure_kind=failure_kind,
        trace_tail=trace_tail,
        returned_lines=len(selected),
        truncated=len(lines) > len(selected),
        hints=hints,
    )


def _classify_failure(job: dict[str, Any], trace_tail: str) -> tuple[FailureKind, list[str]]:
    haystack = " ".join(
        [
            str(job.get("name") or ""),
            str(job.get("stage") or ""),
            trace_tail,
        ]
    ).lower()

    rules: list[tuple[FailureKind, tuple[str, ...], str]] = [
        (
            "infra",
            (
                "runner system failure",
                "execution took longer than",
                "connection reset",
                "connection refused",
                "network is unreachable",
                "no space left on device",
                "502 bad gateway",
                "503 service unavailable",
            ),
            "Looks like infrastructure/runner/network failure rather than code.",
        ),
        (
            "dependency",
            (
                "could not find a version",
                "no matching distribution found",
                "modulenotfounderror",
                "importerror",
                "npm err!",
                "dependency",
                "lock file",
                "resolution impossible",
            ),
            "Looks related to dependency resolution, missing packages, or lock files.",
        ),
        (
            "lint",
            (
                "ruff",
                "flake8",
                "eslint",
                "mypy",
                "format",
                "lint",
                "would reformat",
                "black",
            ),
            "Looks like lint, formatting, or static analysis failure.",
        ),
        (
            "test",
            (
                "pytest",
                "assertionerror",
                "failed tests",
                "failed,",
                "error at setup",
                "test failed",
                "unittest",
            ),
            "Looks like automated test failure.",
        ),
        (
            "build",
            (
                "docker build",
                "build failed",
                "compilation failed",
                "compiler",
                "webpack",
                "vite",
                "collectstatic",
            ),
            "Looks like build or compilation failure.",
        ),
    ]

    for failure_kind, needles, hint in rules:
        if any(needle in haystack for needle in needles):
            return failure_kind, [hint]

    return "unknown", ["No known failure pattern matched the available log tail."]


def _dominant_failure_kind(diagnoses: list[FailedJobDiagnosis]) -> FailureKind:
    if not diagnoses:
        return "unknown"

    counts: dict[FailureKind, int] = {}
    for diagnosis in diagnoses:
        counts[diagnosis.failure_kind] = counts.get(diagnosis.failure_kind, 0) + 1

    priority: list[FailureKind] = ["infra", "dependency", "lint", "test", "build", "unknown"]
    return max(priority, key=lambda kind: (counts.get(kind, 0), -priority.index(kind)))


def _diagnosis_summary(
    *,
    pipeline_status: str,
    failed_jobs_count: int,
    likely_failure_kind: FailureKind,
) -> str:
    if failed_jobs_count == 0:
        return f"Pipeline is {pipeline_status}; no failed jobs were found."
    return (
        f"Pipeline is {pipeline_status} with {failed_jobs_count} failed job(s). "
        f"The dominant failure kind appears to be {likely_failure_kind}."
    )


def _next_steps(failure_kind: FailureKind) -> list[str]:
    steps_by_kind: dict[FailureKind, list[str]] = {
        "lint": [
            "Run the same lint/static-analysis command locally.",
            "Fix formatting or type errors before retrying the pipeline.",
        ],
        "test": [
            "Run the failing test target locally with verbose output.",
            "Inspect recent changes touching the failing assertion or fixture.",
        ],
        "build": [
            "Reproduce the build command locally or in the same container image.",
            "Check compiler/build-tool errors near the end of the log.",
        ],
        "dependency": [
            "Check dependency declarations and lock files.",
            "Verify package indexes, credentials, and compatible version constraints.",
        ],
        "infra": [
            "Retry the failed job before changing code.",
            "Check runner health, network access, disk space, and GitLab incidents.",
        ],
        "unknown": [
            "Inspect each returned log tail manually.",
            "Fetch a larger tail or the full job log if the failure is above the returned window.",
        ],
    }
    return steps_by_kind[failure_kind]
