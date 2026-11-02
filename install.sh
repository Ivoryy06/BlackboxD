#!/usr/bin/env bash
# install.sh — install blackboxd from the checkout this script lives in.

set -euo pipefail

APP_NAME="blackboxd"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_NAME"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
REPO_URL="https://github.com/Ivoryy06/BlackboxD"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[info]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[warn]${NC} $1"; }
log_error() { echo -e "${RED}[error]${NC} $1" >&2; }

check_dependencies() {
    local missing=()
    for cmd in python3 git; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if (( ${#missing[@]} > 0 )); then
        log_error "missing: ${missing[*]}"
        exit 1
    fi
    python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit("blackboxd needs Python 3.11 or newer")
PY
}

install_blackboxd() {
    log_info "installing from $SCRIPT_DIR"
    mkdir -p "$CONFIG_DIR" "$SYSTEMD_DIR"

    python3 -m pip install --user -e "$SCRIPT_DIR"
    mkdir -p "$BIN_DIR"

    if command -v go &>/dev/null; then
        log_info "building the Go API"
        (cd "$SCRIPT_DIR/go-api" && go build -o "$BIN_DIR/blackboxd-api" .)
    else
        log_warn "go not found — skipping the API (the Python dashboard still works)"
    fi

    if [[ -f "$SCRIPT_DIR/listener/blackboxD-listener.lua" ]]; then
        cp "$SCRIPT_DIR/listener/blackboxD-listener.lua" "$BIN_DIR/"
    fi

    local daemon_cmd
    daemon_cmd="$(command -v blackboxd || echo 'python3 -m blackboxd.daemon')"

    cat > "$SYSTEMD_DIR/$APP_NAME.service" <<EOF
[Unit]
Description=blackboxd activity recorder
Documentation=$REPO_URL
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=$daemon_cmd
Restart=on-failure
RestartSec=3
Environment=XDG_RUNTIME_DIR=%t

[Install]
WantedBy=graphical-session.target
EOF

    systemctl --user daemon-reload
    log_info "installed. start it with:"
    echo "    systemctl --user enable --now $APP_NAME"
    echo "    blackboxd-report serve        # open the dashboard"
    echo "    blackboxd-api                 # optional Go API on :8080"
}

uninstall_blackboxd() {
    log_info "removing the service and shortcuts"
    systemctl --user disable --now "$APP_NAME.service" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/$APP_NAME.service" \
          "$BIN_DIR/$APP_NAME" \
          "$BIN_DIR/blackboxd-api" \
          "$BIN_DIR/blackboxD-listener.lua"
    systemctl --user daemon-reload
    log_info "removed. the source folder and your events.db were left alone."
}

print_usage() {
    cat <<EOF
blackboxd installer

Usage: $0 [command]

  install     install the Python daemon, Go API and user service (default)
  uninstall   remove the service and installed binaries
  help        show this message
EOF
}

main() {
    case "${1:-install}" in
        install|update)
            check_dependencies
            install_blackboxd
            ;;
        uninstall) uninstall_blackboxd ;;
        help|--help|-h) print_usage ;;
        *) log_error "unknown command: $1"; print_usage; exit 1 ;;
    esac
}

main "$@"
