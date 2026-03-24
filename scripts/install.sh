#!/bin/bash
set -e

# Clanker Installation Script
# Usage: curl -fsSL https://raw.githubusercontent.com/USER/clanker/main/scripts/install.sh | bash

REPO="USER/clanker"  # Update with actual repo
INSTALL_DIR="${CLANKER_INSTALL_DIR:-$HOME/.local/bin}"
BINARY_NAME="clanker"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Detect OS
detect_os() {
    case "$(uname -s)" in
        Linux*)  echo "linux" ;;
        Darwin*) echo "darwin" ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *) error "Unsupported operating system: $(uname -s)" ;;
    esac
}

# Detect architecture
detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64) echo "amd64" ;;
        arm64|aarch64) echo "arm64" ;;
        *) error "Unsupported architecture: $(uname -m)" ;;
    esac
}

# Get latest release version
get_latest_version() {
    curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" |
        grep '"tag_name":' |
        sed -E 's/.*"([^"]+)".*/\1/'
}

# Main installation
main() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║       CLANKER INSTALLATION            ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════╝${NC}"
    echo ""

    # Detect platform
    OS=$(detect_os)
    ARCH=$(detect_arch)
    info "Detected platform: ${OS}-${ARCH}"

    # Get latest version
    info "Fetching latest release..."
    VERSION=$(get_latest_version)
    if [ -z "$VERSION" ]; then
        error "Could not determine latest version. Check your internet connection."
    fi
    info "Latest version: ${VERSION}"

    # Construct download URL based on OS
    case "$OS" in
        linux)
            FILENAME="clanker-linux-${ARCH}.tar.gz"
            ;;
        darwin)
            FILENAME="clanker-darwin-${ARCH}.tar.gz"
            ;;
        windows)
            FILENAME="clanker-windows-amd64.zip"
            BINARY_NAME="clanker.exe"
            ;;
    esac

    DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${FILENAME}"
    info "Downloading from: ${DOWNLOAD_URL}"

    # Create install directory and temp directory
    mkdir -p "$INSTALL_DIR"
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT

    # Download archive
    ARCHIVE_PATH="${TEMP_DIR}/${FILENAME}"
    if ! curl -fsSL "$DOWNLOAD_URL" -o "$ARCHIVE_PATH"; then
        error "Failed to download. URL: ${DOWNLOAD_URL}"
    fi

    # Extract and install
    case "$OS" in
        linux|darwin)
            tar -xzf "$ARCHIVE_PATH" -C "$TEMP_DIR"
            mv "${TEMP_DIR}/clanker" "${INSTALL_DIR}/${BINARY_NAME}"
            ;;
        windows)
            unzip -q "$ARCHIVE_PATH" -d "$TEMP_DIR"
            mv "${TEMP_DIR}/clanker.exe" "${INSTALL_DIR}/${BINARY_NAME}"
            ;;
    esac

    chmod +x "${INSTALL_DIR}/${BINARY_NAME}"
    success "Installed to ${INSTALL_DIR}/${BINARY_NAME}"

    # Check if install dir is in PATH
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        warn "${INSTALL_DIR} is not in your PATH"
        echo ""
        echo "Add it to your shell config:"
        echo ""

        SHELL_NAME=$(basename "$SHELL")
        case "$SHELL_NAME" in
            zsh)
                echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
                echo "  source ~/.zshrc"
                ;;
            bash)
                echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
                echo "  source ~/.bashrc"
                ;;
            fish)
                echo "  fish_add_path ~/.local/bin"
                ;;
            *)
                echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
                ;;
        esac
        echo ""
    fi

    # Verify installation
    if command -v clanker &> /dev/null || [ -x "${INSTALL_DIR}/${BINARY_NAME}" ]; then
        success "Installation complete!"
        echo ""
        echo -e "${GREEN}Run 'clanker' to get started.${NC}"
        echo ""
    else
        warn "Binary installed but may not be in PATH yet."
    fi
}

main "$@"
