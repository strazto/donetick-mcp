"""Exercise a configured Donetick account over stdio with a temporary task and label."""

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from donetick_mcp.client import Donetick


async def check(command):
    client = Donetick.from_env()
    username = client.username
    params = StdioServerParameters(
        command=command[0],
        args=command[1:],
        env={k: v for k, v in os.environ.items() if k.startswith("DONETICK_")},
    )
    task_id = None
    label_id = None
    marker = "MCP verification " + uuid.uuid4().hex
    due = (
        (datetime.now(ZoneInfo(client.timezone)) + timedelta(days=1))
        .replace(hour=9, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    async with client.http as api:
        try:
            expected_actor = await client.identity()
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()

                async def call(tool_name, **arguments):
                    response = await session.call_tool(tool_name, arguments)
                    assert not response.is_error, (tool_name, response.content)
                    data = response.structured_content
                    if data is None:
                        data = json.loads(response.content[0].text)
                    assert data["actor"]["username"] == username
                    return data

                actor = (await call("whoami"))["actor"]
                if actor != expected_actor:
                    raise RuntimeError(
                        "The stdio connection and the API are using different accounts."
                    )
                members = (await call("list_members"))["result"]
                assert members
                result = await api.post("/api/v1/labels", json={"name": marker, "color": "#607d8b"})
                result.raise_for_status()
                label_id = result.json()["res"]["id"]
                assert any(x["id"] == label_id for x in (await call("list_labels"))["result"])
                created = await call(
                    "create_task",
                    name=marker,
                    details={
                        "description": "Temporary integration check",
                        "frequencyType": "daily",
                        "frequency": 1,
                        "isRolling": True,
                        "nextDueDate": due,
                        "frequencyMetadata": {"time": due},
                        "points": 7,
                    },
                )
                task_id = created["result"]
                assert (await call("list_tasks", query=marker))["total"] == 1

                async def current():
                    return (await call("get_task", task_id=task_id))["result"]

                task = await current()
                assert task["frequencyMetadata"]["timezone"] == client.timezone
                await call(
                    "assign_task",
                    task_id=task_id,
                    member_ids=[actor["id"]],
                    assigned_to=actor["id"],
                    expected_updated_at=task["updatedAt"],
                )
                task = await current()
                await call(
                    "set_task_labels",
                    task_id=task_id,
                    label_ids=[label_id],
                    expected_updated_at=task["updatedAt"],
                )
                task = await current()
                await call(
                    "edit_task",
                    task_id=task_id,
                    changes={"priority": 2},
                    expected_updated_at=task["updatedAt"],
                )
                edited = await current()
                for field in [
                    "frequencyMetadata",
                    "description",
                    "points",
                    "assignedTo",
                    "labelsV2",
                ]:
                    assert edited[field] == task[field], field
                stale = await session.call_tool(
                    "edit_task",
                    {
                        "task_id": task_id,
                        "changes": {"name": "should not change"},
                        "expected_updated_at": "stale",
                    },
                )
                assert stale.is_error
                await call("complete_task", task_id=task_id, notes="Temporary verification")
                history = (await call("task_history", task_id=task_id))["result"]
                assert history[0]["completedBy"] == actor["id"]
                await call("undo_task", task_id=task_id)
                await call("skip_task", task_id=task_id)
                await call("undo_task", task_id=task_id)
                print(
                    f"{username}: identity, search, create, edit, tags, assignment, completion attribution, skip and undo passed.",
                    flush=True,
                )
        finally:
            try:
                if task_id is not None:
                    result = await api.get(f"/api/v1/chores/{task_id}")
                    result.raise_for_status()
                    if result.json()["res"]["name"] != marker:
                        raise RuntimeError(
                            "The task no longer matches the test fixture. Leaving it in place."
                        )
                    result = await api.delete(f"/api/v1/chores/{task_id}")
                    result.raise_for_status()
            finally:
                if label_id is not None:
                    result = await api.delete(f"/api/v1/labels/{label_id}")
                    result.raise_for_status()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Optional stdio launcher after -- (default: donetick-mcp)",
    )
    args = parser.parse_args()
    if not args.apply:
        parser.error("--apply is required: creates then deletes temporary tasks and labels")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    await check(command or ["donetick-mcp"])


if __name__ == "__main__":
    asyncio.run(main())
