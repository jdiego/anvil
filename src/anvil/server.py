from __future__ import annotations

from fastmcp import FastMCP

from anvil.doctor import doctor_report
from anvil.github.tools import (
    compare_github_refs,
    get_github_actions_job_log,
    get_github_pull_request_diff,
    get_github_workflow_run_status,
    list_github_pull_requests,
    resolve_github_context,
)
from anvil.gitlab.tools import (
    approve_gitlab_merge_request,
    cancel_gitlab_pipeline,
    compare_gitlab_refs,
    create_gitlab_merge_request,
    diagnose_gitlab_pipeline_failure,
    get_gitlab_job_log,
    get_gitlab_mr_diff,
    get_gitlab_pipeline_status,
    list_gitlab_merge_requests,
    post_gitlab_mr_comment,
    post_gitlab_mr_line_comment,
    retry_gitlab_failed_jobs,
    set_gitlab_mr_ready,
    trigger_gitlab_pipeline,
)
from anvil.logging import configure_logging, get_logger
from anvil.prompts import (
    create_hotfix_plan,
    debug_pipeline,
    fix_sentry_issue,
    investigate_production_error,
    prepare_release_summary,
    review_merge_request,
    review_sentry_issue,
)
from anvil.resources import list_contexts_resource
from anvil.sentry.tools import (
    assign_sentry_issue,
    get_sentry_issue,
    get_sentry_release,
    link_sentry_issue_to_mr,
    list_sentry_issues,
    resolve_sentry_context,
    resolve_sentry_issue,
)
from anvil.workflows import open_fix_mr_from_sentry


def build_server() -> FastMCP:
    configure_logging()
    _logger = get_logger(__name__)
    _logger.info("server_starting")

    mcp = FastMCP("anvil")

    mcp.tool(
        resolve_sentry_context,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    mcp.tool(
        get_sentry_issue,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    mcp.tool(
        list_sentry_issues,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    mcp.tool(
        get_sentry_release,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    for read_only_tool in (
        resolve_github_context,
        list_github_pull_requests,
        get_github_pull_request_diff,
        compare_github_refs,
        get_github_workflow_run_status,
        get_github_actions_job_log,
    ):
        mcp.tool(
            read_only_tool,
            annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
        )
    mcp.tool(
        create_gitlab_merge_request,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    mcp.tool(
        get_gitlab_pipeline_status,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    mcp.tool(
        get_gitlab_job_log,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    mcp.tool(
        diagnose_gitlab_pipeline_failure,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    mcp.tool(
        list_gitlab_merge_requests,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    mcp.tool(
        compare_gitlab_refs,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    mcp.tool(
        get_gitlab_mr_diff,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    for destructive_tool in (
        retry_gitlab_failed_jobs,
        cancel_gitlab_pipeline,
        post_gitlab_mr_comment,
        post_gitlab_mr_line_comment,
        approve_gitlab_merge_request,
        set_gitlab_mr_ready,
        trigger_gitlab_pipeline,
        assign_sentry_issue,
        resolve_sentry_issue,
        link_sentry_issue_to_mr,
        open_fix_mr_from_sentry,
    ):
        mcp.tool(
            destructive_tool,
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
    mcp.tool(
        doctor_report,
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )

    mcp.resource(
        "contexts://list",
        name="contexts-list",
        description="List configured anvil contexts and public upstream base URLs.",
        mime_type="application/json",
        annotations={"readOnlyHint": True},
    )(list_contexts_resource)

    mcp.prompt(
        "review-sentry-issue",
        description=(
            "Guide an agent through fetching, triaging, and proposing a fix for a "
            "Sentry issue using anvil tools."
        ),
    )(review_sentry_issue)

    mcp.prompt(
        "fix-sentry-issue",
        description=(
            "Guide an agent through implementing and opening a GitLab MR for a "
            "Sentry issue fix, from branch creation to merge request."
        ),
    )(fix_sentry_issue)

    mcp.prompt(
        "debug-pipeline",
        description=(
            "Diagnose a failed GitLab or GitHub Actions pipeline and recommend "
            "a retry or code fix."
        ),
    )(debug_pipeline)

    mcp.prompt(
        "review-merge-request",
        description=(
            "Review a GitLab MR or GitHub PR diff and provide structured, "
            "actionable feedback."
        ),
    )(review_merge_request)

    mcp.prompt(
        "investigate-production-error",
        description=(
            "Investigate a Sentry issue at incident scope: impact, release context, "
            "related errors, and immediate mitigation options."
        ),
    )(investigate_production_error)

    mcp.prompt(
        "prepare-release-summary",
        description=(
            "Compile a release summary from merged MRs/PRs, ref comparison, "
            "and Sentry release metadata."
        ),
    )(prepare_release_summary)

    mcp.prompt(
        "create-hotfix-plan",
        description=(
            "Plan a hotfix for a production Sentry issue: assess rollback vs forward fix, "
            "propose branch and minimal change, and guide MR creation."
        ),
    )(create_hotfix_plan)

    return mcp


def run_server() -> None:
    build_server().run()
