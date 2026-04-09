[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🌟 Overview

BlackboxD is a lightweight, performance-focused activity tracking system designed to monitor and record desktop activity across multiple window managers without impacting system performance. It consists of multiple components working together to provide seamless activity tracking, visualization, and export capabilities.

## ✨ Features

- **🚀 Performance-First Design** - Minimal resource usage while recording
- **🎨 Multi-WM Support** - Works with GNOME, Hyprland, and more
- **📊 Real-time Dashboard** - Visualize your activity data
- **💾 Multiple Export Formats** - Export data in JSON, CSV, and more
- **🔧 Modular Architecture** - Python daemon + Go API + Rust exporter + Lua listener
- **⚡ Fast & Efficient** - Built with performance in mind

## 🏗️ Architecture

BlackboxD consists of four main components:

1. **Python Core** (`daemon.py`, `engine.py`, etc.) - Main activity tracking daemon
2. **Go API** (`go-api/`) - HTTP server for data access
3. **Rust Exporter** (`rust-exporter/`) - High-performance data export utilities
4. **Lua Listener** (`listener/`) - Lightweight event listener
5. **Web Dashboard** - Real-time activity visualization

## 📦 Project Structure

```
BlackboxD/
├── daemon.py              # Main daemon process
├── engine.py              # Core tracking engine
├── models.py              # Data models
├── cli.py                 # Command-line interface
├── config.py              # Configuration management
├── reconstructor.py       # Activity reconstruction
├── renderer.py            # Data rendering
├── registry.py            # Component registry
├── gnome.py               # GNOME integration
├── hyprland.py            # Hyprland integration
├── dashboard.html         # Web dashboard
├── go-api/                # Go HTTP API server
├── rust-exporter/         # Rust export utilities
├── listener/              # Lua event listener
├── workspacegrid/         # Workspace visualization component
├── install.sh             # Installation script
└── test_blackboxd.py      # Test suite
```

## 🚀 Installation

### Prerequisites

- Python 3.8+
- Go 1.19+ (for API server)
- Rust 1.70+ (for exporter)
- Lua 5.4+ (for listener)

### Quick Install

```bash
# Clone the repository
git clone https://github.com/Ivoryy06/BlackboxD.git
cd BlackboxD

# Run the installation script
chmod +x install.sh
./install.sh
```

### Manual Installation

```bash
# Install Python dependencies
pip install -e .

# Build Go API server
cd go-api
go build -o blackboxd-api

# Build Rust exporter
cd rust-exporter
cargo build --release

# Start the daemon
blackboxd start
```

## 🎮 Usage

### Starting the Daemon

```bash
# Start BlackboxD daemon
blackboxd start

# Check status
blackboxd status

# Stop daemon
blackboxd stop
```

### Viewing Activity

```bash
# Open the dashboard
blackboxd dashboard

# Export data
blackboxd export --format json --output activity.json

# View live stats
blackboxd stats
```

### Configuration

Edit `~/.config/blackboxd/config.yaml` to customize:

```yaml
# Sample configuration
tracking:
  interval: 5  # seconds
  window_managers:
    - gnome
    - hyprland
export:
  formats:
    - json
    - csv
dashboard:
  port: 8080
```

## 🖥️ Supported Desktop Environments

- ✅ GNOME
- ✅ Hyprland
- 🚧 KDE Plasma (coming soon)
- 🚧 i3/Sway (coming soon)

## 📊 Dashboard

Access the web dashboard at `http://localhost:8080` after starting the daemon. The dashboard provides:

- Real-time activity monitoring
- Workspace usage visualization
- Application time tracking
- Activity timeline
- Export functionality

## 🔧 Development

### Running Tests

```bash
# Run Python tests
python -m pytest test_blackboxd.py

# Run with coverage
pytest --cov=blackboxd test_blackboxd.py
```

### Building from Source

```bash
# Python package
pip install -e .[dev]

# Go API
cd go-api && go build

# Rust exporter
cd rust-exporter && cargo build
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with performance and privacy in mind
- Inspired by the need for lightweight activity tracking
- Community contributions welcome

## 📧 Contact

- GitHub: [@Ivoryy06](https://github.com/Ivoryy06)
- Project Link: [https://github.com/Ivoryy06/BlackboxD](https://github.com/Ivoryy06/BlackboxD)

---

<p align=\"center\">Made with ❤️ by Ivyy</p>
"
Observation: Overwrite successful: /app/README.md
