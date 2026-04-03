# Installation

## One-Line Install (Recommended)

The easiest way to install Clanker:

```bash
curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
```

This script:
- Detects your OS (Linux, macOS, Windows/WSL) and architecture (amd64, arm64)
- Downloads the latest release from GitHub
- Installs to `~/.local/bin` (configurable via `CLANKER_INSTALL_DIR`)
- Prompts before upgrading if already installed

### Custom Install Location

```bash
CLANKER_INSTALL_DIR=/usr/local/bin curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
```

## Manual Download

Download from [GitHub Releases](https://github.com/Nightmare99/clanker/releases):

### Linux

```bash
curl -LO https://github.com/Nightmare99/clanker/releases/latest/download/clanker-linux-amd64.tar.gz
tar -xzf clanker-linux-amd64.tar.gz
sudo mv clanker /usr/local/bin/
```

### macOS

```bash
# Intel Mac
curl -LO https://github.com/Nightmare99/clanker/releases/latest/download/clanker-darwin-amd64.tar.gz

# Apple Silicon (M1/M2/M3)
curl -LO https://github.com/Nightmare99/clanker/releases/latest/download/clanker-darwin-arm64.tar.gz

tar -xzf clanker-darwin-*.tar.gz
sudo mv clanker /usr/local/bin/

# Note: You may need to allow the binary in System Preferences > Security & Privacy
```

### Windows

1. Download `clanker-windows-amd64.zip` from the releases page
2. Extract the zip file
3. Add the extracted folder to your PATH, or move `clanker.exe` to a directory in your PATH
4. Open a new terminal and run `clanker --version`

## From PyPI (Python users)

```bash
# Install with pip
pip install clanker

# Or with pipx (recommended for CLI tools)
pipx install clanker
```

## From Source

```bash
git clone https://github.com/Nightmare99/clanker.git
cd clanker
pip install -e ".[dev]"
clanker --version
```

## Building Binaries Locally

```bash
# Install dependencies and build
pip install -e ".[dev]"
./scripts/build.sh

# Binary will be at dist/clanker (~100MB)
./dist/clanker --version
```

## Updating

### Check for Updates

```bash
clanker --check-update
```

Clanker also shows a notification on startup if an update is available.

### Update to Latest

```bash
curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
```

The install script detects existing installations and prompts before upgrading.

## Uninstalling

```bash
curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/uninstall.sh | bash
```

Or manually:

```bash
rm ~/.local/bin/clanker
rm -rf ~/.clanker  # Remove config (optional)
```

## Optional: GitHub Copilot Support

To use GitHub Copilot mode, install the Copilot SDK:

```bash
pip install github-copilot-sdk
```

Then start with Copilot mode:
```bash
clanker --copilot
```

See [Copilot Mode](copilot.md) for details.

## Configuration

After installation, run `clanker` to start the setup wizard, or:

### BYOK Mode (Bring Your Own Key)

1. Set your API key:
   ```bash
   export ANTHROPIC_API_KEY=your-key
   # or
   export AZURE_OPENAI_API_KEY=your-key
   ```

2. Run `clanker config` to open the web-based configuration UI

See [Configuration](configuration.md) for detailed setup options.

### Copilot Mode

1. Install the SDK: `pip install github-copilot-sdk`
2. Run: `clanker --copilot`
3. Follow the GitHub authentication prompts

See [Copilot Mode](copilot.md) for details.
