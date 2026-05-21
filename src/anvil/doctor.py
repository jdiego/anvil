from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from anvil.config import CONFIG_PATH, load_config
from anvil.contexts import Context, load_contexts
from anvil.exceptions import AnvilError
from anvil.github.client import get_current_user as github_get_current_user
from anvil.gitlab.client import get_current_user as gitlab_get_current_user
from anvil.keychain import async_keychain_get
from anvil.logging import get_logger
from anvil.sentry.client import get_authenticated as sentry_get_authenticated

_logger = get_logger(__name__)


class Status(StrEnum):
    OK = "ok"
    FAIL = "fail"


class Check(BaseModel):
    name: str
    status: Status
    detail: str = ""


class ContextReport(BaseModel):
    context: str
    checks: list[Check]


class DoctorReport(BaseModel):
    config_path: str = Field(description="Resolved path of the contexts file.")
    config_loaded: Status
    config_error: str | None = None
    contexts: list[ContextReport] = Field(default_factory=list)
    overall: Status

    def as_text(self) -> str:
        lines = [
            f"config: {self.config_path}",
            f"config_loaded: {self.config_loaded.value}",
        ]
        if self.config_error:
            lines.append(f"  error: {self.config_error}")
        for ctx_report in self.contexts:
            lines.append(f"\ncontext: {ctx_report.context}")
            for check in ctx_report.checks:
                marker = "✓" if check.status is Status.OK else "✗"
                detail = f" — {check.detail}" if check.detail else ""
                lines.append(f"  {marker} {check.name}{detail}")
        lines.append(f"\noverall: {self.overall.value}")
        return "\n".join(lines)


async def _check_secret(service_name: str) -> Check:
    try:
        await async_keychain_get(service_name)
    except AnvilError as exc:
        return Check(name=f"secret:{service_name}", status=Status.FAIL, detail=str(exc))
    return Check(name=f"secret:{service_name}", status=Status.OK)


async def _check_sentry(ctx: Context) -> Check:
    if ctx.sentry is None:
        return Check(name="sentry:auth", status=Status.OK, detail="not configured")

    try:
        token = await async_keychain_get(ctx.sentry.token_keychain)
        user = await sentry_get_authenticated(ctx.sentry.base_url, token)
    except AnvilError as exc:
        return Check(name="sentry:auth", status=Status.FAIL, detail=str(exc))
    except Exception as exc:
        return Check(name="sentry:auth", status=Status.FAIL, detail=f"unexpected: {exc!r}")

    user_label = _safe_label(user, fallback="authenticated")
    return Check(name="sentry:auth", status=Status.OK, detail=user_label)


async def _check_gitlab(ctx: Context) -> Check:
    if ctx.gitlab is None:
        return Check(name="gitlab:auth", status=Status.OK, detail="not configured")

    try:
        token = await async_keychain_get(ctx.gitlab.token_keychain)
        user = await gitlab_get_current_user(ctx.gitlab.base_url, token)
    except AnvilError as exc:
        return Check(name="gitlab:auth", status=Status.FAIL, detail=str(exc))
    except Exception as exc:
        return Check(name="gitlab:auth", status=Status.FAIL, detail=f"unexpected: {exc!r}")

    user_label = _safe_label(user, fallback="authenticated")
    return Check(name="gitlab:auth", status=Status.OK, detail=user_label)


async def _check_github(ctx: Context) -> Check:
    if ctx.github is None:
        return Check(name="github:auth", status=Status.OK, detail="not configured")

    try:
        token = await async_keychain_get(ctx.github.token_keychain)
        user = await github_get_current_user(ctx.github.base_url, token)
    except AnvilError as exc:
        return Check(name="github:auth", status=Status.FAIL, detail=str(exc))
    except Exception as exc:
        return Check(name="github:auth", status=Status.FAIL, detail=f"unexpected: {exc!r}")

    user_label = _safe_label(user, fallback="authenticated")
    return Check(name="github:auth", status=Status.OK, detail=user_label)


def _safe_label(payload: Any, *, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("username", "name", "email", "slug"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return fallback


async def _diagnose() -> DoctorReport:
    try:
        load_config()
    except AnvilError as exc:
        return DoctorReport(
            config_path=str(CONFIG_PATH),
            config_loaded=Status.FAIL,
            config_error=str(exc),
            overall=Status.FAIL,
        )

    try:
        contexts = load_contexts()
    except AnvilError as exc:
        return DoctorReport(
            config_path=str(CONFIG_PATH),
            config_loaded=Status.FAIL,
            config_error=str(exc),
            overall=Status.FAIL,
        )

    reports: list[ContextReport] = []
    overall = Status.OK

    for name, ctx in contexts.items():
        checks: list[Check] = []

        if ctx.sentry is not None:
            sentry_secret = await _check_secret(ctx.sentry.token_keychain)
            checks.append(sentry_secret)
            checks.append(
                await _check_sentry(ctx)
                if sentry_secret.status is Status.OK
                else await _noop_skipped("sentry:auth", "skipped — secret missing")
            )

        if ctx.gitlab is not None:
            gitlab_secret = await _check_secret(ctx.gitlab.token_keychain)
            checks.append(gitlab_secret)
            checks.append(
                await _check_gitlab(ctx)
                if gitlab_secret.status is Status.OK
                else await _noop_skipped("gitlab:auth", "skipped — secret missing")
            )

        if ctx.github is not None:
            github_secret = await _check_secret(ctx.github.token_keychain)
            checks.append(github_secret)
            checks.append(
                await _check_github(ctx)
                if github_secret.status is Status.OK
                else await _noop_skipped("github:auth", "skipped — secret missing")
            )

        if any(c.status is Status.FAIL for c in checks):
            overall = Status.FAIL

        reports.append(ContextReport(context=name, checks=checks))

    return DoctorReport(
        config_path=str(CONFIG_PATH),
        config_loaded=Status.OK,
        contexts=reports,
        overall=overall,
    )


async def _noop_skipped(name: str, detail: str) -> Check:
    return Check(name=name, status=Status.FAIL, detail=detail)


async def doctor_report() -> DoctorReport:
    """Diagnose the local anvil setup end-to-end.

    Use when:
      - A user reports that the MCP cannot reach Sentry or GitLab.
      - You need to verify local config, secret lookup, and upstream auth
        before using other tools.

    Do not use when:
      - You only need to resolve a URL to a configured context; use
        resolve_sentry_context or the contexts://list resource.

    Input example:
      {}

    Returns:
      A report with config status, per-context secret checks, upstream auth
      checks, and an overall ok/fail status.

    Side effects:
      Read-only. Retrieves local secrets and performs lightweight authenticated
      GET requests to Sentry /api/0/ and GitLab /api/v4/user.
    """

    report = await _diagnose()
    _logger.info("doctor_report", overall=report.overall.value)
    return report
