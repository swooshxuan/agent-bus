# Windows 部署指南

agent-bus 在 Windows 上可用，但需要几个与 Linux 不同的设置。本文覆盖安装、配置、
后台运行（任务计划程序）、SSH 客户端选择和 shell runner 的行为差异。

## 1. 前置条件

| 项 | 要求 | 检查 |
|---|---|---|
| 系统 | Windows 10/11 | — |
| Python | 3.8+ | `python --version` |
| OpenSSH 客户端 | 系统自带 | `where ssh` |
| agent-bus | pip 安装 | `agent-bus --help` |

没有 Python：`winget install -e --id Python.Python.3.12`，装完重开终端。

## 2. 安装与接入

```bat
pip install agents-bus
ssh-keygen -t ed25519 -f "%USERPROFILE%\.ssh\agentbus" -N ""
type "%USERPROFILE%\.ssh\agentbus.pub"
```

把公钥发到信箱主机，加入 `~/.ssh/authorized_keys`（带受限命令）：

```
command="agent-bus-gate",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... pc-name
```

## 3. 配置文件

路径：`%USERPROFILE%\.config\agent-bus\config.toml`（或当前目录的 `agent-bus.toml`）。

```toml
remote = "ubuntu@bus-host"
remote_key = "C:/Users/you/.ssh/agentbus"
me = "pc1"
dir = "C:/Users/you/agent-work"
poll = 10
workers = 2
sandbox = "auto"
signing_key = "<与信箱主机一致>"
```

> ⚠️ TOML 基本字符串会把 `\` 当转义符。Windows 路径请用正斜杠
> `C:/Users/...`，或单引号字面量 `'C:\Users\...'`。

## 4. 自检与前台运行

```bat
agent-bus doctor --me pc1 --dir "%USERPROFILE%\agent-work"
agent-bus work
```

`doctor` 会逐项检查模式、SSH、密钥、信箱、CLI runner、workdir。

## 5. 后台运行

```bat
agent-bus work --detach
agent-bus status --me pc1
agent-bus stop --me pc1
```

日志默认在 `%USERPROFILE%\.agent-bus\worker\pc1.log`（`--log` 可改）。

## 6. 开机自启（任务计划程序）

创建 `E:\frp\agent.bat`：

```bat
@echo off
agent-bus work --detach
```

注册任务（登录后自动启动、失败自动重启）：

```bat
schtasks /create /tn "agent-bus" /tr "E:\frp\agent.bat" /sc onlogon /rl highest /f
```

- 用 `onlogon` 而不是 `onstart`：worker 需要用户环境（PATH、凭证、配置）
- `agent.bat` 内部用 `--detach`，任务本身立即退出，worker 在后台持续运行
- 任务计划程序 GUI 里可以设置「失败后重启」（触发器与操作之外，另在「设置」页配置）
- 更新 agent-bus 后需要 `agent-bus stop --me pc1` 再启动，后台进程才会用新版本

## 7. SSH 客户端选择

默认使用系统 OpenSSH（`C:\Windows\System32\OpenSSH\ssh.exe`）。如果使用
Git for Windows 的 ssh：

```toml
ssh_bin = "C:/Program Files/Git/usr/bin/ssh.exe"
```

对应环境变量：`AGENT_BUS_SSH_BIN`。

## 8. shell runner 在 Windows 上的行为

`--runner shell` 在 Windows 上通过 `cmd.exe /c` 执行任务正文（POSIX 上是 `sh -c`）。

| 方面 | Windows 行为 | 建议 |
|---|---|---|
| 解释器 | `cmd.exe` | 不要使用 `bash` 语法（`&&`、`$VAR` 等在 cmd 中语义不同） |
| 退出码 | 命令成功为 0，失败非 0 | 用 `exit /b N` 控制 |
| 路径 | 反斜杠、盘符 | 任务里写绝对路径最稳 |
| 编码 | 输出按系统代码页（中文为 GBK）解码 | 输出 UTF-8 内容时建议用 `python -c` |
| 跨平台任务 | — | 写成 `python -c "..."` 两边都能跑 |

示例（跨平台）：

```text
python -c "print('hello from', __import__('platform').node())"
```

## 9. 排错

```bat
agent-bus doctor --me pc1 --dir "%USERPROFILE%\agent-work"
agent-bus status --me pc1
agent-bus tasks pc1 --all
type "%USERPROFILE%\.agent-bus\worker\pc1.log"
```

| 现象 | 处理 |
|---|---|
| `Permission denied (publickey)` | 检查 `remote_key` 路径、公钥是否已加入信箱主机 |
| `host key verification failed` | 首次连接执行 `ssh -o StrictHostKeyChecking=accept-new user@host true` |
| worker 显示 up 但没动静 | 看启动首行 `mode:` 是否为 REMOTE；看 `status` 心跳 |
| 任务长期 pending | 目标机器 worker 未运行或不可达 |
| 任务卡在 running | `agent-bus reap --me pc1 --older 60` |
