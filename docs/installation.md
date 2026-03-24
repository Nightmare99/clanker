# Installation

## Pre-built Binaries (Recommended)

Download the latest binary for your platform from [GitHub Releases](https://github.com/yourusername/clanker/releases).

### Linux

```bash
# Download
curl -LO https://github.com/yourusername/clanker/releases/latest/download/clanker-linux-amd64.tar.gz

# Extract
tar -xzf clanker-linux-amd64.tar.gz

# Install (optional)
sudo mv clanker /usr/local/bin/

# Or add to your PATH
chmod +x clanker
./clanker --version
```

### macOS

```bash
# Intel Mac
curl -LO https://github.com/yourusername/clanker/releases/latest/download/clanker-darwin-amd64.tar.gz
tar -xzf clanker-darwin-amd64.tar.gz

# Apple Silicon (M1/M2/M3)
curl -LO https://github.com/yourusername/clanker/releases/latest/download/clanker-darwin-arm64.tar.gz
tar -xzf clanker-darwin-arm64.tar.gz

# Install
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
# Clone the repository
git clone https://github.com/yourusername/clanker.git
cd clanker

# Install in development mode
pip install -e ".[dev]"

# Run
clanker --version
```

## Building Binaries Locally

If you want to build your own binary:

```bash
# Install build dependencies
pip install -e ".[dev]"

# Run the build script
./scripts/build.sh

# The binary will be in dist/clanker
./dist/clanker --version
```

## Configuration

After installation, run `clanker` to start the setup wizard, or create a configuration manually:

1. Set your API key:
   ```bash
   export ANTHROPIC_API_KEY=your-key
   # or
   export AZURE_OPENAI_API_KEY=your-key
   ```

2. Run `clanker config` to open the web-based configuration UI

See [Configuration](configuration.md) for detailed setup options.
