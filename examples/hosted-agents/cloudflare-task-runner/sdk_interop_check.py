"""A2A interop check for the reference task runner, with the official SDK clients.

Drives the agent through both official a2a-sdk JSON-RPC clients, which
parse responses strictly, so any drift from either wire format fails
loudly:

- A2A 1.0: ``JsonRpcTransport`` (``SendMessage`` …, ``A2A-Version: 1.0``)
- A2A 0.3: ``CompatJsonRpcTransport`` (``message/send`` …, no version
  header) — the SDK's own backward-compatibility client.

Each run covers AgentCard resolution, send (blocking and
return-immediately), streaming, GetTask, CancelTask, SubscribeToTask,
push-config CRUD and error mapping (plus ListTasks on 1.0; 0.3 has no
task-list method). Regression guard for a2aproject/A2A discussion #1826
(SendMessage -> MethodNotFound).

    pip install "a2a-sdk[http-server]>=1.2.2"
    python sdk_interop_check.py [base_url]   # default: live endpoint
"""

import asyncio
import sys
import uuid

import httpx
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.compat.v0_3.jsonrpc_transport import CompatJsonRpcTransport
from a2a.types import a2a_pb2 as p
from a2a.utils.errors import A2AError

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://tasks.a2a-testbed.com"
LOCAL = any(h in BASE for h in ("127.0.0.1", "localhost"))


def msg(text):
    return p.Message(message_id=str(uuid.uuid4()), role=p.ROLE_USER, parts=[p.Part(text=text)])


async def run(version, transport_cls, headers, card, check):
    print(f"--- A2A {version} ({transport_cls.__name__})")
    async with httpx.AsyncClient(timeout=30, headers=headers) as hc:
        # wrangler dev rewrites Host to the prod route; point at the local base instead
        url = BASE if LOCAL else card.supported_interfaces[0].url
        t = transport_cls(hc, card, url)

        resp = await t.send_message(p.SendMessageRequest(message=msg("count: 2 hello")))
        task = resp.task if resp.HasField("task") else None
        check(
            "send (blocking) returns completed task",
            task is not None and task.status.state == p.TASK_STATE_COMPLETED,
            f"artifacts={len(task.artifacts) if task else '-'}",
        )
        got = await t.get_task(p.GetTaskRequest(id=task.id))
        check("GetTask", got.id == task.id and len(got.artifacts) == 2)
        if version == "1.0":
            lst = await t.list_tasks(p.ListTasksRequest(page_size=5))
            check("ListTasks", len(lst.tasks) >= 1)
        try:
            await t.cancel_task(p.CancelTaskRequest(id=task.id))
            check("CancelTask on terminal -> TaskNotCancelable", False)
        except A2AError as e:
            check(
                "CancelTask on terminal -> TaskNotCancelable",
                "NotCancelable" in type(e).__name__,
                type(e).__name__,
            )
        try:
            await t.get_task(p.GetTaskRequest(id=str(uuid.uuid4())))
            check("GetTask unknown -> TaskNotFound", False)
        except A2AError as e:
            check(
                "GetTask unknown -> TaskNotFound", "NotFound" in type(e).__name__, type(e).__name__
            )

        cfg = await t.create_task_push_notification_config(
            p.TaskPushNotificationConfig(
                task_id=task.id,
                id="cfg1",
                url="https://example.invalid/hook",
                token="tok",
                authentication=p.AuthenticationInfo(scheme="Bearer", credentials="c"),
            )
        )
        check(
            "CreateTaskPushNotificationConfig",
            cfg.id == "cfg1" and cfg.task_id == task.id and cfg.authentication.scheme == "Bearer",
        )
        g = await t.get_task_push_notification_config(
            p.GetTaskPushNotificationConfigRequest(task_id=task.id, id="cfg1")
        )
        check("GetTaskPushNotificationConfig", g.url == "https://example.invalid/hook")
        listed = await t.list_task_push_notification_configs(
            p.ListTaskPushNotificationConfigsRequest(task_id=task.id)
        )
        check("ListTaskPushNotificationConfigs", len(listed.configs) == 1)
        await t.delete_task_push_notification_config(
            p.DeleteTaskPushNotificationConfigRequest(task_id=task.id, id="cfg1")
        )
        listed = await t.list_task_push_notification_configs(
            p.ListTaskPushNotificationConfigsRequest(task_id=task.id)
        )
        check("DeleteTaskPushNotificationConfig", len(listed.configs) == 0)

        kinds = []
        last = None
        async for ev in t.send_message_streaming(
            p.SendMessageRequest(message=msg("count: 3 stream"))
        ):
            kinds.append(ev.WhichOneof("payload"))
            last = ev
        check(
            "streaming send",
            kinds[0] == "task"
            and kinds.count("artifact_update") == 3
            and kinds[-1] == "status_update"
            and last.status_update.status.state == p.TASK_STATE_COMPLETED,
            str(kinds),
        )

        r = await t.send_message(
            p.SendMessageRequest(
                message=msg("count: 8 bg"),
                configuration=p.SendMessageConfiguration(return_immediately=True),
            )
        )
        check(
            "send (return immediately)",
            r.task.status.state in (p.TASK_STATE_SUBMITTED, p.TASK_STATE_WORKING),
        )
        sub = [
            ev.WhichOneof("payload")
            async for ev in t.subscribe(p.SubscribeToTaskRequest(id=r.task.id))
        ]
        check("SubscribeToTask", sub and sub[0] == "task" and sub[-1] == "status_update", str(sub))


async def main():
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name, extra)

    async with httpx.AsyncClient(timeout=30) as hc:
        card = await A2ACardResolver(hc, BASE).get_agent_card()
    check("card parses", card.name == "Task Runner")
    versions = {(i.protocol_binding, i.protocol_version) for i in card.supported_interfaces}
    check(
        "card advertises JSONRPC 1.0 (preferred) and 0.3",
        card.supported_interfaces[0].protocol_version == "1.0" and ("JSONRPC", "0.3") in versions,
    )

    # 1.0: the header ClientFactory sets on every request. 0.3: no header.
    await run("1.0", JsonRpcTransport, {"A2A-Version": "1.0"}, card, check)
    await run("0.3", CompatJsonRpcTransport, {}, card, check)

    print("ALL PASS" if ok else "SOME FAILED")
    return ok


sys.exit(0 if asyncio.run(main()) else 1)
