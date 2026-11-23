# 使用手册

本文假设一个典型拓扑：一台常开的**信箱主机**（VPS/服务器），以及若干台
**worker 机器**（笔记本、实验室主机、家用服务器……）。worker 只需要能出站 SSH
到信箱主机，因此 NAT/校园网环境下无需公网 IP。

```
[worker A] ──SSH──┐
                  ├──→ 信箱（tasks/ results/）←── Claude / agent 读写
[worker B] ──SSH──┘
```

## 1. 一次性配置

### 1.1 信箱主机

```bash
pip install agents-bus                       # 命令仍是 agent-bus
export AGENT_BUS_DIR=/srv/agent-bus          # 建议写入 ~/.bashrc
agent-bus list                               # 创建目录并确认可用
```

给每个 worker 的公钥加**强制命令**（只能执行 agent-bus，不能开 shell）：

```
command="agent-bus-gate",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... worker-a
```

### 1.2 worker 机器

```bash
pip install agents-bus
agent-bus --remote ubuntu@bus-host --remote-key ~/.ssh/agentbus \
  doctor --me lab --dir ~/agent-work
```

`doctor` 应全部 PASS（claude 可按需 WARN）。然后启动 worker：

```bash
agent-bus --remote ubuntu@bus-host --remote-key ~/.ssh/agentbus \
  work --me lab --dir ~/agent-work --poll 20 -- \
  --dangerously-skip-permissions --max-turns 30
```

### 1.3 Windows 快捷脚本（推荐）

在 `E:\frp\` 下创建两个文件（路径按需修改）：

`bus.bat`（日常派活/查结果）：

```bat
@echo off
agent-bus --remote ubuntu@bus-host --remote-key "%USERPROFILE%\.ssh\agentbus" %*
```

`agent.bat`（启动 worker，含后台参数）：

```bat
@echo off
agent-bus --remote ubuntu@bus-host --remote-key "%USERPROFILE%\.ssh\agentbus" work --me laptop --dir "%USERPROFILE%\agent-work" --poll 10 -- --dangerously-skip-permissions --max-turns 30
pause
```

> 注意：`--` 之后的参数是传给 `claude` 的；没有 `--dangerously-skip-permissions`
> 时，headless 模式下的工具调用会被拒绝，任务只能做文本回复。

## 2. 日常操作

### 2.1 发任务

```bash
# 短任务
agent-bus --remote ... send lab "回显测试" --body "请只回复：OK"

# 正式任务（推荐：文件 + 模板）
agent-bus --remote ... send lab "CSV 汇总" < task.txt
```

### 2.2 任务模板

```text
@workdir: /home/you/project        # 可选；第一行；worker 会 cd 到这里
# 任务
把 data/ 下的 CSV 汇总成 report.md
# 验收标准
- report.md 存在，包含所有 CSV 的汇总行
- 用中文，表格对齐
# 背景 / 约束
- 缺失值记 0，不要修改原始 CSV
```

- `@workdir` 只对 `agent-bus work` 生效；不写则用 `--dir`
- 验收标准写给执行任务的 agent 看，它会据此自检
- 一个任务一个产物；上下文里写清路径

### 2.3 查看

```bash
agent-bus --remote ... list            # 各目标 pending/running/done/failed
agent-bus --remote ... tasks lab --all # 详细列表
agent-bus --remote ... result <id>     # 结果
```

## 3. worker 管理

| 平台 | 启动 | 查看 | 停止 |
|---|---|---|---|
| Windows | `agent.bat` 或 `work ... --detach` | `agent-bus status --me laptop` | `agent-bus stop --me laptop` |
| Linux systemd | `systemctl --user enable --now agent-bus-worker` | `systemctl --user status agent-bus-worker` | `systemctl --user stop agent-bus-worker` |

后台模式（关闭终端不退出）：

```bash
agent-bus --remote ... work --me lab --dir ~/agent-work --detach
agent-bus status --me lab
agent-bus stop --me lab
```

日志默认在 `~/.agent-bus/worker/<me>.log`（`--log` 可改）。

systemd 用户服务示例见 `examples/agent-worker.service`；开机自启需要
`sudo loginctl enable-linger $USER`。

## 4. 沙箱（v0.2+）

`work` 默认 `--sandbox auto`：

- 任务目录是 **git 仓库** → 每任务一个 worktree（主检出不变，结果带 diff）
- 否则退回 `none` 并打印 WARN

```bash
agent-bus work ... --sandbox worktree      # 强制 worktree
agent-bus work ... --sandbox docker        # 容器隔离（需 Docker）
agent-bus work ... --sandbox none          # 旧行为
agent-bus work ... --keep-worktrees        # 保留 worktree 供检查
```

docker 镜像：

```bash
docker build -t agent-bus-worker sandbox/
# 慢网络（国内）：
docker build --build-arg DEBIAN_MIRROR=mirrors.tuna.tsinghua.edu.cn \
  --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
  -t agent-bus-worker sandbox/
```

容器只挂作业目录，凭证通过 `ANTHROPIC_API_KEY` 等环境变量传入，不挂 home。
容器以**非 root** 身份运行（CLI 拒绝以 root 使用 skip-permissions；运行时用
`--user` 对齐宿主 uid，`HOME=/tmp`）。安全档位由 **worker 侧**决定，任务正文里的
`@sandbox:` 会被忽略。

## 5. 多机协作示例

服务器上的 Claude（或任何人）派活，各机器处理本机文件，结果回信箱：

```bash
# 1) 两端各自动手
agent-bus --remote ... send lab "统计文件" --body "统计 ~/agent-work 的文件数和大小"
agent-bus --remote ... send laptop "统计文件" --body "统计 %USERPROFILE%\\agent-work 的文件数和大小"

# 2) 读结果
agent-bus --remote ... result <lab-id>
agent-bus --remote ... result <laptop-id>

# 3) 汇总：把两份结果拼成新任务，发给想落结果的一方
agent-bus --remote ... send lab "汇总" < combined.txt
```

要点：每台 agent 只访问本机磁盘；跨机数据通过任务正文/结果传递；结果超过
`AGENT_BUS_MAX_RESULT`（默认 100KB）会被截断，大产出应写文件并汇报路径。

## 6. 排错

```bash
agent-bus --remote ... doctor --me laptop --dir D   # 环境、密钥、信箱、claude、git/docker
agent-bus status --me laptop                        # 后台 worker 状态 + 日志尾部
agent-bus --remote ... tasks lab --all              # 任务卡在哪
agent-bus --remote ... reap lab --older 60          # 回收卡在 running 的任务
```

| 现象 | 处理 |
|---|---|
| 任务一直 pending | 目标 worker 没在跑，或轮询未到 |
| `result not ready` | worker 还在执行；看 status 日志 |
| 卡在 running | worker 崩溃过：`reap` |
| worker 显示 up 但空转 | 看启动第一行 `mode:` 是否为 REMOTE |
| 中文乱码/崩溃（旧版） | 升级到 0.1.5+ |

## 7. 安全

详见 [SECURITY.md](../SECURITY.md)。两条底线：

1. **能往信箱写任务 = 能让 worker 执行代码。** 私钥不外传，只给可信来源。
2. **优先沙箱**：至少 `auto`（git 仓库 → worktree），不可信来源用 `docker`。

## 8. 升级

```bash
pip install --upgrade agent-bus        # PyPI 发布后
# 或从 release wheel 安装
```

升级后重启 worker；`agent-bus doctor` 会报告版本与各组件状态。
