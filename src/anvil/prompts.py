from __future__ import annotations


def fix_sentry_issue(
    sentry_issue_url: str,
    project_path: str,
    branch_name: str,
    base_ref: str = "main",
) -> str:
    """Build a prompt to implement a fix for a Sentry issue in a GitLab project."""

    return f"""Implement a fix for a Sentry issue in the local repository.

Workflow:
1. Call get_sentry_issue with "{sentry_issue_url}" to fetch the issue and latest event.
2. Identify the failing exception, culprit, and the most relevant stack frames.
3. Map those frames to files and functions in the local repository.
4. In the target checkout, create or switch to branch {branch_name} (base: {base_ref}).
5. Find the smallest code change that addresses the root cause.
6. Add or update tests that reproduce the failure.
7. Run focused tests and lint/type checks for the touched code.
8. Commit locally and push the branch.
9. Call create_gitlab_merge_request with confirm=false first, then ask for user confirmation.

GitLab target:
- project: {project_path}
- base ref: {base_ref}
- branch: {branch_name}

Constraints:
- Do not paste the full latest_event payload back to the user.
- Ignore noisy framework frames unless they affect the root cause.
- Do not create the merge request until the user explicitly confirms.
- If either URL host does not match a configured context, ask the user before proceeding.

MR draft guidance:
- Title: fix: <short description matching culprit>
- Description: root cause, fix summary, Sentry issue URL, and test plan.
"""


def review_sentry_issue(
    issue_url: str,
) -> str:
    """Build a review prompt for investigating and fixing a Sentry issue."""

    return f"""Review this Sentry issue and propose an implementation plan.

Issue URL:
{issue_url}

Workflow:
1. Call get_sentry_issue with the issue URL above.
2. Identify the failing exception, culprit, release/environment hints, request context,
   and the most relevant stack frames from the latest event.
3. Map those frames to likely files and functions in the local repository.
4. Propose the smallest fix that addresses the root cause.
5. Include tests or verification steps that would catch the regression.
6. If a merge request is needed, prepare a concise MR title, description, and test plan.

Constraints:
- Do not paste the full latest_event payload back to the user.
- Ignore noisy framework frames unless they affect the root cause.
- Do not create a GitLab merge request until the user explicitly confirms.
- If the Sentry URL host does not match a configured context, ask the user which
  environment should be configured instead of guessing.

Expected answer:
- Summary of the failure.
- Probable root cause.
- Files/functions to inspect.
- Proposed fix.
- Verification plan.
- Optional MR draft if the user asks for one.
"""


def debug_pipeline(
    context_url: str,
    project_path: str,
    pipeline_id: int,
) -> str:
    """Build a prompt to diagnose and resolve a failed CI pipeline."""

    return f"""Diagnose and resolve a failed CI pipeline.

Pipeline:
- context URL: {context_url}
- project: {project_path}
- pipeline id: {pipeline_id}

Workflow:
1. Determine the platform from the context URL host using resolve_sentry_context or
   resolve_github_context to match the configured context.
2. For GitLab: call diagnose_gitlab_pipeline_failure to get a structured failure report
   including job log tails and a likely failure kind.
   For GitHub: call get_github_workflow_run_status to get job statuses, then
   get_github_actions_job_log for each failed job.
3. Classify the failure: lint, test, build, dependency, infra, or unknown.
4. If the failure is transient (infra/flaky): propose retry using retry_gitlab_failed_jobs
   or ask the user to re-run the GitHub workflow, with confirm=false first.
5. If the failure is deterministic: identify the root cause in the log tail, map it to
   source files, and propose the minimal code or config change needed.
6. Do not retry or cancel the pipeline without user confirmation.

Expected answer:
- Failure classification and confidence.
- Root cause (log excerpt, file, and line if identifiable).
- Recommended action: retry, code fix, or config fix.
- If a code fix: which files to change and why.
"""


def review_merge_request(
    context_url: str,
    project_path: str,
    mr_or_pr_id: int,
) -> str:
    """Build a prompt to review a merge request or pull request."""

    return f"""Review a merge request or pull request and provide actionable feedback.

Target:
- context URL: {context_url}
- project: {project_path}
- MR/PR id: {mr_or_pr_id}

Workflow:
1. Determine the platform from the context URL host.
2. For GitLab: call get_gitlab_mr_diff to fetch metadata and per-file diffs.
   For GitHub: call get_github_pull_request_diff to fetch metadata and per-file patches.
3. Review each changed file for:
   - Correctness and logic errors.
   - Missing or insufficient test coverage.
   - Security issues (injection, secret exposure, unsafe defaults).
   - Readability and naming clarity.
   - Unnecessary complexity or scope creep.
4. Check the MR/PR description for a clear summary, test plan, and linked issue.

Constraints:
- Do not approve, comment, or request changes without user confirmation.
- Focus feedback on actionable issues, not style preferences.
- Flag security issues separately and with higher urgency.

Expected answer:
- Overall assessment: approve / request changes / needs discussion.
- Grouped feedback: correctness, tests, security, readability.
- Top 1-3 blocking issues if any.
- Optional inline comment drafts if the user asks.
"""


def investigate_production_error(
    sentry_issue_url: str,
) -> str:
    """Build a prompt for a full incident-scope production error investigation."""

    return f"""Investigate a production error at incident scope.

Sentry issue URL:
{sentry_issue_url}

Workflow:
1. Call get_sentry_issue with the URL above to fetch the issue and latest event.
2. Assess impact: level, status, first seen, last seen, times seen, affected users.
3. Identify the release and environment from the issue metadata.
4. Call get_sentry_release for the affected release to check deploy timing and commits.
5. Call list_sentry_issues filtered to the same project to find related concurrent errors.
6. If a GitLab pipeline is associated with the release: call get_gitlab_pipeline_status
   to check whether the deploy pipeline completed cleanly.
7. Summarise the blast radius: which users, environments, and services are affected.
8. Propose immediate triage actions (rollback, hotfix, silence) before a full code fix.

Constraints:
- Do not resolve or assign the issue without explicit user confirmation.
- Do not paste raw event payloads; summarise the relevant fields only.
- If the Sentry host does not match a configured context, ask the user before proceeding.

Expected answer:
- Incident summary: what broke, when, and how widely.
- Root cause hypothesis with supporting evidence.
- Immediate mitigation options with trade-offs.
- Next step: hotfix, rollback, or monitor.
"""


def prepare_release_summary(
    context_url: str,
    project_path: str,
    from_ref: str,
    to_ref: str,
) -> str:
    """Build a prompt to compile a release summary from refs and merged MRs."""

    return f"""Prepare a release summary between two refs.

Target:
- context URL: {context_url}
- project: {project_path}
- from ref: {from_ref}
- to ref: {to_ref}

Workflow:
1. Determine the platform from the context URL host.
2. For GitLab: call compare_gitlab_refs to get commit count and changed files between
   {from_ref} and {to_ref}. Then call list_gitlab_merge_requests filtered to merged MRs
   targeting the release branch.
   For GitHub: call compare_github_refs and list_github_pull_requests filtered to merged PRs.
3. If Sentry is configured in the same context: call get_sentry_release for {to_ref} to
   include deploy metadata and any new issues introduced in this release.
4. Classify changes: features, fixes, refactors, dependency bumps, breaking changes.
5. Flag any MR/PR that lacks a description, linked issue, or test plan.

Expected answer:
- Release headline: version, date, change count.
- Categorised change list with MR/PR titles and authors.
- Breaking changes section (empty if none).
- Known issues or open Sentry errors introduced in this range.
- Suggested release notes draft.
"""


def create_hotfix_plan(
    sentry_issue_url: str,
    context_url: str,
    project_path: str,
    base_ref: str = "main",
) -> str:
    """Build a prompt to plan and initiate a hotfix for a production Sentry issue."""

    return f"""Plan and initiate a hotfix for a production Sentry issue.

Sentry issue URL:
{sentry_issue_url}

GitLab target:
- context URL: {context_url}
- project: {project_path}
- base ref: {base_ref}

Workflow:
1. Call get_sentry_issue with the Sentry URL to fetch the issue and latest event.
2. Identify the culprit, affected release, and the most relevant stack frames.
3. Call get_sentry_release for the affected release to find the deploy commit.
4. Call compare_gitlab_refs between the deploy commit and {base_ref} to understand
   how far the affected code is from the current tip.
5. Assess whether a rollback or a forward fix is safer given the diff size.
6. If a forward fix: propose branch name (hotfix/<short-id>), the minimal code change,
   and the test that would catch the regression.
7. Present the plan to the user before taking any action.
8. On confirmation: suggest calling open_fix_mr_from_sentry or create_gitlab_merge_request
   with confirm=false so the user reviews before the branch or MR is created.

Constraints:
- Do not create branches, commit, or open MRs without explicit user confirmation.
- Prefer the smallest possible change; a hotfix is not the time for refactoring.
- If the Sentry or GitLab host does not match a configured context, ask before proceeding.

Expected answer:
- Hotfix vs rollback recommendation with rationale.
- If hotfix: affected files, proposed change, and verification steps.
- Branch name and MR draft title/description ready to copy.
"""
