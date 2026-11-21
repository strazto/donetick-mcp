import copy
import json
import os
import unittest
from unittest.mock import patch

import httpx
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from donetick_mcp.client import Donetick
from donetick_mcp.server import TaskChanges, edit_payload, make_server


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler, username="test-user", **kwargs):
        client = Donetick(
            "http://donetick:2021",
            "test-secret",
            username,
            transport=httpx.MockTransport(handler),
            **kwargs,
        )
        self.addAsyncCleanup(client.http.aclose)
        return client

    async def test_wrong_identity_blocks_write(self):
        requests = []

        def handler(req):
            requests.append(req)
            return httpx.Response(
                200, json={"res": {"id": 2, "username": "other-user", "circleID": 1}}
            )

        client = self.client(handler)
        with self.assertRaisesRegex(ToolError, "identity does not match"):
            await client.result("POST", "/api/v1/chores/1/do", json={})
        self.assertEqual([r.method for r in requests], ["GET"])

    async def test_uncertain_write_is_not_retried(self):
        requests = []

        def handler(req):
            requests.append(req)
            if req.method == "GET":
                return httpx.Response(
                    200, json={"res": {"id": 1, "username": "test-user", "circleID": 1}}
                )
            raise httpx.ReadTimeout("timeout", request=req)

        client = self.client(handler)
        with self.assertRaisesRegex(ToolError, "may have succeeded"):
            await client.result("POST", "/api/v1/chores/1/do", json={})
        self.assertEqual([r.method for r in requests], ["GET", "POST"])

    async def test_revoked_token_stops_before_write(self):
        requests = []

        def handler(req):
            requests.append(req)
            return httpx.Response(401, json={"error": "test-secret"})

        client = self.client(handler)
        with self.assertRaises(ToolError) as caught:
            await client.result("POST", "/api/v1/chores/", json={})
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertEqual(len(requests), 1)

    async def test_schema_excludes_admin_and_impersonation(self):
        server = make_server(self.client(lambda req: httpx.Response(500)), "test")
        tools = await server.list_tools()
        names = {t.name for t in tools}
        self.assertEqual(len(names), 13)
        self.assertNotIn("delete_task", names)
        for tool in tools:
            schema = tool.model_dump_json(by_alias=True)
            self.assertNotIn("completedBy", schema)
            self.assertNotIn("api_token", schema)
            self.assertEqual(
                tool.annotations.read_only_hint,
                tool.name
                in {
                    "whoami",
                    "list_members",
                    "list_labels",
                    "list_tasks",
                    "get_task",
                    "task_history",
                },
            )

    async def test_stale_edit_does_not_write(self):
        requests = []

        def handler(req):
            requests.append(req)
            data = (
                {"id": 1, "username": "test-user", "circleID": 1}
                if req.url.path.endswith("/profile")
                else {"updatedAt": "new"}
            )
            return httpx.Response(200, json={"res": data})

        server = make_server(self.client(handler), "test")
        with self.assertRaisesRegex(ToolError, "Task changed"):
            await server.call_tool(
                "edit_task",
                {"task_id": 1, "changes": {"name": "Updated"}, "expected_updated_at": "old"},
            )
        self.assertEqual([r.method for r in requests], ["GET", "GET"])

    def test_partial_edit_preserves_schedule_and_unrelated_fields(self):
        current = {
            "id": 1,
            "name": "Old",
            "frequencyType": "weekly",
            "frequency": 2,
            "frequencyMetadata": {"timezone": "Europe/Paris", "days": ["monday"]},
            "assignees": [{"userId": 2}],
            "notification": True,
            "points": 7,
            "subTasks": [{"id": 3, "name": "Keep"}],
            "projectId": 4,
            "description": "Keep",
            "updatedAt": "old",
            "labelsV2": [{"id": 5, "name": "Household"}],
        }
        original = copy.deepcopy(current)
        payload = edit_payload(current, {"name": "New"})
        self.assertEqual(current, original)
        for field in (
            "frequencyMetadata",
            "subTasks",
            "assignees",
            "notification",
            "points",
            "projectId",
            "description",
            "updatedAt",
        ):
            self.assertEqual(payload[field], current[field])
        self.assertEqual(payload["labelsV2"], [{"id": 5}])
        edited = edit_payload(current, {"frequencyMetadata": {"days": ["tuesday"]}})
        self.assertEqual(
            edited["frequencyMetadata"], {"timezone": "Europe/Paris", "days": ["tuesday"]}
        )
        monthly = edit_payload(
            current, {"frequencyType": "monthly", "frequencyMetadata": {"months": ["march"]}}
        )
        self.assertEqual(
            monthly["frequencyMetadata"], {"timezone": "Europe/Paris", "months": ["march"]}
        )

    async def test_create_uses_connection_timezone_unless_task_specifies_one(self):
        payloads = []

        def handler(request):
            if request.method == "GET":
                return httpx.Response(
                    200, json={"res": {"username": "test-user", "id": 3, "circleID": 1}}
                )
            payloads.append(json.loads(request.content))
            return httpx.Response(201, json={"res": 9})

        zone = "America/Toronto"
        server = make_server(self.client(handler, timezone=zone), "test")
        for metadata, expected in [
            (None, zone),
            ({"days": ["monday"]}, zone),
            ({"timezone": "Asia/Tokyo"}, "Asia/Tokyo"),
        ]:
            arguments = {"name": "Read"}
            if metadata is not None:
                arguments["details"] = {"frequencyMetadata": metadata}
            result = await server.call_tool("create_task", arguments)
            self.assertFalse(result.is_error)
            data = result.structured_content or json.loads(result.content[0].text)
            self.assertEqual(data["timezone"], zone)
            self.assertEqual(payloads[-1]["frequencyMetadata"]["timezone"], expected)
        with self.assertRaises(ValidationError):
            TaskChanges(frequencyMetadata={"timezone": "Invalid/Zone"})

    def test_token_environment_and_default_timezone(self):
        env = {
            "DONETICK_EXPECTED_USERNAME": "example",
            "DONETICK_BASE_URL": "https://example.test",
            "DONETICK_TOKEN": "fixture",
        }
        with patch.dict(os.environ, env, clear=True):
            client = Donetick.from_env()
            self.addAsyncCleanup(client.http.aclose)
            self.assertEqual(client.timezone, "UTC")
            self.assertEqual(client.http.headers["secretkey"], "fixture")
            os.environ["DONETICK_TOKEN_FILE"] = "/unused"
            with self.assertRaisesRegex(ValueError, "only one"):
                Donetick.from_env()

    def test_dates_require_offsets_including_dst_boundaries(self):
        for date in ["2026-10-04T03:30:00+11:00", "2026-04-05T02:30:00+10:00"]:
            self.assertIsNotNone(TaskChanges(nextDueDate=date).nextDueDate.utcoffset())
        with self.assertRaises(ValidationError):
            TaskChanges(nextDueDate="2026-10-04T02:30:00")
        with self.assertRaises(ValidationError):
            TaskChanges(completedBy=2)


if __name__ == "__main__":
    unittest.main()
