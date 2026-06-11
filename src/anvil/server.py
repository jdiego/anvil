from __future__ import annotations

from fastmcp import FastMCP

from anvil.doctor import doctor_report
from anvil.github.tools import (
    compare_github_refs,
    create_github_pull_request,
    get_github_actions_job_log,
    get_github_pull_request,
    get_github_pull_request_diff,
    get_github_workflow_run_status,
    list_github_pull_requests,
    resolve_github_context,
    update_github_pull_request,
)
from anvil.gitlab.tools import (
    approve_gitlab_merge_request,
    cancel_gitlab_pipeline,
    compare_gitlab_refs,
    create_gitlab_merge_request,
    diagnose_gitlab_pipeline_failure,
    get_gitlab_job_log,
    get_gitlab_merge_request,
    get_gitlab_mr_diff,
    get_gitlab_pipeline_status,
    list_gitlab_merge_requests,
    post_gitlab_mr_comment,
    post_gitlab_mr_line_comment,
    retry_gitlab_failed_jobs,
    set_gitlab_mr_ready,
    trigger_gitlab_pipeline,
    update_gitlab_merge_request,
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

    # Read-only tool that touches no upstream (pure local context resolution).
    mcp.tool(
        resolve_sentry_context,
        annotations={
            "title": "Resolve Sentry Context",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )

    # Read-only tools that call an upstream API. Title is required by the
    # Anthropic Directory review and drives the host's connector listing.
    read_only_tools = (
        (get_sentry_issue, "Get Sentry Issue"),
        (list_sentry_issues, "List Sentry Issues"),
        (get_sentry_release, "Get Sentry Release"),
        (resolve_github_context, "Resolve GitHub Context"),
        (list_github_pull_requests, "List GitHub Pull Requests"),
        (get_github_pull_request, "Get GitHub Pull Request"),
        (get_github_pull_request_diff, "Get GitHub Pull Request Diff"),
        (compare_github_refs, "Compare GitHub Refs"),
        (get_github_workflow_run_status, "Get GitHub Workflow Run Status"),
        (get_github_actions_job_log, "Get GitHub Actions Job Log"),
        (get_gitlab_pipeline_status, "Get GitLab Pipeline Status"),
        (get_gitlab_job_log, "Get GitLab Job Log"),
        (diagnose_gitlab_pipeline_failure, "Diagnose GitLab Pipeline Failure"),
        (list_gitlab_merge_requests, "List GitLab Merge Requests"),
        (get_gitlab_merge_request, "Get GitLab Merge Request"),
        (compare_gitlab_refs, "Compare GitLab Refs"),
        (get_gitlab_mr_diff, "Get GitLab Merge Request Diff"),
        (doctor_report, "Doctor Report"),
    )
    for read_only_tool, read_only_title in read_only_tools:
        mcp.tool(
            read_only_tool,
            annotations={
                "title": read_only_title,
                "readOnlyHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )

    # Destructive tools — mutate upstream state, gated behind a confirm flag.
    destructive_tools = (
        (create_github_pull_request, "Create GitHub Pull Request"),
        (update_github_pull_request, "Update GitHub Pull Request"),
        (create_gitlab_merge_request, "Create GitLab Merge Request"),
        (update_gitlab_merge_request, "Update GitLab Merge Request"),
        (retry_gitlab_failed_jobs, "Retry GitLab Failed Jobs"),
        (cancel_gitlab_pipeline, "Cancel GitLab Pipeline"),
        (post_gitlab_mr_comment, "Post GitLab MR Comment"),
        (post_gitlab_mr_line_comment, "Post GitLab MR Line Comment"),
        (approve_gitlab_merge_request, "Approve GitLab Merge Request"),
        (set_gitlab_mr_ready, "Set GitLab MR Ready"),
        (trigger_gitlab_pipeline, "Trigger GitLab Pipeline"),
        (assign_sentry_issue, "Assign Sentry Issue"),
        (resolve_sentry_issue, "Resolve Sentry Issue"),
        (link_sentry_issue_to_mr, "Link Sentry Issue to Merge Request"),
        (open_fix_mr_from_sentry, "Open Fix MR from Sentry Issue"),
    )
    for destructive_tool, destructive_title in destructive_tools:
        mcp.tool(
            destructive_tool,
            annotations={
                "title": destructive_title,
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
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
            "Diagnose a failed GitLab or GitHub Actions pipeline and recommend a retry or code fix."
        ),
    )(debug_pipeline)

    mcp.prompt(
        "review-merge-request",
        description=(
            "Review a GitLab MR or GitHub PR diff and provide structured, actionable feedback."
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
