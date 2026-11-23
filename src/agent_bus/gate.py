"""SSH restricted-command gate.

Put this as the forced command of a worker's public key in
``~/.ssh/authorized_keys`` on the bus host::

    command="agent-bus-gate",no-port-forwarding,no-X11-forwarding,\
no-agent-forwarding,no-pty ssh-ed25519 AAAA... lab@worker

Then ``ssh bus "agent-bus send lab 'title'"`` works, but nothing else does.
"""

import os
import shlex
import sys


def main(argv=None):
    command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    try:
        parts = shlex.split(command)
    except ValueError:
        sys.exit("agent-bus-gate: malformed command")
    if not parts or parts[0] != "agent-bus":
        sys.exit("agent-bus-gate: only 'agent-bus ...' is allowed")
    os.execv(sys.executable,
             [sys.executable, "-m", "agent_bus.cli"] + parts[1:])


if __name__ == "__main__":
    main()
