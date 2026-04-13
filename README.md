[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

# BlackboxD

A lightweight desktop activity tracker. Records window focus, workspace switches, and idle time across GNOME and Hyprland — then lets you query, visualise, and export the data.

## Architecture

Four components, each in the language best suited to its job:

| Component | Language | Role |
|---|---|---|
| `blackboxd/` | Python | Daemon — collects events, writes SQLite |
| `go-api/` | Go | HTTP API — serves events to the dashboard and Lua listener |
| `rust-exporter/` | Rust | CLI exporter — dumps events to JSON or CSV |
| `listener/` | Lua | Hyprland IPC listener — notifies the Go API on workspace events |

## Project Structure

```
BlackboxD/
├── blackboxd/
│   ├── daemon.py           # Main daemon process
│   ├── models.py           # Event, Session, TimelineDay types
│   ├── config.py           # Configuration management
│   ├── cli.py              # blackboxd CLI entry point
│   ├── storage/engine.py   # Append-only SQLite event store (WAL mode)
│   ├── timeline/
│   │   ├── reconstructor.py  # Builds Sessions and TimelineDays from raw events
│   │   └── renderer.py       # Formats timeline for terminal output
│   └── collectors/
│       ├── base.py           # Abstract collector interface
│       ├── gnome.py          # GNOME Shell collector (D-Bus)
│       ├── hyprland.py       # Hyprland collector (IPC socket)
│       └── mock.py           # Mock collector for testing
├── go-api/
│   ├── main.go             # HTTP API server
│   └── go.mod
├── rust-exporter/
│   ├── src/main.rs         # Export CLI (JSON / CSV)
│   └── Cargo.toml
├── listener/
│   └── blackboxD-listener.lua  # Hyprland socket2 event listener
├── workspacegrid/
│   └── WorkspaceGrid.tsx   # React workspace visualisation component
├── dashboard.html          # Web dashboard (standalone HTML)
├── install.sh              # One-shot installer
├── pyproject.toml
└── test/test_blackboxd.py
```

## Installation

### Prerequisites

- Python 3.11+
- Go 1.21+ (for the API server)
- Rust 1.70+ / Cargo (for the exporter)
- Lua 5.4+ with `luasocket` (for the Hyprland listener)

### Quick install

```bash
git clone https://github.com/Ivoryy06/BlackboxD.git
cd BlackboxD
chmod +x install.sh && ./install.sh
```

### Manual

```bash
# Python daemon
pip install -e .

# Go API
cd go-api && go build -o blackboxd-api .

# Rust exporter
cd rust-exporter && cargo build --release
# binary: target/release/blackboxd-export
```

## Usage

### Python daemon

```bash
blackboxd start          # start recording
blackboxd stop           # stop
blackboxd status         # show daemon status
blackboxd stats          # print activity summary
blackboxd report         # full timeline report
```

Config lives at `~/.config/blackboxd/config.yaml`. The SQLite database is at `~/.local/share/blackboxd/events.db`.

### Go API (`go-api/`)

Serves the event database over HTTP. The Lua listener and web dashboard both talk to this.

```bash
cd go-api
BLACKBOXD_DB=~/.local/share/blackboxd/events.db ./blackboxd-api
# → http://localhost:9099
```

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| GET | `/api/events` | Query events (`?since=`, `?until=`, `?limit=`) |
| GET | `/api/events/latest` | Most recent events (`?n=50`) |
| GET | `/api/stats` | Total event count and date range |
| POST | `/api/refresh` | Called by the Lua listener on workspace events |
| GET | `/api/health` | Health check |

Environment variables: `BLACKBOXD_DB` (db path), `BLACKBOXD_PORT` (default `9099`).

### Rust exporter (`rust-exporter/`)

Exports the event database to JSON or CSV. Useful for backups, analysis in other tools, or piping into `jq`.

```bash
# Export everything to JSON
blackboxd-export --format json --output activity.json

# Export a time range to CSV
blackboxd-export --format csv --since 1700000000 --until 1700086400 --output week.csv

# Pipe to jq
blackboxd-export --format json | jq '[.[] | select(.kind == "window_focus")]'
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--format` | `json` | `json` or `csv` |
| `--output` | stdout | Output file path |
| `--since` | — | Unix timestamp lower bound |
| `--until` | — | Unix timestamp upper bound |
| `--db` | `~/.local/share/blackboxd/events.db` | Database path (also `BLACKBOXD_DB` env) |

### Lua listener (`listener/`)

Connects to Hyprland's `socket2` IPC and forwards workspace events to the Go API. Run alongside the daemon when using Hyprland.

```bash
lua listener/blackboxD-listener.lua
```

Environment variables: `BLACKBOXD_HOST` (default `127.0.0.1`), `BLACKBOXD_PORT` (default `9099`), `BLACKBOXD_DEBUG=1` for verbose logging.

Requires `luasocket`: `luarocks install luasocket`.

## Running Tests

```bash
python -m pytest test/
# with coverage:
pytest --cov=blackboxd test/
```

## License

MIT — see [LICENSE](LICENSE).
