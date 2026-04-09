#!/usr/bin/env bash
# install.sh — BlackboxD installer with systemd user service setup

set -euo pipefail

APP_NAME="blackboxd"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_NAME"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
REPO_URL="[github.com](https://github.com/Ivoryy06/BlackboxD)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

check_dependencies() {
    local missing=()
    for cmd in go git hyprctl; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing dependencies: ${missing[*]}"
        exit 1
    fi
}

install_blackboxd() {
    log_info "Installing BlackboxD..."
    
    # Create directories
    mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$CONFIG_DIR" "$SYSTEMD_DIR"
    
    # Clone or update repository
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log_info "Updating existing installation..."
        git -C "$INSTALL_DIR" pull --ff-only
    else
        log_info "Cloning repository..."
        rm -rf "$INSTALL_DIR"
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    fi
    
    # Build Go server
    log_info "Building server..."
    (cd "$INSTALL_DIR/server" && go build -o "$BIN_DIR/$APP_NAME" .)
    
    # Build web frontend if npm/pnpm available
    if command -v pnpm &>/dev/null; then
        log_info "Building web UI with pnpm..."
        (cd "$INSTALL_DIR/web" && pnpm install && pnpm build)
    elif command -v npm &>/dev/null; then
        log_info "Building web UI with npm..."
        (cd "$INSTALL_DIR/web" && npm install && npm run build)
    else
        log_warn "npm/pnpm not found — skipping web build"
    fi
    
    # Copy Lua listener if present
    if [[ -f "$INSTALL_DIR/listener/blackboxd-listener.lua" ]]; then
        cp "$INSTALL_DIR/listener/blackboxd-listener.lua" "$BIN_DIR/"
        chmod +x "$BIN_DIR/blackboxd-listener.lua"
    fi
    
    log_info "Binary installed to $BIN_DIR/$APP_NAME"
}

setup_systemd_service() {
    log_info "Setting up systemd user service..."
    
    cat > "$SYSTEMD_DIR/$APP_NAME.service" << EOF
[Unit]
Description=BlackboxD Hyprland Dynamic Desktop
Documentation=$REPO_URL
PartOf=graphical-session.target
After=graphical-session.target
ConditionEnvironment=HYPRLAND_INSTANCE_SIGNATURE

[Service]
Type=simple
ExecStart=$BIN_DIR/$APP_NAME
Restart=on-failure
RestartSec=3
Environment=XDG_RUNTIME_DIR=%t

[Install]
WantedBy=graphical-session.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable "$APP_NAME.service"
    
    log_info "Service installed: $APP_NAME.service"
    log_info "Start with: systemctl --user start $APP_NAME"
}

uninstall_blackboxd() {
    log_info "Uninstalling BlackboxD..."
    
    systemctl --user stop "$APP_NAME.service" 2>/dev/null || true
    systemctl --user disable "$APP_NAME.service" 2>/dev/null || true
    
    rm -f "$SYSTEMD_DIR/$APP_NAME.service"
    rm -f "$BIN_DIR/$APP_NAME"
    rm -f "$BIN_DIR/blackboxd-listener.lua"
    rm -rf "$INSTALL_DIR"
    
    systemctl --user daemon-reload
    
    log_info "BlackboxD uninstalled"
}

print_usage() {
    cat << EOF
BlackboxD Installer

Usage: $0 [command]

Commands:
    install     Install BlackboxD and set up systemd service (default)
    uninstall   Remove BlackboxD and systemd service
    update      Update existing installation
    help        Show this message

EOF
}

main() {
    case "${1:-install}" in
        install|update)
            check_dependencies
            install_blackboxd
            setup_systemd_service
            log_info "Installation complete!"
            log_info "Add to Hyprland config: exec-once = systemctl --user start $APP_NAME"
            ;;
        uninstall)
            uninstall_blackboxd
            ;;
        help|--help|-h)
            print_usage
            ;;
        *)
            log_error "Unknown command: $1"
            print_usage
            exit 1
            ;;
    esac
}

main "$@"
