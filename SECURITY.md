# Security Policy

## Threat model

agent-bus is a task mailbox. Workers execute whatever task lands in their queue.

- **Who can write tasks can influence what workers run.** With
  `claude --dangerously-skip-permissions`, task authors effectively obtain code
  execution on the worker machine.
- The bus is plain files. Anyone with filesystem or SSH access to the bus host
  can read, forge and delete tasks and results.
- Transport security comes from SSH. Pin worker keys with
  `command="agent-bus-gate"` so they cannot open a shell or forward ports.

## Hardening checklist

- Give every worker its own key and restrict it in `authorized_keys`:

  ```
  command="agent-bus-gate",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... worker@host
  ```

- Run workers under a dedicated low-privilege account, ideally in a container
  or VM, and point `--dir` at a throwaway workspace.
- Treat the bus as a trust boundary: only let trusted agents and humans send
  tasks. Anyone who can reach the bus can queue code for every worker.
- Keep the bus host patched; put fail2ban in front of SSH and prefer a
  VPN/tunnel over exposing SSH to the internet.
- Bound result size with `AGENT_BUS_MAX_RESULT` (default 100000 characters).
- Rotate `auth.token` (frp) and stcp `secretKey`s if they may have leaked.
- Recover stuck jobs with `agent-bus reap --me <name> --older 60`.

## Supported versions

0.1.x receives fixes. Please upgrade before reporting an issue.

## Reporting a vulnerability

Open a private security advisory on GitHub (Security -> Advisories -> New
advisory) or email the maintainer. Please do not file a public issue for
exploitable problems.
