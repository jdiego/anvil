from __future__ import annotations

import httpx
import pytest
import respx

from anvil.exceptions import UpstreamHTTPError
from anvil.http import request_json


@pytest.mark.asyncio
@respx.mock
async def test_request_json_retries_on_5xx_and_succeeds() -> None:
    route = respx.get("https://example.test/api").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as client:
        result = await request_json(client, "GET", "https://example.test/api", service="test")

    assert result == {"ok": True}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_request_json_retries_429_with_retry_after() -> None:
    route = respx.get("https://example.test/api").mock(
        side_effect=[
            httpx.Response(429, text="slow down", headers={"Retry-After": "0"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as client:
        result = await request_json(client, "GET", "https://example.test/api", service="test")

    assert result == {"ok": True}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_request_json_maps_4xx_to_upstream_error() -> None:
    respx.get("https://example.test/api").mock(return_value=httpx.Response(404, text="nope"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(UpstreamHTTPError) as excinfo:
            await request_json(client, "GET", "https://example.test/api", service="test")

    assert excinfo.value.status_code == 404
    assert excinfo.value.service == "test"


@pytest.mark.asyncio
@respx.mock
async def test_request_json_204_returns_none() -> None:
    respx.get("https://example.test/api").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as client:
        result = await request_json(client, "GET", "https://example.test/api", service="test")
    assert result is None
