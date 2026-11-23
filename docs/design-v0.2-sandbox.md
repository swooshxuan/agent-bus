# v0.2 设计：任务沙箱

状态：草案（待确认）
目标版本：0.2.0

## 背景与威胁模型

当前 `agent-bus work` 的默认用法是 `claude -p <body> --dangerously-skip-permissions`：
**能向信箱投任务的人，就能在 worker 机器上执行任意代码**。对一个只敢在自己机器上用
的小工具，这是可接受的；要交给别人或团队用，这是红线。

需要先说明一个物理约束：

> Claude Code 必须联网才能推理。因此沙箱**不能**做网络隔离（`--unshare-net` 会直接
> 让任务失败）。沙箱能做到的是：**文件系统隔离 + 进程/资源隔离 + 凭证隔离**。

## 目标

1. 任务默认运行在隔离的工作副本里，主工作区不被污染
2. 能明确看到任务改了什么（diff），可审可回滚
3. 降低「一个恶意/失控任务」的影响半径
4. 不破坏现有用户（`--sandbox none` 保持旧行为）
5. 跨平台可落地：Linux 为主，Windows/macOS 尽力而为

非目标（本版不做）：

- 网络隔离 / 出站白名单
- 多租户与强身份（任务签名留到后续版本）
- 完整 VM 级隔离

## 三种沙箱档位

| 档位 | 隔离内容 | 依赖 | 平台 | 强度 |
|---|---|---|---|---|
| `none` | 无（现状） | 无 | 全平台 | 无 |
| `worktree` | 每任务一个 git worktree，改动不落在主检出；产出 diff | git | 全平台 | 中（只防误伤，不防恶意） |
| `docker` | 容器内执行，只有作业目录被挂载；凭证走环境变量 | Docker/Podman | Linux/Win(Desktop)/macOS | 高（进程+文件） |

`bwrap`（bubblewrap）不单独作为档位：它无法做网络隔离（Claude 需要联网），
而文件系统隔离 worktree 已经覆盖；留作将来与 docker 组合使用。

## 推荐默认值：`auto`

- 有效作业目录是 **git 仓库** → 自动使用 `worktree`
- 否则 → `none`，但日志打印醒目 WARN：

  ```
  [agent-bus] WARN: sandbox=auto fell back to none (not a git repo)
  [agent-bus] WARN: tasks can modify files and run code; see SECURITY.md
  ```

用户可用 `--sandbox none|worktree|docker` 显式指定；`--sandbox docker` 在
Docker 不可用时**直接失败**，不静默降级。

安全策略由 **worker 侧**决定，任务正文里的 `@sandbox:` 指令**一律忽略**
（否则任务作者可以自我降级）。这一点会写进 README 和测试。

## worktree 档位

对每个任务：

```bash
git -C <repo> worktree add --detach <state>/worktrees/<task-id> HEAD
```

- 任务在 worktree 内执行（`--dir` 就指向它）
- 任务完成后：
  - 采集 `git diff --stat` 与完整 patch（保存在结果元数据中或文件引用）
  - 默认删除 worktree；`--keep-worktrees` 保留
- 非 git 目录：报错（`--sandbox worktree` 时）或按 `auto` 降级

优点：零额外依赖、跨平台、diff 天然可审计。
局限：不阻止代码执行（只是脏不到主目录）。

## docker 档位

```
docker run --rm -i \
  -v <host-workdir>:/work -w /work \
  -e ANTHROPIC_API_KEY (或等价凭证) \
  agent-bus-worker:<tag> \
  claude -p <body> --dangerously-skip-permissions ...
```

- 镜像由仓库内 `sandbox/Dockerfile` 构建（node:22-slim + claude CLI）
- **不挂载用户 home**；凭证通过环境变量传入
- 默认 `--network bridge`（Claude 需要联网）；可选 `--network none` 供纯脚本任务
- 资源限制：`--memory 2g --cpus 2 --pids-limit 256`（可配置）
- 容器内免权限运行时仍需 skip-permissions，但影响半径限制在容器 + 作业目录

## CLI 变更

```text
agent-bus work --me N --dir D [--sandbox auto|none|worktree|docker]
               [--keep-worktrees] [--docker-image IMG] [--docker-network bridge|none]
```

- 默认 `--sandbox auto`
- 启动日志增加：`sandbox: worktree (repo: /path)` / `sandbox: docker (image: ...)`
- `doctor` 增加检查：git 是否可用、worktree 是否可建、docker 是否可用

## 结果元数据

任务结果（`results/<id>.json`）增加可选字段：

```json
{
  "sandbox": "worktree",
  "sandbox_info": {
    "repo": "/home/u/project",
    "worktree": "/home/u/.agent-bus/worktrees/<id>",
    "diff_stat": "3 files changed, 42 insertions(+), 7 deletions(-)",
    "diff": "..."            // 或 diff_file 引用，超过阈值时
  }
}
```

## 代码结构

- 新增 `src/agent_bus/sandbox.py`
  - `Sandbox(mode, task_dir, task_id, opts)` → `.run_dir`、`.wrap(argv)`、`.finish(status)`
- `cli.py` 的 worker 循环：每个任务创建/销毁 sandbox
- `tests/test_sandbox.py`：worktree 隔离与 diff 采集；docker 测试在无 Docker 时 skip
- 文档：README、SECURITY.md、CHANGELOG

## 实施顺序

1. `sandbox.py` + worktree 档位 + 测试（半天～1 天）
2. docker 档位 + Dockerfile + 测试（1～2 天）
3. doctor 增补、文档、发布 0.2.0（半天）

## 验收标准

- [ ] 在 git 仓库上用 `auto`，任务改动落在 worktree；主检出无改动；结果含 diff 统计
- [ ] `--sandbox docker` 在服务器上跑通一个真实任务；容器内看不到宿主 home
- [ ] 非 git 目录 + `auto` 时给出明确 WARN，行为与旧版一致
- [ ] 任务正文中的 `@sandbox:` 被忽略（测试覆盖）
- [ ] 无 Docker 时 `--sandbox docker` 立即报错退出
- [ ] CI 覆盖 worktree 测试（Linux + Windows），docker 测试按可用性 skip

## 待确认

1. 默认值用 `auto`（推荐）还是保持 `none`？
2. docker 镜像：仓库内 Dockerfile 本地构建（推荐）还是发布到 ghcr.io？
