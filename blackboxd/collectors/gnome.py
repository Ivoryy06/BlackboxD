"""
blackboxd.collectors.gnome
~~~~~~~~~~~~~~~~~~~~~~~~~~
Collector backend for GNOME Shell (Wayland or X11 session).

Active window:  queried via the org.gnome.Shell D-Bus interface using
                `gdbus call` — no Python D-Bus bindings required.
Idle time:      queried via org.gnome.Mutter.IdleMonitor D-Bus interface.

Both calls are synchronous subprocess invocations; they are fast (<5 ms)
and safe to run on every poll tick.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

from blackboxd.collectors.base import BaseCollector, WindowInfo
from blackboxd.config import CollectorConfig

log = logging.getLogger(__name__)


class GNOMECollector(BaseCollector):
    NAME = "gnome"

    # ---- availability ----------------------------------------------------

    def is_available(self) -> bool:
        if os.environ.get("XDG_CURRENT_DESKTOP", "").upper() not in ("GNOME", "UBUNTU:GNOME"):
            return False
        return _command_exists("gdbus")

    # ---- active window ---------------------------------------------------

    def get_active_window(self) -> WindowInfo | None:
        """
        Query GNOME Shell for the focused window via D-Bus eval.

        Uses the `global.display.focus_window` property exposed by GNOME Shell.
        Returns None if the shell cannot be reached or no window is focused.
        """
        script = (
            "let w = global.display.focus_window; "
            "w ? JSON.stringify({"
            "  title: w.title,"
            "  wm_class: w.get_wm_class(),"
            "  wm_class_instance: w.get_wm_class_instance(),"
            "  workspace: w.get_workspace().index()"
            "}) : 'null'"
        )
        raw = _gdbus_eval(script)
        if raw is None or raw.strip() in ("", "null", "''"):
            return None

        import json
        try:
            # gdbus returns strings wrapped in extra quotes/escaping
            cleaned = raw.strip().strip("'").replace('\\"', '"')
            data: dict[str, Any] = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            log.debug("GNOME: failed to parse window JSON: %s | raw=%r", exc, raw)
            return None

        app_class = data.get("wm_class") or data.get("wm_class_instance")
        app_name  = _prettify(app_class)
        workspace = str(data["workspace"]) if "workspace" in data else None

        return WindowInfo(
            app_name  = app_name,
            app_class = app_class,
            title     = data.get("title"),
            workspace = workspace,
        )

    # ---- idle time -------------------------------------------------------

    def get_idle_seconds(self) -> float:
        """
        Query idle time from org.gnome.Mutter.IdleMonitor via gdbus.
        Returns milliseconds converted to seconds.
        """
        result = _gdbus_call(
            dest    = "org.gnome.Mutter.IdleMonitor",
            path    = "/org/gnome/Mutter/IdleMonitor/Core",
            iface   = "org.gnome.Mutter.IdleMonitor",
            method  = "GetIdletime",
            args    = None,
        )
        if result is None:
            return 0.0

        # gdbus output: "(uint64 123456,)\n"
        match = re.search(r"\((?:uint64\s+)?(\d+),?\)", result)
        if not match:
            return 0.0
        ms = int(match.group(1))
        return ms / 1000.0


# ---------------------------------------------------------------------------
# gdbus helpers
# ---------------------------------------------------------------------------

def _gdbus_eval(script: str) -> str | None:
    """Call org.gnome.Shell.Eval with *script*, return the result string."""
    return _gdbus_call(
        dest   = "org.gnome.Shell",
        path   = "/org/gnome/Shell",
        iface  = "org.gnome.Shell",
        method = "Eval",
        args   = f'"{script}"',
    )


def _gdbus_call(
    dest:   str,
    path:   str,
    iface:  str,
    method: str,
    args:   str | None,
) -> str | None:
    cmd = [
        "gdbus", "call",
        "--session",
        "--dest",   dest,
        "--object-path", path,
        "--method", f"{iface}.{method}",
    ]
    if args:
        cmd.append(args)

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if res.returncode != 0:
            log.debug("gdbus %s.%s failed: %s", iface, method, res.stderr.strip())
            return None
        return res.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.debug("gdbus call error: %s", exc)
        return None


def _command_exists(name: str) -> bool:
    try:
        subprocess.run([name, "--version"], capture_output=True, timeout=1)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _prettify(class_name: str | None) -> str | None:
    if not class_name:
        return None
    name = class_name.rsplit(".", 1)[-1]
    return name.capitalize()
