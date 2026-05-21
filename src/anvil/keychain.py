from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess

from anvil.exceptions import SecretNotFoundError


def _run_secret_command(command: list[str], *, label: str) -> str:
    result = subprocess.run(  # noqa: S603
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise SecretNotFoundError(f"Secret not found using {label}")

    secret = result.stdout.strip()

    if not secret:
        raise SecretNotFoundError(f"Empty secret returned by {label}")

    return secret


def _env_name_from_service(service_name: str) -> str:
    normalized = service_name.upper()
    normalized = normalized.replace("/", "_").replace("-", "_").replace(".", "_")
    return normalized


def _get_from_env(service_name: str) -> str | None:
    env_name = _env_name_from_service(service_name)
    value = os.environ.get(env_name)

    if value:
        return value

    return None


def _get_from_macos_keychain(service_name: str) -> str:
    return _run_secret_command(
        [
            "security",
            "find-generic-password",
            "-a",
            os.environ["USER"],
            "-s",
            service_name,
            "-w",
        ],
        label="macOS Keychain",
    )


def _get_from_linux_secret_tool(service_name: str) -> str:
    return _run_secret_command(
        [
            "secret-tool",
            "lookup",
            "service",
            service_name,
            "account",
            os.environ["USER"],
        ],
        label="secret-tool",
    )


def _get_from_pass(service_name: str) -> str:
    return _run_secret_command(
        ["pass", "show", service_name],
        label="pass",
    )


def keychain_get(service_name: str) -> str:
    """Return a secret from the local platform secret store.

    Resolution order:
    1. Environment variable derived from the service name.
       Example: ``anvil/sentry/example`` -> ``ANVIL_SENTRY_EXAMPLE``.
    2. macOS Keychain, when running on Darwin.
    3. Linux Secret Service via ``secret-tool``, when available.
    4. ``pass``, when available.
    """

    env_value = _get_from_env(service_name)

    if env_value:
        return env_value

    system = platform.system().lower()

    if system == "darwin":
        return _get_from_macos_keychain(service_name)

    if system == "linux" and shutil.which("secret-tool"):
        return _get_from_linux_secret_tool(service_name)

    if shutil.which("pass"):
        return _get_from_pass(service_name)

    raise SecretNotFoundError(
        "No supported secret backend found. "
        "Use macOS Keychain, Linux secret-tool, pass, or an environment variable."
    )


async def async_keychain_get(service_name: str) -> str:
    """Async wrapper for secret lookup so MCP tools do not block the event loop."""

    return await asyncio.to_thread(keychain_get, service_name)
