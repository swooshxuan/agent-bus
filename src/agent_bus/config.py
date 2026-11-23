"""Optional TOML configuration (agent-bus.toml).

Precedence: command line > environment > config file > built-in defaults.

Search order for the config file:
  1. ``--config PATH``
  2. ``$AGENT_BUS_CONFIG``
  3. ``./agent-bus.toml``
  4. ``~/.config/agent-bus/config.toml``
"""

import os

from .store import BusError

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - covered on older Pythons
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

_SEARCH = (
    lambda: os.path.join(os.getcwd(), "agent-bus.toml"),
    lambda: os.path.join(os.path.expanduser("~"), ".config", "agent-bus",
                         "config.toml"),
)


def find_config(explicit=None):
    if explicit:
        return os.path.expanduser(explicit)
    from_env = os.environ.get("AGENT_BUS_CONFIG")
    if from_env:
        return os.path.expanduser(from_env)
    for candidate in _SEARCH:
        path = candidate()
        if os.path.isfile(path):
            return path
    return None


def load_config(explicit=None):
    """Return (settings dict, path or None)."""
    path = find_config(explicit)
    if not path:
        return {}, None
    if not os.path.isfile(path):
        raise BusError("config file not found: %s" % path)
    if tomllib is None:
        raise BusError("TOML config needs Python 3.11+ or the 'tomli' package")
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except Exception as exc:  # noqa: BLE001 - surface a readable message
        raise BusError("invalid config %s: %s" % (path, exc))
    return {key: value for key, value in data.items()
            if not isinstance(value, dict)}, path
