# agent-bus

[![CI](https://github.com/swooshxuan/agent-bus/actions/workflows/ci.yml/badge.svg)](https://github.com/swooshxuan/agent-bus/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](pyproject.toml)

> 给多台机器上的 AI agent 用的任务信箱：**SSH 为传输，文件为存储，人类可读**。
>
> A tiny, SSH-native, human-readable task mailbox for cross-machine AI agents.

不用装 NATS、不用 Kubernetes、不用开公网端口。两台在内网/NAT 后面的机器，
各放一把受限 SSH 公钥，就能互相派任务、收结果。

```
            ┌────────────── 信箱（files + SSH）──────────────┐
  laptop ──→│ tasks/laptop/   tasks/lab/   results/<id>.json │←── lab
  agent     └────────────────────────────────────────────────┘    agent
```

## 为什么

现有的多智能体编排方案大多假设：公网可达、有消息中间件、有容器编排。
但个人/实验室的常态是：笔记本在移动宽带 CGNAT 后面、服务器在校园网后面、
你想让它们上面的 Claude Code / Codex / 脚本协作一次。

agent-bus 做减法：

- **零依赖**：纯 Python 标准库，一个文件级队列
- **NAT 友好**：复用你已经有的 SSH（或 frp/ngrok 隧道）
- **人类可读**：任务是 JSON 文件，`ls` / `jq` / `git` 都能用
- **最小权限**：worker 的公钥被 `command=` 钉死，只能执行 `agent-bus`
- **agent 无关**：Claude Code、Codex、Aider、任意 CLI 都能当 worker

## 快速开始

### 1. 安装（在信箱主机和每台 worker 上）

```bash
pip install agent-bus          # 或 pip install -e .
agent-bus --help
```

### 2. 信箱主机：准备目录和受限入口

```bash
export AGENT_BUS_DIR=/srv/agent-bus      # 建议写进 ~/.bashrc
agent-bus list

# 把本机的 agent-bus-gate 写成受限命令（每台 worker 的公钥一行）
echo 'command="agent-bus-gate",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... lab-worker' \
  >> ~/.ssh/authorized_keys
```

> 也可以用 `--base` 参数指定目录，等价于 `AGENT_BUS_DIR`。

### 3. Worker：起一个循环

```bash
# 轮询本机任务，用 Claude Code headless 执行，结果自动回传
agent-bus work --me lab --dir ~/agent-work --poll 20 -- \
  --dangerously-skip-permissions --max-turns 30
```

或交给 systemd（见 `examples/agent-worker.service`），开机自动挂。

### 4. 投递与查看

```bash
# 从任何一台机器派活（经受限 SSH）
ssh -i ~/.ssh/agentbus bus-host "agent-bus send lab '汇总 CSV' --body '把 data/ 下的 CSV 汇总成 report.md'"

# 看任务 / 结果
ssh -i ~/.ssh/agentbus bus-host "agent-bus tasks lab"
ssh -i ~/.ssh/agentbus bus-host "agent-bus result <id>"
```

### 远程模式（推荐：机器只出站）

worker 机器不需要同步信箱，直接通过受限 SSH 访问信箱主机：

```bash
export AGENT_BUS_REMOTE=ubuntu@bus-host            # 信箱主机
export AGENT_BUS_SSH_KEY=~/.ssh/agentbus          # 受限密钥
agent-bus tasks lab                                # 等价于 ssh 过去执行
agent-bus work --me lab --dir ~/agent-work         # worker 也走远程
```

MCP 同理：`AGENT_BUS_REMOTE=... claude mcp add agent-bus -- agent-bus-mcp`。

## 任务模板（推荐）

任务正文按统一结构写，任何 agent 都能读懂，能显著减少「自由发挥」：

```text
@workdir: /home/you/project        # 可选；必须是第一行，worker 会 cd 到这里
# 任务
把 data/ 下的 CSV 汇总成 report.md
# 验收标准
- report.md 存在，包含所有 CSV 的汇总
- 用中文
# 背景 / 约束
- 不要修改原始数据
```

- `@workdir` 只对用 `agent-bus work` 的 worker 生效；不写就用 worker 的 `--dir`
- 验收标准是写给执行任务的 agent 看的 —— 它会据此自检
- 示例见 `examples/task-template.md`

## 自检与后台运行

接入新机器时先跑一次自检，它会逐项检查：模式（本地/远程）、Python、SSH 客户端、密钥、信箱可达性、Claude、作业目录。

```bash
agent-bus --remote ubuntu@bus-host --remote-key ~/.ssh/agentbus \
  doctor --me lab --dir ~/agent-work
```

每项输出 `PASS` / `WARN` / `FAIL`，最后一行是 `RESULT: OK` 或 `FAILED`（有 FAIL 时退出码非 0）。

后台运行（关闭终端也不停）：

```bash
agent-bus --remote ubuntu@bus-host --remote-key ~/.ssh/agentbus \
  work --me lab --detach
agent-bus status --me lab     # RUNNING/STOPPED + 最近日志
agent-bus stop --me lab
```

日志默认写到 `~/.agent-bus/worker/<me>.log`（`--log` 可改）。
worker 启动时第一行会打印 `mode: REMOTE ...` 或 `mode: LOCAL ...` —— 本地模式会额外警告「任务不会发往远端」。

## 可靠性

- worker 轮询遇网络错误会指数退避重试（5s → 120s），不会退出
- 结果超过 `AGENT_BUS_MAX_RESULT`（默认 100KB）会截断
- 执行中崩溃的任务会停留在 `running`：`agent-bus reap --me lab --older 60` 回收

安全模型和加固建议见 [SECURITY.md](SECURITY.md)。

## 命令参考

| 命令 | 说明 |
|---|---|
| `agent-bus send <target> <title> [--from N] [--body B]` | 投递任务（body 缺省从 stdin 读），打印任务 id |
| `agent-bus tasks <me> [--all]` | 列出待办 |
| `agent-bus claim <me> <id>` | 原子认领（并发安全） |
| `agent-bus done <me> <id> [--status ok\|fail]` | 提交结果（缺省从 stdin 读） |
| `agent-bus requeue <me> <id>` | 把卡住的任务重置为 pending |
| `agent-bus reap <me> [--older 60]` | 回收超时未完成的任务 |
| `agent-bus show <id>` / `result <id>` | 查看详情 / 结果 |
| `agent-bus list` | 总览 |
| `agent-bus doctor [--me N] [--dir D]` | 环境自检 |
| `agent-bus work --me N --dir D [--detach] [--log F]` | worker 循环（可后台） |
| `agent-bus status --me N` / `stop --me N` | 后台 worker 状态 / 停止 |

## 接入 Claude Code（MCP）

```bash
claude mcp add agent-bus -- agent-bus-mcp
```

之后 Claude 就能直接调用 `send_task` / `list_tasks` / `complete_task` / `get_result`
等工具，不需要记命令行。

## 安全模型

- worker 公钥在信箱主机上被 `command="agent-bus-gate"` 约束，**不能开 shell、不能端口转发**。
- 信箱目录就是权限边界：能写 `tasks/<me>/` 等于能让 `<me>` 执行任务。
- `work --runner claude` 默认会把任务正文交给 Claude Code。如果你加了
  `--dangerously-skip-permissions`，**投递方 = 代码执行权**，请只允许可信来源。
- 生产使用建议：容器 / git worktree 隔离（roadmap）、按 agent 分离系统用户。

## 与同类方案对比

| | agent-bus | multi-fleet | AgentChatBus | Google Scion |
|---|---|---|---|---|
| 依赖 | 无（SSH+文件） | NATS | MCP 服务进程 | Docker/K8s |
| NAT/内网 | 原生友好 | 部分 | 需可达端点 | 需集群 |
| 可审计 | 纯 JSON 文件 | 事件流 | SQLite | 平台日志 |
| 规模 | 个人/小团队 | 中 | 中 | 大 |

agent-bus 不打算赢过重型编排平台，它占的是「**几百行、五分钟、两台机器**」这个角落。

## Roadmap

- [ ] `--worktree`：每任务独立 git worktree / 容器隔离
- [ ] 任务签名与来源校验
- [ ] HTTP / Redis 传输后端（保持文件存储不变）
- [ ] `agent-bus watch` 实时日志
- [ ] Windows worker 一键脚本

## License

MIT
