"""
blackboxd.collectors.hyprland
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Collector backend for the Hyprland Wayland compositor.

Uses `hyprctl activewindow -j` to query the active window and
`hyprctl activeworkspace -j` for the current workspace. Both are
fast local IPC calls over a Unix socket — no D-Bus required.

Idle detection uses `hypridle` indirectly: we query the last input
time via `hyprctl devices -j` (tracks last input timestamp).
Falls back to a monotonic timer if hypridle data is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Any

from blackboxd.collectors.base import BaseCollector, WindowInfo
from blackboxd.config.config import CollectorConfig

log = logging.getLogger(__name__)


class HyprlandCollector(BaseCollector):
    NAME = "hyprland"

    def __init__(self, config: CollectorConfig) -> None:
        super().__init__(config)
        self._last_input_time: float = time.monotonic()

    # ---- availability ----------------------------------------------------

    def is_available(self) -> bool:
        """True if HYPRLAND_INSTANCE_SIGNATURE is set and hyprctl exists."""
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return False
        return _command_exists("hyprctl")

    # ---- active window ---------------------------------------------------

    def get_active_window(self) -> WindowInfo | None:
        data = _hyprctl("activewindow")
        if data is None or not isinstance(data, dict):
            return None

        # hyprctl returns {"class": "...", "title": "...", ...}
        app_class = data.get("class") or None
        title     = data.get("title") or None

        # Derive a human name from the class: "firefox" → "Firefox"
        app_name = _prettify(app_class)

        # Workspace info is embedded in the activewindow response
        workspace_id   = data.get("workspace", {}).get("id")
        workspace_name = data.get("workspace", {}).get("name")
        workspace = workspace_name or (str(workspace_id) if workspace_id else None)

        return WindowInfo(
            app_name  = app_name,
            app_class = app_class,
            title     = title,
            workspace = workspace,
        )

    # ---- idle time -------------------------------------------------------

    def get_idle_seconds(self) -> float:
        """
        Approximate idle time by querying the last registered input device event.

        `hyprctl devices -j` returns a list of keyboards and mice with
        `lastTimestamp` fields (milliseconds since compositor start, or 0).
        We track the max seen timestamp and compare against monotonic time.
        """
        data = _hyprctl("devices")
        if data is None:
            return 0.0

        latest_ms: int = 0
        for category in ("keyboards", "mice", "tablets"):
            for device in data.get(category, []):
                ts = device.get("lastTimestamp", 0)
                if ts and ts > latest_ms:
                    latest_ms = ts
                    self._last_input_time = time.monotonic()

        elapsed = time.monotonic() - self._last_input_time
        return max(0.0, elapsed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hyprctl(command: str) -> Any | None:
    """Run `hyprctl <command> -j` and return parsed JSON, or None on error."""
    try:
        result = subprocess.run(
            ["hyprctl", command, "-j"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            log.debug("hyprctl %s failed: %s", command, result.stderr.strip())
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as exc:
        log.debug("hyprctl %s error: %s", command, exc)
        return None


def _command_exists(name: str) -> bool:
    try:
        subprocess.run([name, "--version"], capture_output=True, timeout=1)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _prettify(class_name: str | None) -> str | None:
    """Turn a WM class into a display name: 'firefox' → 'Firefox'."""
    if not class_name:
        return None
    # Some apps use "org.gnome.Foo" style — take the last segment.
    name = class_name.rsplit(".", 1)[-1]
    return name.capitalize()
