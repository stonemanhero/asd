#!/usr/bin/env python3
"""
main.py — Single-instance Libadwaita application entry point and background daemon for Asd.

Features:
- Single-instance via D-Bus (application_id="org.ubuntu.Asd")
- Persistent background daemon using Gio.Application hold()
- Instant window activation (~2ms)
- Background system tray indicator management
- Minimize-to-tray on close (X) and RAM wipe security lifecycle
- Command line flag handling (--show, --lock, --quit)
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, List, Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

GLib.set_prgname("org.ubuntu.Asd")
GLib.set_application_name("Asd")

from crypto import CryptoManager
from database import DatabaseManager
from ui import MainWindow

APPLICATION_ID: str = "org.ubuntu.Asd"


class AsdApplication(Adw.Application):
    """
    Main application controller managing single-instance lifecycle,
    background daemon state, and system tray subprocess for Asd.
    """

    def __init__(self) -> None:
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )
        self.crypto: Optional[CryptoManager] = None
        self.db: Optional[DatabaseManager] = None
        self.window: Optional[MainWindow] = None
        self.tray_proc: Optional[subprocess.Popen] = None
        self._is_held: bool = False

    def do_startup(self) -> None:
        """Initialize core services, hold the application loop, and spawn tray helper."""
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name("asd")

        # Hold the application loop so it runs as a persistent background daemon
        self.hold()
        self._is_held = True

        # Initialize crypto and database engines
        self.crypto = CryptoManager()
        self.db = DatabaseManager(crypto=self.crypto)

        # Launch the standalone tray helper subprocess
        self._launch_tray_helper()

    def _launch_tray_helper(self) -> None:
        """Start tray.py in a dedicated GTK3 subprocess."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        tray_script = os.path.join(script_dir, "tray.py")

        if os.path.isfile(tray_script):
            try:
                self.tray_proc = subprocess.Popen(
                    [sys.executable, tray_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as exc:
                print(f"[Asd] Note: Failed to spawn system tray helper ({exc})", file=sys.stderr)

    def show_window(self, token: Optional[str] = None) -> None:
        """Reveal, center, and present the application window without requiring password if already unlocked."""
        if self.window is None:
            assert self.db is not None and self.crypto is not None
            self.window = MainWindow(application=self, db=self.db, crypto=self.crypto)

        if not self.db.is_initialized():
            if not self.window.is_visible():
                self.window.show_setup_view()
        else:
            # Only prompt for password if the vault is currently locked
            if not self.crypto.is_unlocked:
                self.window.lock_vault(present=False)
            else:
                if self.window.main_stack.get_visible_child_name() != "vault":
                    self.window.show_vault_view(present=False)

        self.window.center_and_present(token=token)

    def lock_and_hide(self) -> None:
        """Wipe RAM, lock vault, and hide window to tray."""
        if self.window is not None:
            self.window.lock_vault()
            self.window.minimize_to_tray()

    def do_activate(self) -> None:
        """
        Handle application activation:
        - If window is already visible and active: toggle closed (minimize to tray)
        - If window is hidden: center and present window without requiring password if already unlocked
        """
        if self.window is None:
            self.show_window(token=token)
            return

        # If window is currently visible and focused, toggle it closed (minimize to tray)
        if self.window.is_visible() and self.window.is_active():
            self.window.minimize_to_tray()
            return

        self.show_window(token=token)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Process command-line arguments on the primary application instance."""
        args: List[str] = command_line.get_arguments()
        token: Optional[str] = None
        filtered_args: List[str] = []
        for arg in args:
            if arg.startswith("--token="):
                token = arg.split("=", 1)[1]
            else:
                filtered_args.append(arg)
        args = filtered_args

        if "--quit" in args or "-q" in args:
            self.quit_app()
            return 0

        if "--lock" in args or "-l" in args:
            self.lock_and_hide()
            return 0

        if "--show" in args or "-s" in args:
            self.show_window(token=token)
            return 0

        if "--about" in args or "-a" in args:
            self.show_window(token=token)
            if self.window is not None:
                self.window.show_about_dialog()
            return 0

        if "--help" in args or "-h" in args:
            help_text = (
                "Asd — Encrypted Desktop Note Maker for Ubuntu Linux\n\n"
                "Usage:\n"
                "  asd [OPTION...]\n"
                "  python3 main.py [OPTION...]\n\n"
                "Options:\n"
                "  -s, --show    Open or bring the Asd window to front\n"
                "  -l, --lock    Lock vault and minimize to tray\n"
                "  -q, --quit    Terminate the background daemon and tray helper\n"
                "  -h, --help    Show this help message and exit\n"
            )
            command_line.print_literal(help_text)
            if self.window is None or not self.window.is_visible():
                self.quit_app()
            return 0

        # Normal invocation (e.g. shortcut Ctrl+Shift+J): toggle behavior
        if self.window is not None and self.window.is_visible() and self.window.is_active():
            self.window.minimize_to_tray()
            return 0

        self.show_window(token=token)
        return 0

    def quit_app(self) -> None:
        """Gracefully terminate tray helper, destroy windows, and exit daemon."""
        if self.tray_proc is not None and self.tray_proc.poll() is None:
            try:
                self.tray_proc.terminate()
                self.tray_proc.wait(timeout=2)
            except Exception:
                try:
                    self.tray_proc.kill()
                except Exception:
                    pass

        if self.window is not None:
            if hasattr(self.window, "crypto"):
                self.window.crypto.lock()
            self.window.destroy()
            self.window = None

        if self.db is not None:
            self.db.close()

        if self._is_held:
            self._is_held = False
            self.release()

        self.quit()

    def do_shutdown(self) -> None:
        """Final cleanup before process termination."""
        if self.tray_proc is not None and self.tray_proc.poll() is None:
            try:
                self.tray_proc.terminate()
            except Exception:
                pass

        if self.db is not None:
            self.db.close()

        Adw.Application.do_shutdown(self)


def main() -> int:
    """Application entry point."""
    token = os.environ.get("XDG_ACTIVATION_TOKEN") or os.environ.get("DESKTOP_STARTUP_ID")
    if token and not any(arg.startswith("--token=") for arg in sys.argv):
        sys.argv.append(f"--token={token}")
    app = AsdApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
