---
name: review-merge-request
description: Review a GitLab merge request or GitHub pull request using Anvil MCP diff tools and provide actionable feedback.
---

# Review Merge Request

Review a merge request or pull request and provide actionable feedback.

Use the context URL, project/repository, and MR/PR id provided by the user or by the invocation parameters.

## Workflow

1. Determine the platform from the context URL host.
2. For GitLab: call `get_gitlab_mr_diff` to fetch metadata and per-file diffs.
3. For GitHub: call `get_github_pull_request_diff` to fetch metadata and per-file patches.
4. Review each changed file for correctness, missing tests, security issues, readability, and unnecessary complexity.
5. Check the MR/PR description for a clear summary, test plan, and linked issue.

## Constraints

- Do not approve, comment, or request changes without user confirmation.
- Focus feedback on actionable issues, not style preferences.
- Flag security issues separately and with higher urgency.

## Expected Answer

- Overall assessment: approve, request changes, or needs discussion.
- Grouped feedback: correctness, tests, security, readability.
- Top one to three blocking issues if any.
- Optional inline comment drafts if the user asks.
