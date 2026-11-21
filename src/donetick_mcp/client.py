import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from mcp.server.mcpserver.exceptions import ToolError


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Expected an IANA time zone such as UTC or Europe/Paris.") from None
    return value


class Donetick:
    def __init__(
        self,
        base_url: str,
        token: str,
        username: str,
        *,
        timezone: str = "UTC",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        try:
            url = httpx.URL(base_url.strip())
        except httpx.InvalidURL:
            raise ValueError("Invalid DONETICK_BASE_URL.") from None
        if (
            url.scheme not in ("https", "http")
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "DONETICK_BASE_URL must be an HTTP(S) instance URL without credentials, query or fragment."
            )
        self.username = username.strip()
        if not self.username:
            raise ValueError(
                "Set DONETICK_EXPECTED_USERNAME to the token owner's Donetick username."
            )
        if not token.strip():
            raise ValueError("A nonempty Donetick personal API token is required.")
        self.timezone = validate_timezone(timezone)
        self.http = httpx.AsyncClient(
            base_url=url,
            headers={"secretkey": token.strip()},
            timeout=20,
            follow_redirects=False,
            transport=transport,
        )

    @classmethod
    def from_env(cls):
        token_file = os.environ.get("DONETICK_TOKEN_FILE")
        token = os.environ.get("DONETICK_TOKEN", "")
        if token_file and token:
            raise ValueError("Set only one of DONETICK_TOKEN_FILE and DONETICK_TOKEN.")
        if token_file:
            try:
                token = Path(token_file).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                raise ValueError("Could not read DONETICK_TOKEN_FILE as UTF-8.") from None
        if not token.strip():
            raise ValueError(
                "Supply a personal API token via DONETICK_TOKEN_FILE or DONETICK_TOKEN."
            )
        return cls(
            os.environ.get("DONETICK_BASE_URL", ""),
            token,
            os.environ.get("DONETICK_EXPECTED_USERNAME", ""),
            timezone=os.environ.get("DONETICK_TIMEZONE", "UTC"),
        )

    async def request(self, method, path, **kwargs):
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.RequestError:
            suffix = (
                " The write may have succeeded. Inspect the task history before retrying."
                if method != "GET"
                else ""
            )
            raise ToolError("Donetick request failed." + suffix) from None
        if not response.is_success:
            # Error bodies may contain private task data or request headers.
            message = f"Donetick returned HTTP {response.status_code}."
            if response.status_code in (401, 403):
                message += " Check token validity, permissions, and whether the task changed since you read it."
            if method != "GET" and response.status_code >= 500:
                message += (
                    " The write outcome is uncertain. Inspect the task history before retrying."
                )
            raise ToolError(message)
        if not response.content:
            return None
        body = response.json()
        return body.get("res", body) if isinstance(body, dict) else body

    async def identity(self):
        profile = await self.request("GET", "/api/v1/users/profile")
        if profile["username"] != self.username:
            raise ToolError("Token identity does not match this named connection. Refusing access.")
        return {
            "id": profile["id"],
            "username": profile["username"],
            "circleId": profile["circleID"],
        }

    async def result(self, method, path, **kwargs):
        actor = await self.identity()
        return {
            "actor": actor,
            "timezone": self.timezone,
            "result": await self.request(method, path, **kwargs),
        }
