from __future__ import annotations

from functools import cache
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def fix_sentry_issue(
    sentry_issue_url: str,
    project_path: str,
    branch_name: str,
    base_ref: str = "main",
) -> str:
    """Return the transitional MCP prompt backed by the fix-sentry-issue skill."""

    return _skill_prompt(
        "fix-sentry-issue",
        sentry_issue_url=sentry_issue_url,
        project_path=project_path,
        branch_name=branch_name,
        base_ref=base_ref,
    )


def review_sentry_issue(
    issue_url: str,
) -> str:
    """Return the transitional MCP prompt backed by the review-sentry-issue skill."""

    return _skill_prompt("review-sentry-issue", issue_url=issue_url)


def debug_pipeline(
    context_url: str,
    project_path: str,
    pipeline_id: int,
) -> str:
    """Return the transitional MCP prompt backed by the debug-pipeline skill."""

    return _skill_prompt(
        "debug-pipeline",
        context_url=context_url,
        project_path=project_path,
        pipeline_id=pipeline_id,
    )


def review_merge_request(
    context_url: str,
    project_path: str,
    mr_or_pr_id: int,
) -> str:
    """Return the transitional MCP prompt backed by the review-merge-request skill."""

    return _skill_prompt(
        "review-merge-request",
        context_url=context_url,
        project_path=project_path,
        mr_or_pr_id=mr_or_pr_id,
    )


def investigate_production_error(
    sentry_issue_url: str,
) -> str:
    """Return the transitional MCP prompt backed by the investigate-production-error skill."""

    return _skill_prompt("investigate-production-error", sentry_issue_url=sentry_issue_url)


def prepare_release_summary(
    context_url: str,
    project_path: str,
    from_ref: str,
    to_ref: str,
) -> str:
    """Return the transitional MCP prompt backed by the prepare-release-summary skill."""

    return _skill_prompt(
        "prepare-release-summary",
        context_url=context_url,
        project_path=project_path,
        from_ref=from_ref,
        to_ref=to_ref,
    )


def create_hotfix_plan(
    sentry_issue_url: str,
    context_url: str,
    project_path: str,
    base_ref: str = "main",
) -> str:
    """Return the transitional MCP prompt backed by the create-hotfix-plan skill."""

    return _skill_prompt(
        "create-hotfix-plan",
        sentry_issue_url=sentry_issue_url,
        context_url=context_url,
        project_path=project_path,
        base_ref=base_ref,
    )


def _skill_prompt(skill_name: str, **parameters: object) -> str:
    body = _skill_body(skill_name)
    if not parameters:
        return body

    lines = ["", "## Invocation Parameters"]
    lines.extend(f"- `{key}`: {value}" for key, value in parameters.items())
    return body.rstrip() + "\n" + "\n".join(lines) + "\n"


@cache
def _skill_body(skill_name: str) -> str:
    path = _SKILLS_DIR / skill_name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return text.strip()

    _, _, rest = text.partition("---\n")
    _, separator, body = rest.partition("---\n")
    if not separator:
        return text.strip()
    return body.strip()
