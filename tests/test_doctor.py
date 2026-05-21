from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response

from anvil.doctor import Status, doctor_report


@pytest.mark.asyncio
@respx.mock
async def test_doctor_all_ok(fake_contexts_yaml: Path, env_secrets: None) -> None:
    respx.get("https://sentry.example.com/api/0/").mock(
        return_value=Response(200, json={"username": "svc-example"})
    )
    respx.get("https://gitlab.example.com/api/v4/user").mock(
        return_value=Response(200, json={"username": "svc-example"})
    )

    report = await doctor_report()

    assert report.overall is Status.OK
    assert report.config_loaded is Status.OK
    assert len(report.contexts) == 1
    ctx = report.contexts[0]
    assert all(c.status is Status.OK for c in ctx.checks)


@pytest.mark.asyncio
@respx.mock
async def test_doctor_reports_gitlab_failure(
    fake_contexts_yaml: Path,
    env_secrets: None,
) -> None:
    respx.get("https://sentry.example.com/api/0/").mock(
        return_value=Response(200, json={"username": "svc-example"})
    )
    respx.get("https://gitlab.example.com/api/v4/user").mock(
        return_value=Response(401, text="bad token")
    )

    report = await doctor_report()

    assert report.overall is Status.FAIL
    gitlab_check = next(c for c in report.contexts[0].checks if c.name == "gitlab:auth")
    assert gitlab_check.status is Status.FAIL


@pytest.mark.asyncio
async def test_doctor_handles_missing_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("anvil.config.CONFIG_PATH", tmp_path / "missing.yaml")

    report = await doctor_report()

    assert report.config_loaded is Status.FAIL
    assert report.overall is Status.FAIL
    assert report.contexts == []
