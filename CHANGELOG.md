# Changelog

## 0.4.3

- doctor resolves the configured `ssh_bin` and reports port/proxy/known_hosts;
  `~` is expanded for ssh_bin and ssh_known_hosts
- the MCP server loads `agent-bus.toml`, so SSH options and the signing key apply
  when launched by an MCP host
- `stop` falls back to the heartbeat pid, so it also works for supervised workers
- `status` decodes log tails with a UTF-8 -> locale fallback
- docs: task-scheduler guidance fixed (foreground + restart-on-failure),
  443/frp/IPv6 examples, PowerShell note, same-`me` warning, key distribution

## 0.4.2

- configurable SSH client: `ssh_bin`, `ssh_port`, `ssh_proxy_command`,
  `ssh_known_hosts` (flags, env vars and config file)
- Windows shell runner decodes output with the system codepage instead of UTF-8
- docs: `docs/windows.md` (native deployment, Task Scheduler, shell runner) and
  `docs/remote-deployment.md` (Tailscale/IPv6/frp, troubleshooting)
- tests for SSH option assembly and the shell runner

## 0.4.1

- `agent-bus config [show]` prints the effective config (signing key masked)
- workers write a heartbeat; `status` and `doctor` show the last heartbeat and
  queue depth

## 0.4.0

- `work --workers N`: N concurrent task loops; atomic claim keeps tasks unique
- `watch [--me] [--interval] [--once]`: stream status changes and results
- config key: `workers`

## 0.3.0

- task signing with a shared HMAC key (`AGENT_BUS_SIGNING_KEY` / `signing_key`);
  `send` signs target/title/body/sender automatically
- workers verify signatures; `--require-signature` / `require_signature = true`
  refuses unsigned or tampered tasks before they run
- the MCP `send_task` tool signs when the key is set
- note: a shared key proves "an authorized holder sent this", not which agent;
  per-agent asymmetric identity is planned

## 0.2.2

- optional TOML config (`./agent-bus.toml` or
  `~/.config/agent-bus/config.toml`); command line and env take precedence
- new `agent-bus prune --older-days N [--dry-run]` removes old finished tasks
  and their results
- `tomli` is a dependency only on Python < 3.11
- worker logs the config file it loaded

## 0.2.1

- verified the docker sandbox end to end (the CLI refuses
  `--dangerously-skip-permissions` as root)
- docker: run with the caller's uid/gid and `HOME=/tmp`; the image ships a
  non-root user
- Dockerfile: `DEBIAN_MIRROR` / `NPM_REGISTRY` build args for slow networks
- CI: docker job builds the image and runs a sandbox smoke test

## 0.2.0

- PyPI distribution name is `agents-bus` (the CLI command remains `agent-bus`)
- per-task sandboxes: `--sandbox auto|none|worktree|docker` (default `auto`)
  - `worktree`: isolated git worktree per task; diff summary captured in the result
  - `docker`: run inside a container with only the work directory mounted;
    credentials are passed as environment variables, home is never mounted
- `doctor` reports git/docker availability
- sandbox policy is worker-side; `@sandbox:` in task bodies is ignored
- Dockerfile for the worker image in `sandbox/`

## 0.1.5

- fix: force UTF-8 stdio so Chinese help and messages do not crash on
  cp1252/GBK consoles (found by the new Windows CI job)

## 0.1.4

- worker retries polling with exponential backoff (5s to 120s) instead of
  exiting on transient bus errors
- new `agent-bus reap --me <name> --older <minutes>` requeues tasks stuck in
  `running`
- task results are truncated at `AGENT_BUS_MAX_RESULT` (default 100000 chars)
- CI: add a Windows job running the portable suites
- docs: add SECURITY.md and this changelog

## 0.1.3

- `agent-bus doctor` environment self-check
- `work --detach` background mode with a log file; `status` and `stop`
- worker prints its mode at startup and warns when running in local mode

## 0.1.2

- recommended task template and the `@workdir:` directive
- per-task working directory with a clean failure when it is missing

## 0.1.1

- fix: decode subprocess output as UTF-8 (Windows GBK crash)

## 0.1.0

- initial release: file-based task store, remote mode over restricted SSH,
  MCP stdio server, CLI, tests
