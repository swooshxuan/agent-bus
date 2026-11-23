"""agent-bus command line interface."""

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time

from . import __version__
from .config import load_config
from .remote import RemoteStore
from .sandbox import Sandbox, SandboxError
from .signing import sign_task, verify_task
from .store import BusError, Store

# A task body may start with "@workdir: /path/to/project" to choose the
# directory the runner executes in (falls back to --dir).
_WORKDIR_RE = re.compile(r"^@workdir:\s*(.+?)\s*$")


def _split_workdir(body):
    """Return (workdir or None, body without the directive line)."""
    lines = body.splitlines()
    if lines:
        match = _WORKDIR_RE.match(lines[0].strip())
        if match:
            return match.group(1), "\n".join(lines[1:]).lstrip("\n")
    return None, body


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


def _state_dir():
    path = os.path.join(os.path.expanduser("~"), ".agent-bus", "worker")
    os.makedirs(path, exist_ok=True)
    return path


def _pid_path(me):
    return os.path.join(_state_dir(), me + ".pid")


def _default_log(me):
    return os.path.join(_state_dir(), me + ".log")


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %s" % pid, "/NH"],
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=10)
            return str(pid) in (out.stdout or "")
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _run_claude(body, extra, workdir, timeout, wrap=None):
    argv = ["claude", "-p", body, "--output-format", "text"] + extra
    if wrap is not None:
        argv = wrap(argv)
    return subprocess.run(argv, cwd=workdir, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def _run_shell(body, extra, workdir, timeout, wrap=None):
    if wrap is not None:
        argv = wrap(["bash", "-lc", body])
        return subprocess.run(argv, cwd=workdir, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    return subprocess.run(body, shell=True, cwd=workdir, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def cmd_send(store, args):
    body = _body(args)
    sender = args.sender or os.environ.get("USER", "unknown")
    sig = args.sig
    key = getattr(args, "signing_key", None)
    if key and not sig:
        sig = sign_task(key, args.target, args.title, body, sender)
    task = store.send(args.target, args.title, body, sender, sig=sig)
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


def _detach_worker(args):
    log_path = os.path.abspath(os.path.expanduser(args.log)) if args.log else _default_log(args.me)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    raw = [a for a in getattr(args, "_raw", []) if a != "--detach"]
    argv = [sys.executable, "-m", "agent_bus.cli"] + raw
    logf = open(log_path, "ab")
    kwargs = dict(stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, cwd=os.getcwd())
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **kwargs)
    finally:
        logf.close()
    state = {"pid": proc.pid, "me": args.me,
             "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
             "log": log_path, "mode": getattr(args, "_mode", "unknown")}
    with open(_pid_path(args.me), "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    print("worker started in background: me=%s pid=%d" % (args.me, proc.pid))
    print("log:    %s" % log_path)
    print("status: agent-bus status --me %s" % args.me)
    print("stop:   agent-bus stop --me %s" % args.me)
    return 0


def _check_signature(args, task):
    key = getattr(args, "signing_key", None)
    if key:
        return verify_task(key, task)
    if getattr(args, "require_signature", False):
        return False, "no signing key configured"
    if task.get("sig"):
        _log("WARN: task %s has a signature but no key is configured"
             % task.get("id"))
    else:
        _log("WARN: task %s is unsigned (set signing_key to enable signing)"
             % task.get("id"))
    return True, "unverified"


def cmd_work(store, args):
    if args.detach:
        return _detach_worker(args)

    workdir = os.path.abspath(os.path.expanduser(args.dir))
    os.makedirs(workdir, exist_ok=True)
    extra = list(args.extra or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    runner = _run_claude if args.runner == "claude" else _run_shell
    _log("mode: %s" % getattr(args, "_mode", "unknown"))
    if getattr(args, "_config", None):
        _log("config: %s" % args._config)
    if not getattr(args, "_remote", False):
        _log("NOTE: 本地模式 —— 任务只读写本地信箱，不会发往远端（用 --remote 或 AGENT_BUS_REMOTE）")
    _log("worker up: me=%s dir=%s poll=%ss runner=%s" % (
        args.me, workdir, args.poll, args.runner))
    delay = 5
    while True:
        try:
            tasks = store.list_tasks(args.me)
        except BusError as exc:
            _log("bus error: %s — retry in %ss" % (exc, delay))
            time.sleep(delay)
            delay = min(delay * 2, 120)
            continue
        delay = 5
        for task in tasks:
            try:
                claimed = store.claim(args.me, task["id"])
            except BusError as exc:
                _log("claim failed %s: %s" % (task["id"], exc))
                continue
            if not claimed:
                continue
            _log("running %s: %s" % (task["id"], task.get("title", "")))
            sandbox = None
            status, output = "fail", ""
            try:
                detail = store.get_task(task["id"])
                sig_ok, sig_reason = _check_signature(args, detail)
                if not sig_ok:
                    output = "refused: %s" % sig_reason
                else:
                    body = detail.get("body", "")
                    task_dir, body = _split_workdir(body)
                    task_dir = os.path.expanduser(task_dir) if task_dir else workdir
                    if not os.path.isdir(task_dir):
                        output = "workdir not found: %s" % task_dir
                    else:
                        sandbox = Sandbox(args.sandbox, task_dir, task["id"],
                                          log=_log, keep=args.keep_worktrees,
                                          image=args.docker_image,
                                          network=args.docker_network)
                        _log("sandbox: %s (dir: %s)" % (sandbox.mode, sandbox.run_dir))
                        wrap = sandbox.wrap if sandbox.mode == "docker" else None
                        proc = runner(body, extra, sandbox.run_dir, args.timeout, wrap)
                        status = "ok" if proc.returncode == 0 else "fail"
                        output = proc.stdout or ""
                        if proc.stderr:
                            output += ("\n[stderr]\n" + proc.stderr) if output else ("[stderr]\n" + proc.stderr)
            except SandboxError as exc:
                output = "sandbox error: %s" % exc
            except subprocess.TimeoutExpired:
                status, output = "fail", "timeout after %ss" % args.timeout
            except FileNotFoundError as exc:
                status, output = "fail", "runner not found: %s" % exc
            finally:
                if sandbox is not None:
                    try:
                        info = sandbox.finish()
                    except Exception as exc:  # noqa: BLE001
                        info = {"mode": sandbox.mode, "cleanup_error": repr(exc)}
                    if info.get("diff_stat"):
                        output += "\n\n--- sandbox (worktree) ---\n" + info["diff_stat"]
                        if info.get("diff"):
                            output += "\n" + info["diff"]
                    _log("sandbox %s finished" % info.get("mode"))
            try:
                store.complete(args.me, task["id"], status, output)
            except BusError as exc:
                _log("submit failed %s: %s (left running — use 'agent-bus reap')"
                     % (task["id"], exc))
            else:
                _log("finished %s -> %s" % (task["id"], status))
            if args.once:
                return 0
        if args.once:
            return 0
        time.sleep(args.poll)


def cmd_doctor(store, args):
    failures = 0

    def check(tag, message, hint=None):
        print("[%-4s] %s" % (tag, message))
        if hint:
            print("       hint: %s" % hint)

    print("agent-bus doctor")
    print("-" * 56)
    check("PASS", "version %s" % __version__)
    if sys.version_info >= (3, 8):
        check("PASS", "python %s" % platform.python_version())
    else:
        failures += 1
        check("FAIL", "python %s is too old" % platform.python_version(), "need >= 3.8")
    check("INFO", "mode: %s" % getattr(args, "_mode", "unknown"))

    if getattr(args, "_remote", False):
        ssh = shutil.which("ssh")
        if ssh:
            check("PASS", "ssh client: %s" % ssh)
        else:
            failures += 1
            check("FAIL", "ssh client not found", "install OpenSSH client")
        key = args.remote_key or os.environ.get("AGENT_BUS_SSH_KEY")
        if key:
            key_path = os.path.expanduser(key)
            if os.path.exists(key_path):
                check("PASS", "ssh key: %s" % key_path)
            else:
                failures += 1
                check("FAIL", "ssh key not found: %s" % key_path,
                      "check --remote-key / AGENT_BUS_SSH_KEY")
        else:
            check("WARN", "no ssh key configured", "set --remote-key or AGENT_BUS_SSH_KEY")

    try:
        stats = store.stats()
        tasks = sum(sum(counts.values()) for counts in stats.values())
        check("PASS", "bus reachable (%d targets, %d tasks)" % (len(stats), tasks))
        if args.me:
            pending = len(store.list_tasks(args.me))
            check("PASS", "queue '%s': %d pending" % (args.me, pending))
    except BusError as exc:
        failures += 1
        check("FAIL", "bus unreachable: %s" % exc, "check network, key and --remote")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        check("FAIL", "bus error: %r" % exc)

    claude = shutil.which("claude")
    if claude:
        try:
            out = subprocess.run([claude, "--version"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=10)
            first = (out.stdout or "").strip().splitlines()
            check("PASS", "claude: %s" % (first[0] if first else claude))
        except Exception as exc:  # noqa: BLE001
            check("WARN", "claude found but --version failed: %r" % exc)
    else:
        check("WARN", "claude not found (needed only for --runner claude)")

    git = shutil.which("git")
    check("PASS" if git else "WARN", "git: %s" % (
        git or "not found (worktree sandbox disabled)"))
    docker = shutil.which("docker")
    check("PASS" if docker else "WARN", "docker: %s" % (
        docker or "not found (docker sandbox disabled)"))

    if args.dir:
        target = os.path.abspath(os.path.expanduser(args.dir))
        if os.path.isdir(target):
            if os.access(target, os.W_OK):
                check("PASS", "workdir: %s" % target)
            else:
                check("WARN", "workdir not writable: %s" % target)
        else:
            check("WARN", "workdir will be created: %s" % target)

    print("-" * 56)
    print("RESULT:", "OK" if failures == 0 else "FAILED")
    return 0 if failures == 0 else 1


def cmd_status(store, args):
    path = _pid_path(args.me)
    if not os.path.exists(path):
        print("worker '%s': not running (no pid file)" % args.me)
        return 1
    with open(path, encoding="utf-8") as fh:
        state = json.load(fh)
    alive = _pid_alive(state.get("pid"))
    print("worker '%s': %s (pid %s, started %s)" % (
        args.me, "RUNNING" if alive else "STOPPED",
        state.get("pid"), state.get("started_at")))
    if state.get("mode"):
        print("mode:", state["mode"])
    log = state.get("log")
    if log:
        print("log:", log)
        if os.path.exists(log):
            with open(log, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-5:]
            if lines:
                print("--- last log lines ---")
                print("".join(lines).rstrip())
    return 0 if alive else 1


def cmd_stop(store, args):
    path = _pid_path(args.me)
    if not os.path.exists(path):
        print("worker '%s': not running" % args.me)
        return 1
    with open(path, encoding="utf-8") as fh:
        state = json.load(fh)
    pid = state.get("pid")
    if _pid_alive(pid):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True)
        else:
            os.kill(int(pid), signal.SIGTERM)
        print("stopped worker '%s' (pid %s)" % (args.me, pid))
    else:
        print("worker '%s' was not running (stale pid file)" % args.me)
    try:
        os.unlink(path)
    except OSError:
        pass
    return 0


def cmd_prune(store, args):
    removed = store.prune(args.older_days * 86400, dry_run=args.dry_run)
    if args.json:
        print(json.dumps({"removed": removed}))
    else:
        verb = "would remove" if args.dry_run else "removed"
        print("%s %d task(s)%s" % (
            verb, len(removed),
            (": " + ", ".join(removed)) if removed else ""))
    return 0


def cmd_reap(store, args):
    ids = store.reap(args.me, args.older * 60)
    if args.json:
        print(json.dumps({"reaped": ids}))
    else:
        print("reaped %d task(s)%s" % (len(ids), (": " + ", ".join(ids)) if ids else ""))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="agent-bus",
        description="跨机 agent 任务信箱：SSH 为传输，文件为存储。")
    parser.add_argument("--config", default=None,
                        help="配置文件路径（默认 ./agent-bus.toml 或 "
                             "$AGENT_BUS_CONFIG）")
    parser.add_argument("--base", default=None,
                        help="信箱根目录（默认 $AGENT_BUS_DIR 或 ~/.agent-bus）")
    parser.add_argument("--remote", default=None,
                        help="远程信箱主机 user@host（默认 $AGENT_BUS_REMOTE 或配置）")
    parser.add_argument("--remote-key", default=None,
                        help="远程 SSH 私钥（默认 $AGENT_BUS_SSH_KEY 或配置）")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True

    p = sub.add_parser("send", help="投递任务")
    p.add_argument("target")
    p.add_argument("title")
    p.add_argument("--from", dest="sender", default=None)
    p.add_argument("--body", default=None, help="任务内容（缺省从 stdin 读）")
    p.add_argument("--sig", default=None, help="任务签名（内部使用）")
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
    p.add_argument("--me", default=None, help="本机在信箱里的名字（也可写在配置里）")
    p.add_argument("--dir", default=None, help="runner 的工作目录")
    p.add_argument("--poll", type=int, default=None, help="轮询间隔（秒，默认 20）")
    p.add_argument("--timeout", type=int, default=None, help="单任务超时（秒，默认 3600）")
    p.add_argument("--runner", choices=["claude", "shell"], default=None,
                   help="claude: claude -p <body>；shell: 把 body 当 shell 命令")
    p.add_argument("--sandbox", choices=["auto", "none", "worktree", "docker"],
                   default=None, help="任务沙箱（默认 auto）")
    p.add_argument("--require-signature", action="store_true",
                   help="拒绝未签名或签名无效的任务")
    p.add_argument("--keep-worktrees", action="store_true",
                   help="任务完成后保留 worktree")
    p.add_argument("--docker-image", default=None,
                   help="docker 沙箱镜像（默认 $AGENT_BUS_DOCKER_IMAGE 或 agent-bus-worker:latest）")
    p.add_argument("--docker-network", choices=["bridge", "none"], default=None)
    p.add_argument("--once", action="store_true", help="最多处理一个任务后退出")
    p.add_argument("--detach", action="store_true", help="后台运行（日志写入文件）")
    p.add_argument("--log", default=None, help="后台模式的日志路径")
    p.add_argument("extra", nargs=argparse.REMAINDER,
                   help="追加给 runner 的参数（放在 -- 之后）")
    p.set_defaults(func=cmd_work)

    p = sub.add_parser("doctor", help="环境自检")
    p.add_argument("--me", default=None, help="检查某个目标的队列")
    p.add_argument("--dir", default=None, help="检查作业目录")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("reap", help="回收超时未完成的任务")
    p.add_argument("me")
    p.add_argument("--older", type=int, default=60, help="超过多少分钟算超时（默认 60）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_reap)

    p = sub.add_parser("status", help="查看后台 worker 状态")
    p.add_argument("--me", default=None)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("stop", help="停止后台 worker")
    p.add_argument("--me", default=None)
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("prune", help="清理旧的已完成任务和结果")
    p.add_argument("--older-days", type=int, default=30,
                   help="保留最近多少天（默认 30）")
    p.add_argument("--dry-run", action="store_true", help="只显示将删除的内容")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_prune)

    return parser


def _force_utf8_stdio():
    """Avoid UnicodeEncodeError on legacy Windows code pages (cp1252/GBK)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def _apply_config(args, cfg):
    args.remote = args.remote or os.environ.get("AGENT_BUS_REMOTE") or cfg.get("remote")
    args.remote_key = (args.remote_key or os.environ.get("AGENT_BUS_SSH_KEY")
                       or cfg.get("remote_key"))
    args.base = args.base or os.environ.get("AGENT_BUS_DIR") or cfg.get("base")
    if args.base:
        args.base = os.path.expanduser(args.base)
    if args.remote_key:
        args.remote_key = os.path.expanduser(args.remote_key)

    args.signing_key = (os.environ.get("AGENT_BUS_SIGNING_KEY")
                        or cfg.get("signing_key"))
    args.require_signature = bool(getattr(args, "require_signature", False)
                                  or cfg.get("require_signature", False))

    cmd = args.cmd
    if cmd in ("work", "status", "stop", "doctor") and not getattr(args, "me", None):
        args.me = cfg.get("me")
    if cmd == "work":
        if not args.me:
            raise BusError("--me is required (or set 'me' in the config)")
        if args.require_signature and not args.signing_key:
            raise BusError("require_signature needs a signing key "
                           "(AGENT_BUS_SIGNING_KEY or 'signing_key' in the config)")
        args.dir = os.path.expanduser(args.dir or cfg.get("dir") or ".")
        args.poll = args.poll if args.poll is not None else int(cfg.get("poll", 20))
        args.timeout = args.timeout if args.timeout is not None else int(cfg.get("timeout", 3600))
        args.sandbox = args.sandbox or cfg.get("sandbox") or "auto"
        args.runner = args.runner or cfg.get("runner") or "claude"
        args.docker_network = args.docker_network or cfg.get("docker_network") or "bridge"
        args.docker_image = args.docker_image or cfg.get("docker_image")
    elif cmd in ("status", "stop"):
        if not args.me:
            raise BusError("--me is required (or set 'me' in the config)")
    elif cmd == "doctor" and not args.dir and cfg.get("dir"):
        args.dir = cfg["dir"]


def main(argv=None):
    _force_utf8_stdio()
    raw = list(sys.argv[1:]) if argv is None else list(argv)
    args = build_parser().parse_args(raw)
    try:
        cfg, cfg_path = load_config(args.config)
        _apply_config(args, cfg)
    except BusError as exc:
        sys.stderr.write("agent-bus: %s\n" % exc)
        return 1
    if args.remote:
        store = RemoteStore(args.remote, base=args.base, key=args.remote_key)
        mode = "REMOTE " + args.remote
        if args.remote_key:
            mode += " (key: %s)" % args.remote_key
    else:
        store = Store(args.base)
        mode = "LOCAL " + store.base
    args._raw = raw
    args._mode = mode
    args._remote = bool(args.remote)
    args._config = cfg_path
    try:
        return args.func(store, args) or 0
    except BusError as exc:
        sys.stderr.write("agent-bus: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
