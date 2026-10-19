# Asd

A complete, modular, production-ready encrypted desktop Note Maker application for **Ubuntu Linux** built with **Python 3**, **GTK4**, **Libadwaita (`Adw`)**, **SQLite3**, and **`cryptography`**.

Designed for speed, modern GNOME aesthetics, and zero-compromise privacy.

---

## 1. Quick One-Click Installation

To install Asd on any Ubuntu laptop or desktop:

```bash
cd /home/stone/Projects/asd
./install.sh
```

### What `install.sh` automatically does:
1. **Checks & installs system dependencies** via `apt` (`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `python3-cryptography`; system tray binds directly to native `libayatana-appindicator3`).
2. **Deploys application files** cleanly to `~/.local/share/asd/app/`.
3. **Creates the global terminal command** `asd` in `~/.local/bin/`.
4. **Installs the custom application icon** into `~/.local/share/icons/hicolor/scalable/apps/asd.svg`.
5. **Registers the `.desktop` launcher** so Asd appears in the GNOME Dash & Application Grid.
6. **Configures the global shortcut** (`Ctrl+Shift+J`) in GNOME Settings via `gsettings`.
7. **Launches the application immediately** on your screen.

---

## 2. Features

- **End-to-End Local Encryption & Hardened Storage:**
  - Master password key derivation using **PBKDF2-HMAC-SHA256** with **480,000 iterations** and a 16-byte cryptographically secure random salt.
  - Enforced **8-character minimum** master password policy to protect against offline GPU brute-force attacks.
  - Transparent authenticated symmetric encryption using **Fernet (AES-128-CBC + HMAC-SHA256)** with a 256-bit derived key for note titles, contents, and export files before SQLite disk persistence.
  - Constant-time verification token check (`secrets.compare_digest`) without storing the master password or plain hash.
  - **Strict POSIX File Permission Sandboxing:** Storage directory (`~/.local/share/asd/`) is restricted to `0700` (`rwx------`) and database/WAL files to `0600` (`rw-------`), blocking unauthorized access from other local users.
  - **Cryptographic Secure Delete:** SQLite `PRAGMA secure_delete = ON` actively overwrites deleted notes and pages with zeroes on disk to prevent residual file carving.
  - **Bounded Backup Imports:** Enforces a 50 MB safety threshold on imported `.asd` files to prevent memory exhaustion and DoS.
- **Borderless Compact Auth Card (Locked & Initial Setup):**
  - When Asd is locked or during initial master password setup, the window displays solely as a sleek, compact, borderless card without the top header bar or oversized margins.
  - Features draggable repositioning across your screen via native window handles and a subtle corner close button (<kbd>Esc</kbd>) to minimize directly to tray.
  - Seamlessly and dynamically expands to the full two-pane workspace upon unlocking.
- **Top Header Tray Icon & Smooth Minimize-to-Tray (Slack/Hubstaff-style):**
  - **Clicking `X` (Close) or pressing `Escape`** minimizes Asd directly to the top panel tray icon **without requiring your password when reopened**, allowing you to seamlessly continue typing where you left off.
  - **Centered On Restore:** Whenever Asd is brought back from the top panel tray or via <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>J</kbd>, the window is cleanly centered on your active display.
  - **Explicit Locking:** When you want to lock your notes and wipe encryption keys from RAM, click the **Lock Vault** button in the header bar, press <kbd>Ctrl</kbd>+<kbd>L</kbd>, select **"Lock Vault"** from the top header tray menu, or run `asd --lock`.
  - **Quitting & Shutdown:** Select **"Quit Asd"** from the top header tray icon menu, choose **"Exit"** from the header dropdown menu (`≡`), or run `asd --quit` from terminal to completely terminate the application, memory encryption keys, and background daemon.
- **Instant Background Daemon (~2ms Launch):**
  - Single-instance `Adw.Application` running a background daemon via `Gio.Application.hold()`.
  - When invoked from the top header tray icon or global keyboard shortcut (`Ctrl+Shift+J`), the window activates instantaneously.
- **Pure Encrypted Binary Backup Format (`.asd`):**
  - **Zero Plaintext & No JSON Columns:** Backups are exported as raw binary `.asd` files (`asd_backup_YYYY-MM-DD.asd`). If opened in any text editor, there are **no JSON columns, no keys, and no plain text** — only raw encrypted ciphertext bytes.
  - **Cross-Vault Restore:** Automatically decrypts backups created with the same vault password, or challenges you for the master password used to create the backup, seamlessly re-encrypting the notes into your active vault.
  - Instant in-app feedback via native Libadwaita floating toasts (`Adw.Toast`).
- **Unified Focus Styling:**
  - Both Title entry and Content text box share matching rounded borders, subtle backgrounds, and accent focus rings on `:focus-within`.
- **System Tray Integration:**
  - Uses `AyatanaAppIndicator3` in an isolated GTK3 subprocess (`tray.py`) with automatic fallback to direct `ctypes` native C loading (`libayatana-appindicator3.so.1` / `libappindicator3.so.1`) and `Gtk.StatusIcon`, guaranteeing compatibility on Ubuntu systems without extra package installations.
- **Two-Pane Libadwaita Interface:**
  - **Left Pane:** Real-time smart tokenized search entry (`Ctrl+F`), scrollable note list with 1-line preview snippets showing only the first row of note content under the title, and note count footer. **Search entry is focused by default** upon opening, allowing instant filtering.
- **Smart Multi-Term Tokenized Search & Relevance Ranking:**
  - **Out-of-Order Multi-Word Search:** Searching `milos aweb` instantly matches notes titled `awebdigital milos email` or notes where words appear in different positions.
  - **Cross-Field Matching:** Terms are evaluated across both title and content simultaneously (e.g. searching `email login` matches when `email` is in the title and `login` is in the body).
  - **Weighted Relevance Scoring:** Automatically prioritizes results with exact full query matches (+1000 for title, +500 for content), all tokens in title (+300), title prefix matches (+150), and token frequency, falling back to chronological recency.
  - **Right Pane:** Modern editor with title entry, word-wrapped text editor with focus ring, dynamic auto-save status indicator (displays 'Saved' when data is saved for 2s, then disappears), per-row copy buttons (`edit-copy-symbolic`) aligned with each line of content for instant one-click copying of individual credentials/snippets, and confirmation-guarded trash can button (`user-trash-symbolic`) for note deletion.
  - **HeaderBar:** Quick `+ New Note`, primary menu button (`≡`) with options for Encrypted Backup/Restore (.asd), Lock Vault (`Ctrl+L`), About Asd, and **Exit** (completely shut down application and background daemon), alongside the dedicated `Lock Vault` quick action button.
- **Simple All-in-One About Dialog:**
  - Accessible via primary menu (`≡`), tray icon menu, or `asd --about`.
  - All information is visible immediately on a single clean card with no tabs or hidden subpages.
  - Displays application icon, version (`1.0.0`), description, author (**stone**), email (**stonemanhero@gmail.com**), website ([aystat.com](https://aystat.com)), license (**MIT License**), and copyright (**© 2026 stone**).

---

## 3. Project Architecture

```
.
├── install.sh     # One-click automated installer & launcher
├── uninstall.sh   # Clean uninstaller script
├── asd.svg        # High-resolution custom SVG application icon
├── crypto.py      # Master password derivation (PBKDF2HMAC) and Fernet AES engine
├── database.py    # SQLite storage manager with transparent encryption/decryption
├── ui.py          # GTK4 + Libadwaita views (Setup, Unlock, Vault, and .asd Backup)
├── tray.py        # Isolated GTK3 AyatanaAppIndicator system tray daemon
├── main.py        # Single-instance Adw.Application entry point and daemon manager
└── README.md      # Setup, deployment, and configuration guide
```

- **Database Location:** `~/.local/share/asd/notes.db`
- **Schema:**
  - `meta (key TEXT PRIMARY KEY, value BLOB NOT NULL)` — Stores `salt` and `verify_token`.
  - `notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`

---

## 4. Usage & Terminal Commands

### Run / Toggle Window
```bash
asd
# or
python3 ~/.local/share/asd/app/main.py
```

### Open & Center Window
```bash
asd --show
```

### Show About Window
```bash
asd --about
```

### Explicitly Lock Vault & Minimize to Tray
```bash
asd --lock
```

### Stop Background Daemon & Exit
```bash
asd --quit
```

### Uninstall
```bash
# Standard uninstall (preserves encrypted database)
./uninstall.sh

# Complete purge (removes app and permanently deletes encrypted database)
./uninstall.sh --purge
```

---

## 5. Keyboard Shortcuts Reference

| Shortcut | Scope | Action |
|---|---|---|
| `Ctrl+Shift+J` | System-wide Global | Open or toggle Asd vault from anywhere (centers on screen) |
| `Ctrl+N` | In-App | Create a new note and focus the title editor |
| `Ctrl+F` | In-App | Focus the search bar |
| `Ctrl+L` | In-App | Explicitly lock vault and wipe keys from RAM |
| `Escape` | In-App | Minimize to tray (preserves unlocked state) |
| `Enter` | Setup / Unlock | Submit password challenge |

---

## 6. Ubuntu Flavors & Desktop Environment Compatibility

Asd is architected to run across **all official Ubuntu flavors** and desktop environments:

| Ubuntu Flavor | Desktop Environment | App UI (GTK4 / Libadwaita) | System Tray Support | Global Shortcut (`Ctrl+Shift+J`) |
|---|---|:---:|:---:|:---:|
| **Ubuntu Desktop** | GNOME (Wayland / X11) | Native | AyatanaAppIndicator / SNI | Auto-configured via `gsettings` |
| **Kubuntu** | KDE Plasma (Wayland / X11) | Native | Native StatusNotifierItem (KDE Tray) | Auto-configured via `kwriteconfig5/6` |
| **Xubuntu** | XFCE (X11 / Wayland) | Native | StatusNotifier / Notification Area | Auto-configured via `xfconf-query` |
| **Lubuntu** | LXQt (X11 / Wayland) | Native | Status Notifier Plugin | Configurable via LXQt Global Keys |
| **Ubuntu MATE** | MATE | Native | AyatanaAppIndicator / Notification Area | Auto-configured via `gsettings` |
| **Ubuntu Budgie** | Budgie | Native | AppIndicator Applet | Auto-configured via `gsettings` |
| **Ubuntu Cinnamon** | Cinnamon | Native | AppIndicator Applet | Auto-configured via `gsettings` |
| **Ubuntu Unity** | Unity | Native | Indicator Applet | Auto-configured via `gsettings` |
| **Tiling WMs** (i3, Sway, etc.) | Custom | Native | `Gtk.StatusIcon` / AppIndicator | Bind `asd` in WM config |

### How Compatibility is Achieved:
1. **Core Runtime (`GTK4` & `Libadwaita`):** Standard Ubuntu APT packages (`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `python3-cryptography`) are in the official Ubuntu repositories across all editions. Libadwaita renders consistently regardless of the host desktop window manager.
2. **Multi-Tier Tray Daemon (`tray.py`):** Runs an isolated background process supporting `AyatanaAppIndicator3`, `AppIndicator3`, direct `ctypes` C-library loading, and `Gtk.StatusIcon` fallback.
3. **Automated Multi-Flavor Shortcut Installer:** `install.sh` automatically detects the active desktop environment (GNOME, KDE Plasma, XFCE, Cinnamon, MATE) and registers the global `Ctrl+Shift+J` hotkey to launch `asd`.
