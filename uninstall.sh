#!/usr/bin/env bash
# ==============================================================================
# Asd — Clean Uninstaller
# ==============================================================================

set -eo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

echo -e "${YELLOW}${BOLD}Uninstalling Asd...${RESET}"

# Stop background daemon and tray helper
if command -v asd >/dev/null 2>&1; then
    asd --quit 2>/dev/null || true
fi
pkill -f "python3.*asd/app/main.py" 2>/dev/null || true
pkill -f "python3.*asd/app/tray.py" 2>/dev/null || true

# Remove application files
rm -rf "$HOME/.local/share/asd/app"
rm -f "$HOME/.local/bin/asd"
rm -f "$HOME/.local/share/applications/asd.desktop"
rm -f "$HOME/.local/share/applications/org.ubuntu.Asd.desktop" 2>/dev/null || true
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/asd.svg"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/org.ubuntu.Asd.svg" 2>/dev/null || true

# Remove Shortcuts across Ubuntu flavors
# 1. GNOME / Unity / Budgie / MATE
if command -v gsettings >/dev/null 2>&1; then
    python3 - << 'PYEOF' 2>/dev/null || true
import subprocess, ast

for media_keys, path_prefix in [
    ("org.gnome.settings-daemon.plugins.media-keys", "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom-asd/"),
    ("org.mate.SettingsDaemon.plugins.media-keys", "/org/mate/settings-daemon/plugins/media-keys/custom-keybindings/custom-asd/")
]:
    try:
        res = subprocess.run(["gsettings", "get", media_keys, "custom-keybindings"], capture_output=True, text=True)
        if res.returncode == 0:
            current = res.stdout.strip()
            bindings = ast.literal_eval(current) if current not in ("@as []", "[]", "") else []
            if path_prefix in bindings:
                bindings.remove(path_prefix)
                subprocess.run(["gsettings", "set", media_keys, "custom-keybindings", str(bindings)], check=True)
    except Exception:
        pass

try:
    res = subprocess.run(["gsettings", "get", "org.cinnamon.desktop.keybindings", "custom-list"], capture_output=True, text=True)
    if res.returncode == 0:
        bindings = ast.literal_eval(res.stdout.strip())
        if "custom-asd" in bindings:
            bindings.remove("custom-asd")
            subprocess.run(["gsettings", "set", "org.cinnamon.desktop.keybindings", "custom-list", str(bindings)], check=True)
except Exception:
    pass
PYEOF
fi

# 2. XFCE (Xubuntu)
if command -v xfconf-query >/dev/null 2>&1; then
    xfconf-query -c xfce4-keyboard-shortcuts -p "/commands/custom/<Primary><Shift>j" -r 2>/dev/null || true
    xfconf-query -c xfce4-keyboard-shortcuts -p "/commands/custom/<Primary><Shift>n" -r 2>/dev/null || true
fi

# 3. KDE Plasma (Kubuntu)
if command -v kwriteconfig5 >/dev/null 2>&1; then
    kwriteconfig5 --file kglobalshortcutsrc --group "services" --group "asd.desktop" --key "_launch" "" 2>/dev/null || true
elif command -v kwriteconfig6 >/dev/null 2>&1; then
    kwriteconfig6 --file kglobalshortcutsrc --group "services" --group "asd.desktop" --key "_launch" "" 2>/dev/null || true
fi

# Update desktop & icon caches
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo -e "${GREEN}✓ Asd application and shortcuts removed.${RESET}"

if [ "$1" = "--purge" ] || [ "$1" = "-p" ]; then
    rm -rf "$HOME/.local/share/asd"
    echo -e "${GREEN}✓ All application data and databases purged permanently.${RESET}"
else
    echo -e "${YELLOW}Note: Your encrypted database at ~/.local/share/asd/notes.db was preserved.${RESET}"
    echo -e "To delete it permanently, run: \033[0;36mrm -rf ~/.local/share/asd\033[0m"
    echo -e "Or run: \033[0;36m./uninstall.sh --purge\033[0m"
fi
