# BlackboxD

A small flight recorder for your computer. It notices which window you are in, how long you stay there, and when you wander off — then turns the day into a readable timeline. Everything stays in a SQLite file on your own machine.

Made by [Ivoryy06](https://github.com/Ivoryy06).

## What's in here

```
blackboxd/                the Python daemon
  daemon.py               poll loop: collect → normalize → store
  models.py               Event, Session, TimelineDay
  config.py               TOML settings (sane defaults, no file required)
  cli.py                  blackboxd-report, dashboard serve + export
  storage/engine.py       append-only SQLite store, WAL mode
  timeline/
    reconstructor.py      events → sessions → one day
    renderer.py           terminal output
  collectors/
    base.py               collector interface + idle/focus detection
    hyprland.py           Hyprland via hyprctl
    gnome.py              GNOME via gdbus (xprop fallback)
    mock.py               fake day, for tests and demos
go-api/main.go            read-only HTTP API on :8080
rust-exporter/            JSON / CSV exporter
listener/                 Hyprland socket2 workspace listener
workspacegrid/            little React workspace grid
index.html                the dashboard (live, demo, and offline export)
install.sh                user install helper
test/                     pytest suite
```

## The dashboard

`index.html` is one page with five views: timeline, apps, heatmap, raw log and notes. It has the same pink-on-plum look as the rest of the sites, and it only ever talks to `localhost`.

There are three ways to see it:

1. **GitHub Pages** — <https://ivoryy06.github.io/BlackboxD/>. The page opens on the sample-data gate, because an `https` page is not allowed to call `http://localhost`.
2. **Local, no Go** — `blackboxd-report serve`. This opens `http://127.0.0.1:9100` and reads SQLite directly through small `/data` routes.
3. **Local, with the API** — run `go-api` on `:8080` and serve the folder however you like (`python -m http.server`). The page finds the API by itself.

`blackboxd-report dashboard --export ~/day.html` bakes every stored event into a single file you can open offline or keep as a snapshot.

Features: deep/idle filters, app totals, a seven-day by-hour heatmap, raw log filters, per-day notes in `localStorage`, keyboard shortcuts `1`–`5`, and a demo mode with a made-up day.

## Install

You need Python 3.11+, and optionally Go 1.21+ for the API.

```bash
git clone https://github.com/Ivoryy06/BlackboxD.git
cd BlackboxD
pip install -e .

# or let the script do it and set up a systemd user service
chmod +x install.sh
./install.sh
```

Start recording:

```bash
blackboxd                        # auto-detects Hyprland or GNOME
blackboxd --backend mock         # fake events, nice for a first look
```

Then either:

```bash
blackboxd-report serve           # dashboard on :9100
cd go-api && go build -o blackboxd-api . && ./blackboxd-api   # API on :8080
```

The config file lives at `~/.config/blackboxd/config.toml` (TOML, not YAML). Everything has a default, so you can start with no file at all. The database is `~/.local/share/blackboxd/events.db`.

## GNOME note

GNOME 41 and later block `org.gnome.Shell.Eval` for security. The collector falls back to `xprop` on X11 sessions; on a Wayland session you will need a shell extension that exposes the focused window, or use the Hyprland backend. It will not crash — it just returns nothing when it cannot see the window.

## Report and export

```bash
blackboxd-report                 # today
blackboxd-report --date 2026-10-31
blackboxd-report --days 7 --summary
blackboxd-report --raw --limit 50
blackboxd-report dashboard --export activity.html
```

Rust exporter:

```bash
cd rust-exporter
cargo build --release
./target/release/blackboxd-export --format json --output activity.json
```

## Tests

```bash
python -m pytest test/
```

The tests use the mock collector and a temporary database, so they never touch your real events.

## Privacy

Nothing is uploaded. Window titles can be suppressed (`suppress_titles = true`) or hashed (`hash_titles = true`) in the config. Retention can be capped with `retention_days`.

## Licence

MIT — see [LICENSE](LICENSE).

Made by [Ivoryy06](https://github.com/Ivoryy06) with too much coffee.
