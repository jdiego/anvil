---
name: debug-pipeline
description: Diagnose a failed GitLab or GitHub Actions pipeline using Anvil MCP tools and recommend retry, configuration, or code fixes.
---

# Debug Pipeline

Diagnose and resolve a failed CI pipeline.

Use the context URL, project/repository, and pipeline or workflow run id provided by the user or by the invocation parameters.

## Workflow

1. Determine the platform from the context URL host.
2. For GitLab: call `get_gitlab_pipeline_status`, then `get_gitlab_job_log` for failed jobs.
3. For GitHub: call `get_github_workflow_run_status`, then `get_github_actions_job_log` for failed jobs.
4. Classify the failure: lint, test, build, dependency, infra, or unknown.
5. If the failure is transient, propose a retry. For GitLab, use `retry_gitlab_failed_jobs` with `confirm=false` first. For GitHub, ask the user to re-run the workflow.
6. If the failure is deterministic, identify the root cause in the log tail, map it to source files, and propose the minimal code or config change needed.
7. Do not retry or cancel the pipeline without user confirmation.

## Expected Answer

- Failure classification and confidence.
- Root cause with a concise log excerpt, file, and line if identifiable.
- Recommended action: retry, code fix, or config fix.
- If a code fix is needed: which files to change and why.
