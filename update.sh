#!/usr/bin/env bash
# ==============================================================================
# Asd — Automated Pull & Update Script
# ==============================================================================

set -eo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SOURCE_DIR"

echo -e "${CYAN}${BOLD}"
echo "============================================================"
echo "                   Asd Vault Updater                        "
echo "============================================================"
echo -e "${RESET}"

# 1. Pull latest git changes
echo -e "${BLUE}[1/3] Pulling latest updates from Git...${RESET}"
if [ -d ".git" ]; then
    git pull
else
    echo -e "${YELLOW}Notice: Not a git repository directory; skipping git pull.${RESET}"
fi

# 2. Terminate running background instances
echo -e "${BLUE}[2/3] Stopping running background daemon and tray...${RESET}"
if command -v asd >/dev/null 2>&1; then
    asd --quit 2>/dev/null || true
fi
pkill -f "python3.*asd/app/main.py" 2>/dev/null || true
pkill -f "python3.*asd/app/tray.py" 2>/dev/null || true

# 3. Deploy updated files via installer
echo -e "${BLUE}[3/3] Deploying updated application files...${RESET}"
./install.sh

echo ""
echo -e "${GREEN}${BOLD}✓ Asd successfully updated and launched!${RESET}"
