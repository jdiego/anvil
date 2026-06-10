---
name: create-hotfix-plan
description: Plan a production hotfix for a Sentry issue using Anvil MCP tools before any branch or merge request is created.
---

# Create Hotfix Plan

Plan and initiate a hotfix for a production Sentry issue.

Use the Sentry issue URL, target context URL, project, and base ref provided by the user or by the invocation parameters.

## Workflow

1. Call `get_sentry_issue` with the Sentry URL to fetch the issue and latest event.
2. Identify the culprit, affected release, and the most relevant stack frames.
3. Call `get_sentry_release` for the affected release to find the deploy commit.
4. Call `compare_gitlab_refs` or `compare_github_refs` between the deploy commit and the base ref to understand how far the affected code is from the current tip.
5. Assess whether a rollback or a forward fix is safer given the diff size.
6. If a forward fix is safer, propose a branch name, the minimal code change, and the test that would catch the regression.
7. Present the plan to the user before taking any action.
8. On confirmation, suggest the appropriate atomic MCP tools with `confirm=false` first so the user reviews before any branch or MR/PR is created.

## Constraints

- Do not create branches, commit, or open MRs/PRs without explicit user confirmation.
- Prefer the smallest possible change; a hotfix is not the time for refactoring.
- If the Sentry or source-control host does not match a configured context, ask before proceeding.

## Expected Answer

- Hotfix vs rollback recommendation with rationale.
- If hotfix: affected files, proposed change, and verification steps.
- Branch name and MR/PR draft title/description ready for review.
