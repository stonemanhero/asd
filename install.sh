#!/usr/bin/env bash
# ==============================================================================
# Asd — One-Click Automated Installer for Ubuntu Linux
# ==============================================================================

set -eo pipefail

# Ensure script is executed as standard desktop user, not via sudo
if [ "$EUID" -eq 0 ] && [ -n "$SUDO_USER" ]; then
    echo -e "\033[0;31m\033[1mError: Please do not run install.sh with sudo.\033[0m"
    echo -e "Run as your standard desktop user: \033[0;36m./install.sh\033[0m"
    echo -e "The installer will invoke sudo automatically only when installing system apt packages."
    exit 1
fi

# ANSI Color Codes
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/asd/app"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

echo -e "${CYAN}${BOLD}"
echo "============================================================"
echo "            Asd Encrypted Desktop Note Maker                "
echo "              One-Click Automated Installer                 "
echo "============================================================"
echo -e "${RESET}"

# 1. System & Dependency Check
echo -e "${BLUE}[1/6] Checking system dependencies...${RESET}"

REQUIRED_PKGS=("python3" "python3-gi" "gir1.2-gtk-4.0" "gir1.2-adw-1" "python3-cryptography")
MISSING_REQUIRED=()
for pkg in "${REQUIRED_PKGS[@]}"; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING_REQUIRED+=("$pkg")
    fi
done

if [ ${#MISSING_REQUIRED[@]} -gt 0 ]; then
    echo -e "${YELLOW}Installing required packages via apt: ${MISSING_REQUIRED[*]}${RESET}"
    if [ "$EUID" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then
            sudo apt-get update -y
            sudo apt-get install -y "${MISSING_REQUIRED[@]}"
        else
            echo -e "${RED}Error: sudo is required to install system packages: ${MISSING_REQUIRED[*]}${RESET}"
            exit 1
        fi
    else
        apt-get update -y
        apt-get install -y "${MISSING_REQUIRED[@]}"
    fi
else
    echo -e "${GREEN}✓ All core system dependencies are satisfied.${RESET}"
fi

# Check system tray backend (native C library or typelib)
TRAY_AVAILABLE=false
if ldconfig -p | grep -q "libayatana-appindicator3.so" || dpkg -s libayatana-appindicator3-1 >/dev/null 2>&1 || dpkg -s gir1.2-ayatanaappindicator3-0.1 >/dev/null 2>&1; then
    TRAY_AVAILABLE=true
fi

if [ "$TRAY_AVAILABLE" = true ]; then
    echo -e "${GREEN}✓ System tray indicator backend available (native AyatanaAppIndicator).${RESET}"
else
    echo -e "${CYAN}Notice: System tray library not found.${RESET}"
    if command -v sudo >/dev/null 2>&1; then
        echo -e "${YELLOW}Would you like to install optional system tray support (gir1.2-ayatanaappindicator3-0.1)? [Y/n]${RESET}"
        read -r -p "" response
        if [[ "$response" =~ ^([yY][eE][sS]|[yY]|"")$ ]]; then
            sudo apt-get install -y gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 || true
        fi
    fi
fi

# 2. Install Application Files
echo -e "${BLUE}[2/6] Installing application files to ${INSTALL_DIR}...${RESET}"
mkdir -p "${INSTALL_DIR}"
mkdir -p "$HOME/.local/share/asd"
chmod 700 "$HOME/.local/share/asd" 2>/dev/null || true
if compgen -G "$HOME/.local/share/asd/notes.db*" > /dev/null; then
    chmod 600 "$HOME/.local/share/asd/notes.db"* 2>/dev/null || true
fi

cp "${SOURCE_DIR}/crypto.py" "${INSTALL_DIR}/"
cp "${SOURCE_DIR}/database.py" "${INSTALL_DIR}/"
cp "${SOURCE_DIR}/ui.py" "${INSTALL_DIR}/"
cp "${SOURCE_DIR}/tray.py" "${INSTALL_DIR}/"
cp "${SOURCE_DIR}/main.py" "${INSTALL_DIR}/"
cp "${SOURCE_DIR}/asd.svg" "${INSTALL_DIR}/"
cp -r "${SOURCE_DIR}/resources" "${INSTALL_DIR}/"
cp -r "${SOURCE_DIR}/icons" "${INSTALL_DIR}/"

chmod +x "${INSTALL_DIR}/main.py"
chmod +x "${INSTALL_DIR}/tray.py"


echo -e "${GREEN}✓ Application files installed successfully.${RESET}"

# 3. Create Global CLI Launcher
echo -e "${BLUE}[3/6] Setting up command-line launcher (asd)...${RESET}"
mkdir -p "${BIN_DIR}"

cat << 'EOF' > "${BIN_DIR}/asd"
#!/usr/bin/env bash
token="${XDG_ACTIVATION_TOKEN:-$DESKTOP_STARTUP_ID}"
if [ -n "$token" ]; then
    exec python3 "$HOME/.local/share/asd/app/main.py" "--token=$token" "$@"
else
    exec python3 "$HOME/.local/share/asd/app/main.py" "$@"
fi
EOF
chmod +x "${BIN_DIR}/asd"


# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    if ! grep -q 'PATH="$HOME/.local/bin:$PATH"' "$HOME/.bashrc" 2>/dev/null; then
        echo -e '\n# User local binaries\nexport PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    fi
    echo -e "${YELLOW}Note: Added ~/.local/bin to ~/.bashrc for future terminal sessions.${RESET}"
fi

echo -e "${GREEN}✓ Launcher created at ${BIN_DIR}/asd${RESET}"

# 4. Install App Icon
echo -e "${BLUE}[4/6] Installing application icon...${RESET}"
mkdir -p "${ICON_DIR}"
cp "${SOURCE_DIR}/asd.svg" "${ICON_DIR}/asd.svg"
cp "${SOURCE_DIR}/asd.svg" "${ICON_DIR}/org.ubuntu.Asd.svg"

# Copy all resolution PNG icons to ~/.local/share/icons/hicolor
if [ -d "${SOURCE_DIR}/resources/hicolor" ]; then
    cp -r "${SOURCE_DIR}/resources/hicolor/"* "$HOME/.local/share/icons/hicolor/"
fi

# Ensure org.ubuntu.Asd PNGs exist across all resolutions for Wayland dock matching
for size in 16x16 22x22 24x24 32x32 48x48 64x64 128x128 256x256 512x512; do
    if [ -f "$HOME/.local/share/icons/hicolor/${size}/apps/asd.png" ]; then
        cp "$HOME/.local/share/icons/hicolor/${size}/apps/asd.png" "$HOME/.local/share/icons/hicolor/${size}/apps/org.ubuntu.Asd.png"
    fi
done

# Also install to ~/.local/share/pixmaps
mkdir -p "$HOME/.local/share/pixmaps"
cp "$HOME/.local/share/icons/hicolor/256x256/apps/asd.png" "$HOME/.local/share/pixmaps/asd.png" 2>/dev/null || true
cp "$HOME/.local/share/icons/hicolor/256x256/apps/asd.png" "$HOME/.local/share/pixmaps/org.ubuntu.Asd.png" 2>/dev/null || true

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi
echo -e "${GREEN}✓ App icon installed.${RESET}"

# 5. Create Desktop Entry & Register GNOME Shortcut
echo -e "${BLUE}[5/6] Creating desktop entry and registering shortcuts...${RESET}"
mkdir -p "${DESKTOP_DIR}"

cat << EOF > "${DESKTOP_DIR}/asd.desktop"
[Desktop Entry]
Name=Asd
GenericName=Encrypted Note Maker
Comment=Fast, secure, encrypted desktop notes
Exec=python3 $INSTALL_DIR/main.py %U
Icon=asd
Terminal=false
Type=Application
Categories=Utility;TextEditor;GTK;
StartupWMClass=org.ubuntu.Asd
StartupNotify=true
Keywords=notes;encrypted;security;crypto;asd;
EOF

chmod +x "${DESKTOP_DIR}/asd.desktop"

# Keep org.ubuntu.Asd.desktop for native Wayland compositor dock matching
cp "${DESKTOP_DIR}/asd.desktop" "${DESKTOP_DIR}/org.ubuntu.Asd.desktop"
chmod +x "${DESKTOP_DIR}/org.ubuntu.Asd.desktop"


if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
fi

# Configure Global Shortcut (Ctrl+Shift+J) across Ubuntu Flavors (GNOME, Cinnamon, MATE, XFCE, KDE)
SHORTCUT_REGISTERED=false

# 1. GNOME / Unity / Budgie
if command -v gsettings >/dev/null 2>&1; then
    python3 - << 'PYEOF' 2>/dev/null || true
import subprocess, os
try:
    media_keys = "org.gnome.settings-daemon.plugins.media-keys"
    schema_id = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    binding_path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom-asd/"
    res = subprocess.run(["gsettings", "get", media_keys, "custom-keybindings"], capture_output=True, text=True)
    if res.returncode == 0:
        subprocess.run(["gsettings", "set", f"{schema_id}:{binding_path}", "name", "Asd Toggle"], check=True)
        subprocess.run(["gsettings", "set", f"{schema_id}:{binding_path}", "command", f"{os.path.expanduser('~/.local/bin/asd')}"], check=True)
        subprocess.run(["gsettings", "set", f"{schema_id}:{binding_path}", "binding", "<Primary><Shift>j"], check=True)
        current = res.stdout.strip()
        if binding_path not in current:
            new_val = f"['{binding_path}']" if current in ("@as []", "[]", "") else current[:-1] + f", '{binding_path}']"
            subprocess.run(["gsettings", "set", media_keys, "custom-keybindings", new_val], check=True)
except Exception:
    pass
PYEOF
    SHORTCUT_REGISTERED=true
fi

# 2. XFCE (Xubuntu)
if command -v xfconf-query >/dev/null 2>&1; then
    xfconf-query -c xfce4-keyboard-shortcuts -p "/commands/custom/<Primary><Shift>j" -n -t string -s "$HOME/.local/bin/asd" 2>/dev/null || true
    SHORTCUT_REGISTERED=true
fi

# 3. Cinnamon (Ubuntu Cinnamon)
if command -v gsettings >/dev/null 2>&1; then
    python3 - << 'PYEOF' 2>/dev/null || true
import subprocess, os
try:
    schema = "org.cinnamon.desktop.keybindings"
    res = subprocess.run(["gsettings", "get", schema, "custom-list"], capture_output=True, text=True)
    if res.returncode == 0:
        custom_id = "custom-asd"
        binding_path = f"/org/cinnamon/desktop/keybindings/custom-keybindings/{custom_id}/"
        sub_schema = f"{schema}.custom-keybinding:{binding_path}"
        subprocess.run(["gsettings", "set", sub_schema, "name", "Asd Toggle"], check=True)
        subprocess.run(["gsettings", "set", sub_schema, "command", f"{os.path.expanduser('~/.local/bin/asd')}"], check=True)
        subprocess.run(["gsettings", "set", sub_schema, "binding", "['<Primary><Shift>j']"], check=True)
        current = res.stdout.strip()
        if custom_id not in current:
            new_val = f"['{custom_id}']" if current in ("@as []", "[]", "") else current[:-1] + f", '{custom_id}']"
            subprocess.run(["gsettings", "set", schema, "custom-list", new_val], check=True)
except Exception:
    pass
PYEOF
fi

# 4. MATE (Ubuntu MATE)
if command -v gsettings >/dev/null 2>&1; then
    python3 - << 'PYEOF' 2>/dev/null || true
import subprocess, os
try:
    media_keys = "org.mate.SettingsDaemon.plugins.media-keys"
    schema_id = "org.mate.SettingsDaemon.plugins.media-keys.custom-keybinding"
    binding_path = "/org/mate/settings-daemon/plugins/media-keys/custom-keybindings/custom-asd/"
    res = subprocess.run(["gsettings", "get", media_keys, "custom-keybindings"], capture_output=True, text=True)
    if res.returncode == 0:
        subprocess.run(["gsettings", "set", f"{schema_id}:{binding_path}", "name", "Asd Toggle"], check=True)
        subprocess.run(["gsettings", "set", f"{schema_id}:{binding_path}", "command", f"{os.path.expanduser('~/.local/bin/asd')}"], check=True)
        subprocess.run(["gsettings", "set", f"{schema_id}:{binding_path}", "binding", "<Primary><Shift>j"], check=True)
        current = res.stdout.strip()
        if binding_path not in current:
            new_val = f"['{binding_path}']" if current in ("@as []", "[]", "") else current[:-1] + f", '{binding_path}']"
            subprocess.run(["gsettings", "set", media_keys, "custom-keybindings", new_val], check=True)
except Exception:
    pass
PYEOF
fi

# 5. KDE Plasma (Kubuntu)
if command -v kwriteconfig5 >/dev/null 2>&1; then
    kwriteconfig5 --file kglobalshortcutsrc --group "services" --group "asd.desktop" --key "_launch" "Ctrl+Shift+J,none,Asd" 2>/dev/null || true
    SHORTCUT_REGISTERED=true
elif command -v kwriteconfig6 >/dev/null 2>&1; then
    kwriteconfig6 --file kglobalshortcutsrc --group "services" --group "asd.desktop" --key "_launch" "Ctrl+Shift+J,none,Asd" 2>/dev/null || true
    SHORTCUT_REGISTERED=true
fi

if [ "$SHORTCUT_REGISTERED" = true ]; then
    echo -e "${GREEN}✓ Global shortcut registered: ${BOLD}Ctrl+Shift+J${RESET}"
fi

echo -e "${GREEN}✓ Desktop launcher registered in GNOME Dash.${RESET}"

# 6. Launch Application
echo -e "${BLUE}[6/6] Launching Asd...${RESET}"
if command -v gtk-launch >/dev/null 2>&1; then
    gtk-launch asd >/dev/null 2>&1 &
elif command -v setsid >/dev/null 2>&1; then
    setsid python3 "${INSTALL_DIR}/main.py" --show >/dev/null 2>&1 &
else
    nohup python3 "${INSTALL_DIR}/main.py" --show >/dev/null 2>&1 &
fi
disown

echo ""
echo -e "${GREEN}${BOLD}============================================================${RESET}"
echo -e "${GREEN}${BOLD}             Asd is now installed and running!              ${RESET}"
echo -e "${GREEN}${BOLD}============================================================${RESET}"
echo -e "• ${BOLD}Global Shortcut:${RESET} Press ${CYAN}Ctrl+Shift+J${RESET} to open or toggle the vault."
echo -e "• ${BOLD}In-App Shortcuts:${RESET} ${CYAN}Ctrl+N${RESET} (New Note), ${CYAN}Ctrl+F${RESET} (Search), ${CYAN}Ctrl+L${RESET} (Lock), ${CYAN}Escape${RESET} (Minimize to Tray)."
echo -e "• ${BOLD}Backup & Restore:${RESET} Use Header Menu (${CYAN}≡${RESET}) -> 'Export/Import Encrypted Vault (.asd)'."
echo -e "• ${BOLD}Terminal Command:${RESET} Run ${CYAN}asd${RESET} or ${CYAN}asd --quit${RESET} to manage the background daemon."
echo ""
