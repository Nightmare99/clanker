#!/bin/bash
set -e

# Clanker Installation Script
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash -s -- v0.8.5
#   CLANKER_VERSION=v0.8.5 curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
#
# An optional version (e.g. "v0.8.5" or "0.8.5") installs that release instead
# of the latest one. Pass it as the first argument (note the `-s --` when
# piping through bash) or via the CLANKER_VERSION env var.

REPO="Nightmare99/clanker"
DEFAULTS_REPO="Nightmare99/clanker-defaults"
INSTALL_DIR="${CLANKER_INSTALL_DIR:-$HOME/.local/bin}"
CLANKER_HOME="${CLANKER_HOME:-$HOME/.clanker}"
DEFAULTS_STAGING_DIR="${CLANKER_HOME}/.clanker-defaults"
BINARY_NAME="clanker"
REQUESTED_VERSION="${1:-${CLANKER_VERSION:-}}"

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

release_exists() {
    local tag="$1"
    local status
    status=$(curl -sSL -o /dev/null -w "%{http_code}" "https://api.github.com/repos/${REPO}/releases/tags/${tag}" || echo "000")
    [ "$status" = "200" ]
}

sync_defaults() {
    if ! command -v git &>/dev/null; then
        warn "git not found; skipping default skills/agents sync."
        return
    fi

    rm -rf "$DEFAULTS_STAGING_DIR"
    if ! git clone --depth 1 --quiet "https://github.com/${DEFAULTS_REPO}.git" "$DEFAULTS_STAGING_DIR" 2>/dev/null; then
        warn "Could not clone ${DEFAULTS_REPO}; skipping default skills/agents sync."
        rm -rf "$DEFAULTS_STAGING_DIR"
        return
    fi

    mkdir -p "${CLANKER_HOME}/agents" "${CLANKER_HOME}/skills"
    [ -d "${DEFAULTS_STAGING_DIR}/agents" ] && cp -Rf "${DEFAULTS_STAGING_DIR}/agents/." "${CLANKER_HOME}/agents/"
    [ -d "${DEFAULTS_STAGING_DIR}/skills" ] && cp -Rf "${DEFAULTS_STAGING_DIR}/skills/." "${CLANKER_HOME}/skills/"
    rm -rf "$DEFAULTS_STAGING_DIR"
    success "Synced default skills and agents to ${BOLD}${CLANKER_HOME}${NC}"
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

    if [ -n "$REQUESTED_VERSION" ]; then
        VERSION="$REQUESTED_VERSION"
        [[ "$VERSION" != v* ]] && VERSION="v${VERSION}"
        info "Requested version: ${BOLD}${VERSION}${NC}"
        if ! release_exists "$VERSION"; then
            error "Release ${VERSION} not found. Check available releases at https://github.com/${REPO}/releases"
        fi
        PINNED=1
    else
        VERSION=$(get_latest_version)
        if [ -z "$VERSION" ]; then
            error "Could not determine latest version. Check your internet connection."
        fi
        PINNED=0
    fi

    INSTALLED_VERSION=$(get_installed_version)
    if [ -n "$INSTALLED_VERSION" ]; then
        INSTALLED_CLEAN="${INSTALLED_VERSION#v}"
        TARGET_CLEAN="${VERSION#v}"

        if [ "$INSTALLED_CLEAN" = "$TARGET_CLEAN" ]; then
            echo ""
            success "Clanker ${GREEN}${VERSION}${NC} is already installed."
            sync_defaults
            echo ""
            exit 0
        fi

        echo ""
        info "Installed: ${YELLOW}v${INSTALLED_CLEAN}${NC}"
        info "$([ "$PINNED" = 1 ] && echo "Target:   " || echo "Latest:   ") ${GREEN}${VERSION}${NC}"
        echo ""

        if [ -t 0 ]; then
            read -p "  $([ "$PINNED" = 1 ] && echo "Install this version?" || echo "Upgrade?") [Y/n] " -n 1 -r
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

    sync_defaults

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
