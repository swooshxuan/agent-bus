"""agent-bus command line interface."""

import argparse
import json
import os
import subprocess
import sys
import time

from .remote import RemoteStore
from .store import BusError, Store


def _body(args):
    if args.body is not None:
        return args.body
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def _log(msg):
    sys.stderr.write("[agent-bus] %s\n" % msg)
    sys.stderr.flush()


def _print_tasks(tasks):
    if not tasks:
        print("(no tasks)")
        return
    for task in tasks:
        print("%s  [%s]  %s  (from %s, %s)" % (
            task["id"], task.get("status", "?"), task.get("title", ""),
            task.get("sender", "?"), task.get("created_at", "?")))


def _run_claude(body, extra, workdir, timeout):
    argv = ["claude", "-p", body, "--output-format", "text"] + extra
    return subprocess.run(argv, cwd=workdir, capture_output=True,
                          text=True, timeout=timeout)


def _run_shell(body, extra, workdir, timeout):
    return subprocess.run(body, shell=True, cwd=workdir, capture_output=True,
                          text=True, timeout=timeout)


def cmd_send(store, args):
    task = store.send(args.target, args.title, _body(args), args.sender)
    print(json.dumps(task, ensure_ascii=False) if args.json else task["id"])
    return 0


def cmd_tasks(store, args):
    tasks = store.list_tasks(args.me, include_all=args.all)
    if args.json:
        print(json.dumps(tasks, ensure_ascii=False, indent=2))
    else:
        _print_tasks(tasks)
    return 0


def cmd_claim(store, args):
    claimed = store.claim(args.me, args.id)
    if args.json:
        print(json.dumps({"id": args.id, "claimed": claimed}))
    else:
        print(("claimed " if claimed else "not claimable: ") + args.id)
    return 0 if claimed else 1


def cmd_requeue(store, args):
    task = store.requeue(args.me, args.id)
    if args.json:
        print(json.dumps(task, ensure_ascii=False))
    else:
        print("requeued " + task["id"])
    return 0


def cmd_done(store, args):
    record = store.complete(args.me, args.id, args.status, _body(args))
    if args.json:
        print(json.dumps(record, ensure_ascii=False))
    else:
        print("done %s (%s)" % (record["id"], record["status"]))
    return 0


def cmd_show(store, args):
    print(json.dumps(store.get_task(args.id, args.target), ensure_ascii=False, indent=2))
    return 0


def cmd_result(store, args):
    print(json.dumps(store.get_result(args.id), ensure_ascii=False, indent=2))
    return 0


def cmd_list(store, args):
    stats = store.stats()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if not stats:
        print("(empty)")
        return 0
    for target, counts in stats.items():
        print("%-10s pending=%d running=%d done=%d failed=%d" % (
            target, counts["pending"], counts["running"],
            counts["done"], counts["failed"]))
    return 0


def cmd_work(store, args):
    workdir = os.path.abspath(os.path.expanduser(args.dir))
    os.makedirs(workdir, exist_ok=True)
    extra = list(args.extra or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    runner = _run_claude if args.runner == "claude" else _run_shell
    _log("worker up: me=%s dir=%s poll=%ss runner=%s" % (
        args.me, workdir, args.poll, args.runner))
    while True:
        for task in store.list_tasks(args.me):
            if not store.claim(args.me, task["id"]):
                continue
            _log("running %s: %s" % (task["id"], task.get("title", "")))
            try:
                body = store.get_task(task["id"]).get("body", "")
                proc = runner(body, extra, workdir, args.timeout)
                status = "ok" if proc.returncode == 0 else "fail"
                output = proc.stdout or ""
                if proc.stderr:
                    output += ("\n[stderr]\n" + proc.stderr) if output else ("[stderr]\n" + proc.stderr)
            except subprocess.TimeoutExpired:
                status, output = "fail", "timeout after %ss" % args.timeout
            except FileNotFoundError as exc:
                status, output = "fail", "runner not found: %s" % exc
            store.complete(args.me, task["id"], status, output)
            _log("finished %s -> %s" % (task["id"], status))
            if args.once:
                return 0
        if args.once:
            return 0
        time.sleep(args.poll)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="agent-bus",
        description="跨机 agent 任务信箱：SSH 为传输，文件为存储。")
    parser.add_argument("--base", default=None,
                        help="信箱根目录（默认 $AGENT_BUS_DIR 或 ~/.agent-bus）")
    parser.add_argument("--remote", default=os.environ.get("AGENT_BUS_REMOTE"),
                        help="远程信箱主机 user@host（默认 $AGENT_BUS_REMOTE）")
    parser.add_argument("--remote-key", default=None,
                        help="远程 SSH 私钥（默认 $AGENT_BUS_SSH_KEY）")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True

    p = sub.add_parser("send", help="投递任务")
    p.add_argument("target")
    p.add_argument("title")
    p.add_argument("--from", dest="sender", default=None)
    p.add_argument("--body", default=None, help="任务内容（缺省从 stdin 读）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("tasks", help="列出某台机器的待办")
    p.add_argument("me")
    p.add_argument("--all", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_tasks)

    p = sub.add_parser("claim", help="认领任务")
    p.add_argument("me")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("requeue", help="把卡住的任务重置为待办")
    p.add_argument("me")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_requeue)

    p = sub.add_parser("done", help="提交结果（缺省从 stdin 读）")
    p.add_argument("me")
    p.add_argument("id")
    p.add_argument("--status", choices=["ok", "fail"], default="ok")
    p.add_argument("--body", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_done)

    p = sub.add_parser("show", help="查看任务详情")
    p.add_argument("id")
    p.add_argument("--target", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("result", help="查看结果")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_result)

    p = sub.add_parser("list", help="总览")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("work", help="作为 worker 循环执行任务")
    p.add_argument("--me", required=True, help="本机在信箱里的名字")
    p.add_argument("--dir", default=".", help="runner 的工作目录")
    p.add_argument("--poll", type=int, default=20, help="轮询间隔（秒）")
    p.add_argument("--timeout", type=int, default=3600, help="单任务超时（秒）")
    p.add_argument("--runner", choices=["claude", "shell"], default="claude",
                   help="claude: claude -p <body>；shell: 把 body 当 shell 命令")
    p.add_argument("--once", action="store_true", help="最多处理一个任务后退出")
    p.add_argument("extra", nargs=argparse.REMAINDER,
                   help="追加给 runner 的参数（放在 -- 之后）")
    p.set_defaults(func=cmd_work)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    store = RemoteStore(args.remote, base=args.base, key=args.remote_key) \
        if args.remote else Store(args.base)
    try:
        return args.func(store, args) or 0
    except BusError as exc:
        sys.stderr.write("agent-bus: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
