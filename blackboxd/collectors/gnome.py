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

    

    def is_available(self) -> bool:
        if os.environ.get("XDG_CURRENT_DESKTOP", "").upper() not in ("GNOME", "UBUNTU:GNOME"):
            return False
        return _command_exists("gdbus")

    

    def get_active_window(self) -> WindowInfo | None:
        """
        Query GNOME Shell for the focused window via D-Bus eval.

        GNOME 41+ blocks Shell.Eval for security, so on those sessions we
        fall back to xprop when an X11 display is available.
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
            return _x11_active_window()

        import json
        try:
            
            cleaned = raw.strip().strip("'").replace('\\"', '"')
            data: dict[str, Any] = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            log.debug("GNOME: failed to parse window JSON: %s | raw=%r", exc, raw)
            return _x11_active_window()

        app_class = data.get("wm_class") or data.get("wm_class_instance")
        app_name  = _prettify(app_class)
        workspace = str(data["workspace"]) if "workspace" in data else None

        return WindowInfo(
            app_name  = app_name,
            app_class = app_class,
            title     = data.get("title"),
            workspace = workspace,
        )

    

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
            return _x11_idle_seconds()

        
        match = re.search(r"\((?:uint64\s+)?(\d+),?\)", result)
        if not match:
            return _x11_idle_seconds()
        ms = int(match.group(1))
        return ms / 1000.0


def _x11_active_window() -> WindowInfo | None:
    """Fallback for X11 sessions: ask the root window who is focused."""
    if not os.environ.get("DISPLAY"):
        return None
    try:
        root = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            capture_output=True, text=True, timeout=2,
        )
        match = re.search(r"(0x[0-9a-fA-F]+)", root.stdout)
        if not match:
            return None
        wid = match.group(1)
        props = subprocess.run(
            ["xprop", "-id", wid, "_NET_WM_NAME", "WM_CLASS"],
            capture_output=True, text=True, timeout=2,
        )
        title = re.search(r'_NET_WM_NAME\s*=\s*(?:UTF8_STRING\s*)?(.*)', props.stdout)
        klass = re.search(r'WM_CLASS\s*=\s*"([^"]*)"', props.stdout)
        app_class = klass.group(1) if klass else None
        return WindowInfo(
            app_name  = _prettify(app_class),
            app_class = app_class,
            title     = title.group(1).strip('"') if title else None,
            workspace = None,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _x11_idle_seconds() -> float:
    if not os.environ.get("DISPLAY"):
        return 0.0
    try:
        out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=2)
        if out.returncode == 0 and out.stdout.strip().isdigit():
            return int(out.stdout.strip()) / 1000.0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return 0.0






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
