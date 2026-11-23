"""Minimal MCP (Model Context Protocol) stdio server exposing the bus as tools.

Register with Claude Code::

    claude mcp add agent-bus -- agent-bus-mcp

No third-party dependencies: speaks newline-delimited JSON-RPC 2.0 over stdio.
"""

import json
import os
import sys

from . import __version__
from .remote import RemoteStore
from .store import BusError, Store

TOOLS = [
    {
        "name": "send_task",
        "description": "向目标机器投递一个任务（写入信箱）。返回任务 id。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "目标机器名，如 lab / laptop"},
                "title": {"type": "string", "description": "任务标题（一行）"},
                "body": {"type": "string", "description": "任务正文/提示词"},
                "sender": {"type": "string", "description": "发送方名字（可选）"},
            },
            "required": ["target", "title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "列出某台机器的待办任务。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "include_all": {"type": "boolean", "description": "包含已完成/失败"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "claim_task",
        "description": "原子认领一个任务。返回 claimed=true/false。",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}, "id": {"type": "string"}},
            "required": ["target", "id"],
        },
    },
    {
        "name": "complete_task",
        "description": "提交任务结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "id": {"type": "string"},
                "status": {"type": "string", "enum": ["ok", "fail"]},
                "result": {"type": "string"},
            },
            "required": ["target", "id"],
        },
    },
    {
        "name": "requeue_task",
        "description": "把卡在 running 的任务重置为 pending（崩溃恢复）。",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}, "id": {"type": "string"}},
            "required": ["target", "id"],
        },
    },
    {
        "name": "get_result",
        "description": "读取任务结果。",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "bus_stats",
        "description": "信箱总览（各目标机器各状态的任务数）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _text(payload):
    if not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": payload}]}


def _call_tool(store, name, args):
    if name == "send_task":
        return store.send(args["target"], args["title"],
                          args.get("body", ""), args.get("sender"))
    if name == "list_tasks":
        return store.list_tasks(args["target"], bool(args.get("include_all")))
    if name == "claim_task":
        return {"id": args["id"], "claimed": store.claim(args["target"], args["id"])}
    if name == "complete_task":
        return store.complete(args["target"], args["id"],
                              args.get("status", "ok"), args.get("result", ""))
    if name == "requeue_task":
        return store.requeue(args["target"], args["id"])
    if name == "get_result":
        return store.get_result(args["id"])
    if name == "bus_stats":
        return store.stats()
    raise BusError("unknown tool: %s" % name)


def _handle(store, req):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        version = params.get("protocolVersion") or "2024-11-05"
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "agent-bus", "version": __version__},
        }
    if method in ("notifications/initialized", "initialized",
                  "notifications/cancelled"):
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return _call_tool(store, params.get("name"), params.get("arguments") or {})
    raise BusError("method not found: %s" % method)


def _force_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def main(argv=None):
    _force_utf8_stdio()
    remote = os.environ.get("AGENT_BUS_REMOTE")
    store = RemoteStore(remote) if remote else Store()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid = req.get("id")
        try:
            result = _handle(store, req)
        except BusError as exc:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32000, "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001 - never crash the server loop
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32603, "message": repr(exc)}}
        else:
            if result is None:
                continue  # notification, no response
            if req.get("method") == "tools/call":
                result = _text(result)
            resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
