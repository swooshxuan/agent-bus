# 跨网络部署与排障

agent-bus 对网络只有一个要求：**每台 worker 能建立一条到信箱主机的 SSH 连接**。
worker 不需要公网 IP，也不需要与其它 worker 在同一网段。

## 1. 选择拓扑

| 拓扑 | 需要什么 | 适用场景 |
|---|---|---|
| **公网主机（VPS/云服务器）当信箱** | 一台公网 SSH 主机 | 最省心，推荐 |
| **Tailscale / ZeroTier 组网** | 两端安装客户端（免费） | 都无公网 IP，不想买服务器 |
| **IPv6 直连** | 两端都有公网 IPv6 | 零成本，先检测 |
| **frp / 反向隧道** | 一台公网中继 | 沿用现有 frp 设施 |
| **路由器端口映射** | 公网 IPv4 + 端口转发 | 家庭宽带 |

快速检测 IPv6：`curl -6 ifconfig.co`。若有公网地址且双向可达，直接把
`remote` 写成 `用户名@[2408:...]` 即可，无需组网。

### 1.1 只放行 443 端口

服务器 sshd 增加一个 443 监听：

```bash
sudo tee /etc/ssh/sshd_config.d/443.conf >/dev/null <<'EOF'
Port 443
EOF
sudo sshd -t && sudo systemctl restart ssh
# 云厂商安全组放行 443/TCP
```

worker 配置：

```toml
remote = "user@bus-host"
ssh_port = 443
```

### 1.2 用现有 frp 暴露信箱主机的 SSH

信箱主机在 NAT 后时，用 frpc 把本机 22 映射到公网中继：

```toml
# frpc.toml on the bus host
serverAddr = "relay.example.com"
serverPort = 7000
auth.token = "..."
[[proxies]]
name = "bus-ssh"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = 2222
```

客户端配置：

```toml
remote = "user@relay.example.com"
ssh_port = 2222
```

## 2. Tailscale 示例（无公网、零成本）

1. 两台机器安装 Tailscale，登录同一账号，记下各自的 `100.x.x.x` 地址
2. 选一台作为**信箱主机**（Linux/macOS 最省事；Windows 做主机可行但需要给 gate 写绝对路径）
3. 主机上：

   ```bash
   pip install agents-bus
   mkdir -p ~/agent-bus
   # 把客户端的公钥加入 ~/.ssh/authorized_keys，带 command="agent-bus-gate"
   ```

4. 客户端 `~/.config/agent-bus/config.toml`：

   ```toml
   remote = "user@100.x.y.z"
   remote_key = "~/.ssh/agentbus"
   me = "pc2"
   dir = "~/agent-work"
   ```

5. 主机端可以用本地模式（`base = "~/agent-bus"`），客户端用远程模式指向主机。

> 组网只解决「怎么连上」，任务仍然走 SSH + 信箱，和公网部署完全一样。

## 3. SSH 连接参数

以下配置项同时支持命令行参数和环境变量，命令行优先：

| 配置项 | CLI | 环境变量 | 说明 |
|---|---|---|---|
| `ssh_bin` | `--ssh-bin` | `AGENT_BUS_SSH_BIN` | SSH 客户端路径（如 Git for Windows） |
| `ssh_port` | `--ssh-port` | `AGENT_BUS_SSH_PORT` | 非标准端口 |
| `ssh_proxy_command` | `--ssh-proxy` | `AGENT_BUS_SSH_PROXY_COMMAND` | 跳板机 / 自定义代理 |
| `ssh_known_hosts` | `--ssh-known-hosts` | `AGENT_BUS_SSH_KNOWN_HOSTS` | 独立的 known_hosts 路径 |

示例（经跳板机）：

```toml
remote = "user@10.0.0.5"
ssh_proxy_command = "ssh -W %h:%p jump@bastion.example.com"
```

示例（非标准端口 + 自定义客户端）：

```toml
remote = "user@bus.example.com"
ssh_port = 2222
ssh_bin = "C:/Program Files/Git/usr/bin/ssh.exe"
```

## 4. 排障清单

先跑 `agent-bus doctor --me <me> --dir <dir>`，它会检查：模式、SSH 客户端、密钥、
信箱可达性、CLI runner、workdir。

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `Permission denied (publickey)` | 公钥未加到主机 / 密钥路径不对 | 对照 `--remote-key` 与 `authorized_keys` |
| `host key verification failed` | 首次连接 | `ssh -o StrictHostKeyChecking=accept-new host true` |
| `Connection timed out` | 端口被拦 | 改用 443 端口、Tailscale 或现有隧道 |
| 任务一直 `pending` | worker 没运行 / 轮询没到 | 目标机器 `agent-bus status`、看心跳 |
| 任务 `running` 不结束 | worker 崩溃或超时 | `agent-bus reap --me X --older 60` |
| 结果 `refused: missing signature` | 签名未配置或密钥不一致 | 两端 `signing_key` 必须相同 |
| worker 显示 up 但仓库无变化 | 处于本地模式 | 启动首行 `mode:` 必须是 REMOTE |

实时观察：`agent-bus watch --me lab`（Ctrl+C 退出）。

## 5. 安全

- 每台机器一把密钥，`authorized_keys` 中限制为 `command="agent-bus-gate"`
- 开启 `require_signature` 前确保所有发送方都配置了相同的 `signing_key`
- 不可信来源的任务使用 `--sandbox docker`（容器仅挂载作业目录）
- 不要把信箱主机的 SSH 直接暴露给不可信网络；优先 VPN/组网或 fail2ban
- 同一台机器不要启动两个同名 `me` 的 worker（心跳与 pid 文件会互相覆盖）；多实例请用不同 `me`，或单进程 `workers = N`
- 签名密钥通过安全渠道分发（scp、密码管理器），不要发在聊天或公开频道
