#!/bin/bash
set -e

# Clanker Installation Script
# Usage: curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash

REPO="Nightmare99/clanker"
INSTALL_DIR="${CLANKER_INSTALL_DIR:-$HOME/.local/bin}"
BINARY_NAME="clanker"

# Colors
BOLD='\033[1m'
DIM='\033[2m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "  ${CYAN}▸${NC} $1"; }
success() { echo -e "  ${GREEN}✓${NC} $1"; }
warn()    { echo -e "  ${YELLOW}!${NC} $1"; }
error()   { echo -e "  ${RED}✗${NC} $1"; exit 1; }

detect_os() {
    case "$(uname -s)" in
        Linux*)  echo "linux" ;;
        Darwin*) echo "darwin" ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *) error "Unsupported operating system: $(uname -s)" ;;
    esac
}

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64) echo "amd64" ;;
        arm64|aarch64) echo "arm64" ;;
        *) error "Unsupported architecture: $(uname -m)" ;;
    esac
}

get_latest_version() {
    curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" |
        grep '"tag_name":' |
        sed -E 's/.*"([^"]+)".*/\1/'
}

get_installed_version() {
    if [ -x "${INSTALL_DIR}/clanker" ]; then
        "${INSTALL_DIR}/clanker" --version 2>&1 | grep -oE 'v?[0-9]+\.[0-9]+\.[0-9]+' | head -1
    elif command -v clanker &>/dev/null; then
        clanker --version 2>&1 | grep -oE 'v?[0-9]+\.[0-9]+\.[0-9]+' | head -1
    fi
}

main() {
    echo ""
    echo -e "  ${BOLD}${CYAN}⚙  Clanker Installer${NC}"
    echo -e "  ${DIM}─────────────────────${NC}"
    echo ""

    OS=$(detect_os)
    ARCH=$(detect_arch)
    info "Platform: ${BOLD}${OS}-${ARCH}${NC}"

    VERSION=$(get_latest_version)
    if [ -z "$VERSION" ]; then
        error "Could not determine latest version. Check your internet connection."
    fi

    INSTALLED_VERSION=$(get_installed_version)
    if [ -n "$INSTALLED_VERSION" ]; then
        INSTALLED_CLEAN="${INSTALLED_VERSION#v}"
        LATEST_CLEAN="${VERSION#v}"

        if [ "$INSTALLED_CLEAN" = "$LATEST_CLEAN" ]; then
            echo ""
            success "Clanker ${GREEN}${VERSION}${NC} is already installed and up to date!"
            echo ""
            exit 0
        fi

        echo ""
        info "Installed: ${YELLOW}v${INSTALLED_CLEAN}${NC}"
        info "Latest:    ${GREEN}${VERSION}${NC}"
        echo ""

        if [ -t 0 ]; then
            read -p "  Upgrade? [Y/n] " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Nn]$ ]]; then
                info "Cancelled."
                exit 0
            fi
        else
            info "Upgrading..."
        fi
    else
        info "Version: ${BOLD}${VERSION}${NC}"
    fi

    case "$OS" in
        linux)   FILENAME="clanker-linux-${ARCH}.tar.gz" ;;
        darwin)  FILENAME="clanker-darwin-${ARCH}.tar.gz" ;;
        windows) FILENAME="clanker-windows-amd64.zip"; BINARY_NAME="clanker.exe" ;;
    esac

    DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${FILENAME}"
    info "Downloading ${DIM}${FILENAME}${NC}..."

    mkdir -p "$INSTALL_DIR"
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT

    ARCHIVE_PATH="${TEMP_DIR}/${FILENAME}"
    if ! curl -fsSL "$DOWNLOAD_URL" -o "$ARCHIVE_PATH"; then
        error "Download failed: ${DOWNLOAD_URL}"
    fi

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
    success "Installed to ${BOLD}${INSTALL_DIR}/${BINARY_NAME}${NC}"

    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        echo ""
        warn "${INSTALL_DIR} is not in your PATH."
        echo ""
        SHELL_NAME=$(basename "$SHELL")
        case "$SHELL_NAME" in
            zsh)
                echo -e "  ${DIM}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc${NC}"
                echo -e "  ${DIM}source ~/.zshrc${NC}"
                ;;
            bash)
                echo -e "  ${DIM}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc${NC}"
                echo -e "  ${DIM}source ~/.bashrc${NC}"
                ;;
            fish)
                echo -e "  ${DIM}fish_add_path ~/.local/bin${NC}"
                ;;
            *)
                echo -e "  ${DIM}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
                ;;
        esac
    fi

    echo ""
    echo -e "  ${GREEN}${BOLD}Done!${NC} Run ${CYAN}clanker${NC} to get started."
    echo ""
}

main "$@"
