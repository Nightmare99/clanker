#!/bin/bash
set -e

# Clanker Uninstall Script

INSTALL_DIR="${CLANKER_INSTALL_DIR:-$HOME/.local/bin}"
CONFIG_DIR="$HOME/.clanker"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${YELLOW}Clanker Uninstaller${NC}"
echo ""

# Remove binary
if [ -f "${INSTALL_DIR}/clanker" ]; then
    rm -f "${INSTALL_DIR}/clanker"
    echo -e "${GREEN}[OK]${NC} Removed ${INSTALL_DIR}/clanker"
elif [ -f "${INSTALL_DIR}/clanker.exe" ]; then
    rm -f "${INSTALL_DIR}/clanker.exe"
    echo -e "${GREEN}[OK]${NC} Removed ${INSTALL_DIR}/clanker.exe"
else
    echo -e "${YELLOW}[WARN]${NC} Binary not found in ${INSTALL_DIR}"
fi

# Ask about config
if [ -d "$CONFIG_DIR" ]; then
    echo ""
    read -p "Remove configuration directory ($CONFIG_DIR)? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$CONFIG_DIR"
        echo -e "${GREEN}[OK]${NC} Removed $CONFIG_DIR"
    else
        echo -e "${YELLOW}[SKIP]${NC} Kept $CONFIG_DIR"
    fi
fi

echo ""
echo -e "${GREEN}Clanker has been uninstalled.${NC}"
echo ""
