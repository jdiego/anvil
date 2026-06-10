---
name: fix-sentry-issue
description: Implement a fix for a Sentry issue using Anvil MCP tools, local code changes, tests, and a GitLab merge request workflow.
---

# Fix Sentry Issue

Implement a fix for a Sentry issue in the local repository.

Use the Sentry issue URL, GitLab project, branch name, and base ref provided by the user or by the invocation parameters.

## Workflow

1. Call `get_sentry_issue` with the Sentry issue URL to fetch the issue and latest event.
2. Identify the failing exception, culprit, and the most relevant stack frames.
3. Map those frames to files and functions in the local repository.
4. In the target checkout, create or switch to the requested branch from the requested base ref.
5. Find the smallest code change that addresses the root cause.
6. Add or update tests that reproduce the failure.
7. Run focused tests and lint/type checks for the touched code.
8. Commit locally and push the branch.
9. Call `create_gitlab_merge_request` with `confirm=false` first, then ask for user confirmation.

## Constraints

- Do not paste the full `latest_event` payload back to the user.
- Ignore noisy framework frames unless they affect the root cause.
- Do not create the merge request until the user explicitly confirms.
- If either URL host does not match a configured context, ask the user before proceeding.

## MR Draft Guidance

- Title: `fix: <short description matching culprit>`
- Description: root cause, fix summary, Sentry issue URL, and test plan.
