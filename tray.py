#!/usr/bin/env python3
"""
tray.py — System tray indicator for Asd.

Runs in an isolated GTK3 subprocess to prevent symbol collisions with GTK4
in the main process. Supports both PyGObject typelib and direct ctypes loading
for libayatana-appindicator3 / libappindicator3, as well as Gtk.StatusIcon fallback.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from typing import Any, Optional


def resolve_main_py() -> str:
    """Return the absolute path to main.py."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "main.py")


def resolve_app_launcher() -> list[str]:
    """Return command list to launch or control Asd."""
    main_py = resolve_main_py()
    # Check if ~/.local/bin/asd exists
    home_bin_asd = os.path.expanduser("~/.local/bin/asd")
    if os.path.isfile(home_bin_asd) and os.access(home_bin_asd, os.X_OK):
        return [home_bin_asd]
    return [sys.executable, main_py]


def get_gobject_c_pointer(obj: Any) -> Optional[int]:
    """Extract raw C pointer from PyGObject instance using PyCapsule."""
    try:
        gpointer = getattr(obj, "__gpointer__", None)
        if gpointer is None:
            return None
        ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
        ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
        return ctypes.pythonapi.PyCapsule_GetPointer(gpointer, None)
    except Exception:
        return None


class SystemTrayService:
    """Manages the Asd system tray icon and menu across different desktop environments."""

    def __init__(self) -> None:
        self.gtk: Optional[Any] = None
        self.glib: Optional[Any] = None
        self.menu: Optional[Any] = None
        self.indicator_handle: Optional[Any] = None
        self.parent_pid: int = os.getppid()

    def initialize_gtk(self) -> bool:
        """Initialize GTK 3."""
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import GLib, Gtk
            self.gtk = Gtk
            self.glib = GLib
            return True
        except Exception as exc:
            print(f"[Asd Tray] Error initializing GTK 3: {exc}", file=sys.stderr)
            return False

    def build_menu(self) -> Any:
        """Create the context menu for the system tray indicator."""
        Gtk = self.gtk
        assert Gtk is not None

        menu = Gtk.Menu()
        launcher = resolve_app_launcher()

        # 1. Open Asd (Primary action)
        item_open = Gtk.MenuItem(label="Open Asd")
        # Bold label for primary action
        label = item_open.get_child()
        if label and hasattr(label, "set_markup"):
            label.set_markup("<b>Open Asd</b>")

        def on_open(_widget: Any) -> None:
            try:
                subprocess.Popen(launcher + ["--show"])
            except Exception as err:
                print(f"[Asd Tray] Failed to open Asd: {err}", file=sys.stderr)

        item_open.connect("activate", on_open)
        menu.append(item_open)
        self.item_open = item_open

        # 2. Lock & Hide
        item_lock = Gtk.MenuItem(label="Lock Vault")

        def on_lock(_widget: Any) -> None:
            try:
                subprocess.Popen(launcher + ["--lock"])
            except Exception as err:
                print(f"[Asd Tray] Failed to lock Asd: {err}", file=sys.stderr)

        item_lock.connect("activate", on_lock)
        menu.append(item_lock)

        menu.append(Gtk.SeparatorMenuItem())

        # 3. About Asd
        item_about = Gtk.MenuItem(label="About Asd")

        def on_about(_widget: Any) -> None:
            try:
                subprocess.Popen(launcher + ["--about"])
            except Exception as err:
                print(f"[Asd Tray] Failed to open About: {err}", file=sys.stderr)

        item_about.connect("activate", on_about)
        menu.append(item_about)

        menu.append(Gtk.SeparatorMenuItem())

        # 4. Quit Asd
        item_quit = Gtk.MenuItem(label="Quit Asd")

        def on_quit(_widget: Any) -> None:
            try:
                subprocess.run(launcher + ["--quit"], timeout=5)
            except Exception:
                pass
            Gtk.main_quit()

        item_quit.connect("activate", on_quit)
        menu.append(item_quit)

        menu.show_all()
        self.menu = menu
        return menu

    def setup_app_indicator(self) -> bool:
        """Attempt to set up Ayatana / AppIndicator via PyGObject or ctypes."""
        app_id = "asd"
        icon_name = "asd"

        # Determine resources directory containing hicolor structure
        script_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(script_dir, "resources"),
            os.path.expanduser("~/.local/share/asd/app/resources"),
            os.path.expanduser("~/.local/share/icons"),
        ]
        icon_theme_dir = ""
        for p in possible_paths:
            if os.path.isdir(p):
                icon_theme_dir = p
                break

        # 1. Try PyGObject typelib
        try:
            import gi
            for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
                try:
                    gi.require_version(ns, "0.1")
                    mod = __import__(f"gi.repository.{ns}", fromlist=[ns])
                    indicator_cls = getattr(mod, ns)
                    if icon_theme_dir and hasattr(indicator_cls.Indicator, "new_with_path"):
                        ind = indicator_cls.Indicator.new_with_path(
                            app_id,
                            icon_name,
                            indicator_cls.IndicatorCategory.APPLICATION_STATUS,
                            icon_theme_dir
                        )
                    else:
                        ind = indicator_cls.Indicator.new(
                            app_id,
                            icon_name,
                            indicator_cls.IndicatorCategory.APPLICATION_STATUS
                        )
                    ind.set_status(indicator_cls.IndicatorStatus.ACTIVE)
                    if hasattr(ind, "set_icon_theme_path") and icon_theme_dir:
                        ind.set_icon_theme_path(icon_theme_dir)
                    if hasattr(ind, "set_icon_full"):
                        ind.set_icon_full(icon_name, "Asd")
                    elif hasattr(ind, "set_icon"):
                        ind.set_icon(icon_name)
                    if hasattr(ind, "set_title"):
                        ind.set_title("Asd")
                    ind.set_menu(self.menu)
                    if hasattr(ind, "set_secondary_activate_target"):
                        ind.set_secondary_activate_target(self.item_open)
                    self.indicator_handle = ind
                    return True
                except Exception:
                    continue
        except Exception:
            pass

        # 2. Fallback to ctypes with native shared library
        lib = None
        for candidate in (
            "libayatana-appindicator3.so.1",
            "libayatana-appindicator3.so",
            "libappindicator3.so.1",
            "libappindicator3.so"
        ):
            try:
                lib = ctypes.CDLL(candidate)
                break
            except Exception:
                continue

        if lib is None:
            return False

        try:
            if hasattr(lib, "app_indicator_new_with_path") and icon_theme_dir:
                lib.app_indicator_new_with_path.argtypes = [
                    ctypes.c_char_p,
                    ctypes.c_char_p,
                    ctypes.c_int,
                    ctypes.c_char_p,
                ]
                lib.app_indicator_new_with_path.restype = ctypes.c_void_p
                ind_ptr = lib.app_indicator_new_with_path(
                    app_id.encode(),
                    icon_name.encode(),
                    0,
                    icon_theme_dir.encode(),
                )
            else:
                lib.app_indicator_new.argtypes = [
                    ctypes.c_char_p,
                    ctypes.c_char_p,
                    ctypes.c_int,
                ]
                lib.app_indicator_new.restype = ctypes.c_void_p
                ind_ptr = lib.app_indicator_new(app_id.encode(), icon_name.encode(), 0)

            if not ind_ptr:
                return False

            lib.app_indicator_set_status.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.app_indicator_set_status.restype = None

            lib.app_indicator_set_menu.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.app_indicator_set_menu.restype = None

            if hasattr(lib, "app_indicator_set_title"):
                lib.app_indicator_set_title.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                lib.app_indicator_set_title.restype = None
                lib.app_indicator_set_title(ind_ptr, b"Asd")

            if hasattr(lib, "app_indicator_set_icon_theme_path") and icon_theme_dir:
                lib.app_indicator_set_icon_theme_path.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                lib.app_indicator_set_icon_theme_path.restype = None
                lib.app_indicator_set_icon_theme_path(ind_ptr, icon_theme_dir.encode())

            if hasattr(lib, "app_indicator_set_icon_full"):
                lib.app_indicator_set_icon_full.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
                lib.app_indicator_set_icon_full.restype = None
                lib.app_indicator_set_icon_full(ind_ptr, icon_name.encode(), b"Asd")
            elif hasattr(lib, "app_indicator_set_icon"):
                lib.app_indicator_set_icon.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                lib.app_indicator_set_icon.restype = None
                lib.app_indicator_set_icon(ind_ptr, icon_name.encode())

            if hasattr(lib, "app_indicator_set_secondary_activate_target"):
                lib.app_indicator_set_secondary_activate_target.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                lib.app_indicator_set_secondary_activate_target.restype = None

            # Status 1 (ACTIVE)
            lib.app_indicator_set_status(ind_ptr, 1)

            # Pass GtkMenu C pointer
            menu_ptr = get_gobject_c_pointer(self.menu)
            if menu_ptr:
                lib.app_indicator_set_menu(ind_ptr, menu_ptr)

            item_open_ptr = get_gobject_c_pointer(self.item_open)
            if item_open_ptr and hasattr(lib, "app_indicator_set_secondary_activate_target"):
                lib.app_indicator_set_secondary_activate_target(ind_ptr, item_open_ptr)

            self.indicator_handle = ind_ptr
            return True
        except Exception as exc:
            print(f"[Asd Tray] Error setting up ctypes indicator: {exc}", file=sys.stderr)
            return False

    def setup_status_icon(self) -> bool:
        """Legacy Gtk.StatusIcon fallback for older environments."""
        Gtk = self.gtk
        assert Gtk is not None

        if not hasattr(Gtk, "StatusIcon"):
            return False

        try:
            status_icon = Gtk.StatusIcon()
            status_icon.set_from_icon_name("asd")
            status_icon.set_tooltip_text("Asd — Encrypted Note Maker")

            def on_activate(_icon: Any) -> None:
                launcher = resolve_app_launcher()
                try:
                    subprocess.Popen(launcher + ["--show"])
                except Exception:
                    pass

            def on_popup_menu(_icon: Any, button: int, activate_time: int) -> None:
                if self.menu:
                    self.menu.popup(None, None, Gtk.StatusIcon.position_menu, status_icon, button, activate_time)

            status_icon.connect("activate", on_activate)
            status_icon.connect("popup-menu", on_popup_menu)
            status_icon.set_visible(True)
            self.indicator_handle = status_icon
            return True
        except Exception as exc:
            print(f"[Asd Tray] StatusIcon fallback failed: {exc}", file=sys.stderr)
            return False

    def check_parent_liveness(self) -> bool:
        """Ensure the tray exits if the parent main.py process dies."""
        # If parent PID changes (reparented to init/systemd), the parent has exited
        current_ppid = os.getppid()
        if current_ppid != self.parent_pid:
            if self.gtk:
                self.gtk.main_quit()
            return False
        return True

    def run(self) -> int:
        """Start the system tray service."""
        if not self.initialize_gtk():
            return 1

        self.build_menu()

        # Try AppIndicator (Ayatana / Canonical) first, then StatusIcon
        if not self.setup_app_indicator():
            if not self.setup_status_icon():
                print(
                    "[Asd Tray] Warning: Neither AppIndicator nor StatusIcon could be initialized.\n"
                    "           Tray icon unavailable.",
                    file=sys.stderr
                )
                return 0

        # Periodic check to quit when parent process terminates
        assert self.glib is not None
        assert self.gtk is not None
        self.glib.timeout_add_seconds(2, self.check_parent_liveness)

        # Handle termination signals cleanly
        def handle_signal(_signum: int, _frame: Any) -> None:
            if self.gtk:
                self.gtk.main_quit()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        self.gtk.main()
        return 0


def main() -> int:
    service = SystemTrayService()
    return service.run()


if __name__ == "__main__":
    sys.exit(main())
