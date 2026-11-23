# Changelog

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
