import json
import shutil
import sysconfig
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class ProfileAPI(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/v1/users/profile" or self.headers.get("secretkey") != "fixture":
            self.send_error(403)
            return
        body = json.dumps({"res": {"id": 7, "username": "river", "circleID": 2}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class StdioTest(unittest.IsolatedAsyncioTestCase):
    async def test_installed_command_discovers_tools_and_reads_the_configured_profile(self):
        command = shutil.which("donetick-mcp", path=sysconfig.get_path("scripts"))
        self.assertIsNotNone(command, "Install the project before testing its console script")
        with HTTPServer(("127.0.0.1", 0), ProfileAPI) as api, tempfile.TemporaryDirectory() as tmp:
            thread = Thread(target=api.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            try:
                token = Path(tmp) / "token"
                token.write_text("fixture\n", encoding="utf-8")
                params = StdioServerParameters(
                    command=command,
                    env={
                        "DONETICK_TOKEN_FILE": str(token),
                        "DONETICK_BASE_URL": f"http://127.0.0.1:{api.server_port}",
                        "DONETICK_EXPECTED_USERNAME": "river",
                        "DONETICK_TIMEZONE": "Asia/Tokyo",
                        "DONETICK_CONNECTION_NAME": "Test account",
                    },
                )
                async with (
                    stdio_client(params) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    info = await session.initialize()
                    self.assertEqual(info.server_info.name, "Test account")
                    self.assertEqual(len((await session.list_tools()).tools), 13)
                    reply = await session.call_tool("whoami", {})
                    self.assertFalse(reply.is_error)
                    data = reply.structured_content or json.loads(reply.content[0].text)
                    self.assertEqual(
                        data,
                        {
                            "actor": {"id": 7, "username": "river", "circleId": 2},
                            "timezone": "Asia/Tokyo",
                        },
                    )
            finally:
                api.shutdown()
                thread.join()
