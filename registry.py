"""
blackboxd.collectors.registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Auto-detects the appropriate collector backend for the current environment
and instantiates it.

Detection order (first available wins):
  1. "mock"      — always available; used for testing
  2. "hyprland"  — HYPRLAND_INSTANCE_SIGNATURE is set + hyprctl exists
  3. "gnome"     — XDG_CURRENT_DESKTOP=GNOME + gdbus exists
  4. "x11"       — DISPLAY is set + xprop / xdotool exist  (future)

If backend = "auto", detection runs in that order.
If backend is explicitly named, that backend is loaded directly.
"""

from __future__ import annotations

import logging

from blackboxd.collectors.base import BaseCollector
from blackboxd.config.config import CollectorConfig

log = logging.getLogger(__name__)

# Map of backend name → module + class name (lazy imports)
_REGISTRY: dict[str, tuple[str, str]] = {
    "mock":     ("blackboxd.collectors.mock",      "MockCollector"),
    "hyprland": ("blackboxd.collectors.hyprland",  "HyprlandCollector"),
    "gnome":    ("blackboxd.collectors.gnome",     "GNOMECollector"),
}

_AUTO_ORDER = ["hyprland", "gnome"]


def get_collector(config: CollectorConfig) -> BaseCollector:
    """Instantiate and return the appropriate collector for *config.backend*.

    Raises:
        RuntimeError: If no suitable backend can be found.
    """
    backend = config.backend.lower()

    if backend == "auto":
        return _auto_detect(config)

    return _load(backend, config)


def list_available() -> list[str]:
    """Return names of all registered backends."""
    return list(_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _auto_detect(config: CollectorConfig) -> BaseCollector:
    for name in _AUTO_ORDER:
        try:
            collector = _load(name, config)
            if collector.is_available():
                log.info("Auto-detected collector backend: %s", name)
                return collector
        except ImportError as exc:
            log.debug("Skipping %s: %s", name, exc)

    raise RuntimeError(
        "No suitable collector backend found for this environment. "
        "Set [collector] backend = 'mock' in your config to run without "
        "a supported compositor."
    )


def _load(name: str, config: CollectorConfig) -> BaseCollector:
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown collector backend: {name!r}. "
            f"Available: {list(_REGISTRY)}"
        )

    module_path, class_name = _REGISTRY[name]

    import importlib
    module = importlib.import_module(module_path)
    cls: type[BaseCollector] = getattr(module, class_name)
    return cls(config)
