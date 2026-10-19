#!/usr/bin/env python3
"""
ui.py — GTK4 + Libadwaita user interface for Asd.

Provides:
- First-time master password initialization (Setup view)
- Password challenge unlock (Unlock view)
- Two-pane split view encrypted note editor (Vault view)
- Live auto-save and encrypted background persistence
- Full encrypted binary .asd Vault Import & Export engine (zero plaintext on disk)
- Complete keyboard shortcut bindings
"""

from __future__ import annotations

import base64
from datetime import datetime
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
from cryptography.fernet import Fernet, InvalidToken

from crypto import CryptoManager, CryptoError
from database import DatabaseManager

ASD_MAGIC: bytes = b"ASD\x01"

AUTH_UNLOCK_WIDTH: int = 380
AUTH_UNLOCK_HEIGHT: int = 310
AUTH_SETUP_WIDTH: int = 400
AUTH_SETUP_HEIGHT: int = 370

CUSTOM_CSS: str = """
.vault-paned {
    background-color: @window_bg_color;
}
.sidebar-pane {
    background-color: @card_bg_color;
    border-right: 1px solid alpha(@borders, 0.6);
}
.note-row-box {
    padding: 8px 10px;
    border-radius: 8px;
}
.note-title-label {
    font-weight: 700;
    font-size: 1.05rem;
}
.note-preview-label {
    font-size: 0.88rem;
    opacity: 0.72;
}
.note-date-label {
    font-size: 0.75rem;
    opacity: 0.45;
}

/* Title & Content unified styling & focus border */
.editor-title-entry {
    font-size: 1.35rem;
    font-weight: 700;
    padding: 10px 14px;
    background-color: alpha(@window_fg_color, 0.04);
    border-radius: 8px;
    border: 1px solid alpha(@borders, 0.5);
    box-shadow: none;
    transition: all 150ms ease-in-out;
}
.editor-title-entry text {
    background: transparent;
    background-color: transparent;
}
.editor-title-entry:not(:focus-within) selection {
    background-color: transparent;
    color: inherit;
}
.editor-title-entry:focus-within {
    border-color: @accent_color;
    outline: 2px solid @accent_color;
    outline-offset: -1px;
}
.editor-content-scrolled {
    background-color: alpha(@window_fg_color, 0.04);
    border-radius: 8px;
    border: 1px solid alpha(@borders, 0.5);
    transition: all 150ms ease-in-out;
}
.editor-content-scrolled:focus-within {
    border-color: @accent_color;
    outline: 2px solid @accent_color;
    outline-offset: -1px;
}
.editor-content-textview {
    background: transparent;
}

window.auth-mode {
    background-color: @card_bg_color;
}
window.auth-mode .toast-overlay {
    background-color: @card_bg_color;
}
.auth-card {
    background-color: @card_bg_color;
}
.auth-title {
    font-size: 1.5rem;
    font-weight: 800;
}
.auth-subtitle {
    font-size: 0.95rem;
    opacity: 0.75;
}
.auth-icon {
    color: @accent_color;
}
.auth-close-btn {
    opacity: 0.55;
    border-radius: 9999px;
    min-width: 28px;
    min-height: 28px;
    padding: 4px;
    transition: all 150ms ease-in-out;
}
.auth-close-btn:hover {
    opacity: 1.0;
    background-color: alpha(@window_fg_color, 0.08);
}
.row-copy-btn {
    opacity: 0.45;
    padding: 3px;
    min-width: 24px;
    min-height: 24px;
    border-radius: 9999px;
    transition: all 150ms ease-in-out;
}
.row-copy-btn:hover {
    opacity: 1.0;
    background-color: alpha(@window_fg_color, 0.12);
}
.error-banner {
    color: @destructive_color;
    font-weight: 600;
    font-size: 0.9rem;
}
"""


class NoteRow(Gtk.ListBoxRow):
    """
    Sidebar row widget representing an encrypted note.
    Displays bold title, first row preview, and updated timestamp.
    """

    def __init__(
        self,
        note_id: int,
        title: str,
        content: str,
        updated_at: str = ""
    ) -> None:
        super().__init__()
        self.note_id: int = note_id
        self.raw_title: str = title
        self.raw_content: str = content

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.box.add_css_class("note-row-box")

        # Top line: Title & Date
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.title_label = Gtk.Label(xalign=0.0, hexpand=True)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.add_css_class("note-title-label")

        self.date_label = Gtk.Label(xalign=1.0)
        self.date_label.add_css_class("note-date-label")

        header_box.append(self.title_label)
        header_box.append(self.date_label)

        # Bottom line: only show first row of note under title
        self.preview_label = Gtk.Label(xalign=0.0)
        self.preview_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.preview_label.add_css_class("note-preview-label")

        self.box.append(header_box)
        self.box.append(self.preview_label)
        self.set_child(self.box)

        self.update_data(title, content, updated_at)

    def update_data(self, title: str, content: str, updated_at: str = "") -> None:
        """Update the row's rendered title, first-row preview snippet, and timestamp."""
        self.raw_title = title
        self.raw_content = content

        display_title = title.strip() if title.strip() else "Untitled Note"
        self.title_label.set_text(display_title)

        # Only show first row of note under title
        first_line = ""
        for line in content.splitlines():
            line_str = line.strip()
            if line_str:
                first_line = line_str
                break

        display_preview = first_line if first_line else "No additional text"
        self.preview_label.set_text(display_preview)

        # Format timestamp
        if updated_at:
            parts = updated_at.split()
            if len(parts) >= 2:
                time_part = parts[1][:5]
                self.date_label.set_text(time_part)
            else:
                self.date_label.set_text(updated_at[:10])
        else:
            self.date_label.set_text("")


class MainWindow(Adw.ApplicationWindow):
    """
    Main Libadwaita application window with Setup, Unlock, and Vault views.
    Handles instant auto-save, lock-on-close, encrypted .asd import/export, and keyboard shortcuts.
    """

    def __init__(
        self,
        application: Optional[Adw.Application],
        db: DatabaseManager,
        crypto: CryptoManager
    ) -> None:
        if application is not None:
            super().__init__(application=application)
        else:
            super().__init__()

        self.db: DatabaseManager = db
        self.crypto: CryptoManager = crypto

        self.updating_ui: bool = False
        self.current_note_id: Optional[int] = None
        self._save_timeout_id: Optional[int] = None
        self._status_clear_timeout_id: Optional[int] = None
        self.vault_width: int = 960
        self.vault_height: int = 640

        self.set_title("Asd")
        self.set_icon_name("asd")

        self._load_css()
        self._build_ui()
        self._setup_actions()
        self._setup_shortcuts()

        # Connect close-request to lock vault and hide rather than quit
        self.connect("close-request", self._on_close_request)

        # Initialize window in compact borderless card mode if locked/uninitialized
        if not self.db.is_initialized():
            self.set_default_size(AUTH_SETUP_WIDTH, AUTH_SETUP_HEIGHT)
            self.header_bar.set_visible(False)
            self.add_css_class("auth-mode")
            self.main_stack.set_visible_child_name("setup")
        elif not self.crypto.is_unlocked:
            self.set_default_size(AUTH_UNLOCK_WIDTH, AUTH_UNLOCK_HEIGHT)
            self.header_bar.set_visible(False)
            self.add_css_class("auth-mode")
            self.main_stack.set_visible_child_name("unlock")
        else:
            self.set_default_size(self.vault_width, self.vault_height)
            self.header_bar.set_visible(True)
            self.main_stack.set_visible_child_name("vault")

    @staticmethod
    def _focus_widget(widget: Gtk.Widget) -> bool:
        """
        Helper for GLib.idle_add to focus a widget once.
        Returns GLib.SOURCE_REMOVE (False) so GLib executes it only once.
        """
        widget.grab_focus()
        return GLib.SOURCE_REMOVE

    def show_toast(self, message: str) -> None:
        """Surface an Adw.Toast message."""
        toast = Adw.Toast.new(message)
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def _load_css(self) -> None:
        """Register custom CSS styles for the window."""
        provider = Gtk.CssProvider()
        provider.load_from_string(CUSTOM_CSS)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _build_ui(self) -> None:
        """Assemble HeaderBar, ToastOverlay, and Gtk.Stack containing setup, unlock, and vault views."""
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # HeaderBar
        self.header_bar = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle(
            title="Asd",
            subtitle="Encrypted Desktop Vault"
        )
        self.header_bar.set_title_widget(self.window_title)

        # HeaderBar Action Buttons (visible when unlocked)
        self.new_note_btn = Gtk.Button(label="+ New Note")
        self.new_note_btn.add_css_class("suggested-action")
        self.new_note_btn.set_tooltip_text("Create a new encrypted note (Ctrl+N)")
        self.new_note_btn.connect("clicked", lambda _: self.create_new_note())
        self.header_bar.pack_start(self.new_note_btn)

        # Primary Menu Button (Encrypted .asd Import & Export)
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_icon_name("open-menu-symbolic")
        self.menu_button.set_tooltip_text("Main Menu")

        menu = Gio.Menu()
        menu_vault = Gio.Menu()
        menu_vault.append("Export Encrypted Vault (.asd)...", "win.export_asd")
        menu_vault.append("Import Encrypted Vault (.asd)...", "win.import_asd")
        menu.append_section("Backup & Restore", menu_vault)

        menu_actions = Gio.Menu()
        menu_actions.append("Lock Vault (Ctrl+L)", "win.lock_vault")
        menu.append_section(None, menu_actions)

        menu_help = Gio.Menu()
        menu_help.append("About Asd", "win.about")
        menu.append_section(None, menu_help)

        menu_exit = Gio.Menu()
        menu_exit.append("Exit", "win.exit_app")
        menu.append_section(None, menu_exit)

        self.menu_button.set_menu_model(menu)
        self.header_bar.pack_end(self.menu_button)

        self.lock_btn = Gtk.Button(icon_name="system-lock-screen-symbolic")
        self.lock_btn.set_tooltip_text("Lock Vault (Ctrl+L)")
        self.lock_btn.connect("clicked", lambda _: self.lock_vault())
        self.header_bar.pack_end(self.lock_btn)

        root_box.append(self.header_bar)

        # Main Stack for 3 states: setup, unlock, vault
        self.main_stack = Gtk.Stack()
        self.main_stack.set_hhomogeneous(False)
        self.main_stack.set_vhomogeneous(False)
        self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.main_stack.set_transition_duration(200)

        self.setup_view = self._build_setup_view()
        self.unlock_view = self._build_unlock_view()
        self.vault_view = self._build_vault_view()

        self.main_stack.add_named(self.setup_view, "setup")
        self.main_stack.add_named(self.unlock_view, "unlock")
        self.main_stack.add_named(self.vault_view, "vault")

        # Toast overlay for modern in-app notifications
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self.main_stack)

        root_box.append(self.toast_overlay)
        self.set_content(root_box)

    def _setup_actions(self) -> None:
        """Register window-level Gio.SimpleActions for menus and accelerators."""
        self._add_win_action("export_asd", lambda *_: self.export_encrypted_vault())
        self._add_win_action("import_asd", lambda *_: self.import_encrypted_vault())
        self._add_win_action("lock_vault", lambda *_: self.lock_vault())
        self._add_win_action("about", lambda *_: self.show_about_dialog())
        self._add_win_action("exit_app", lambda *_: self.exit_app())

    def _add_win_action(self, name: str, callback: Callable[..., Any]) -> None:
        """Helper to create and attach a Gio.SimpleAction to the window."""
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

    def show_about_dialog(self) -> None:
        """Display simple, all-in-one About dialog with all info visible immediately."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # App Icon
        icon = Gtk.Image.new_from_icon_name("asd")
        icon.set_pixel_size(64)
        box.append(icon)

        # App Title & Version
        title_lbl = Gtk.Label(
            label='<span size="x-large" weight="bold">Asd</span> <span alpha="65%">1.0.0</span>',
            use_markup=True
        )
        box.append(title_lbl)

        # Description
        desc_lbl = Gtk.Label(
            label="Fast, modular, encrypted desktop Note Maker for Ubuntu Linux.",
            wrap=True,
            justify=Gtk.Justification.CENTER
        )
        desc_lbl.add_css_class("dim-label")
        box.append(desc_lbl)

        # Info Boxed List (All info visible immediately)
        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)

        row_dev = Adw.ActionRow(title="Developer", subtitle="stone")
        listbox.append(row_dev)

        row_email = Adw.ActionRow(title="Email")
        email_lbl = Gtk.Label(
            label='<a href="mailto:stonemanhero@gmail.com">stonemanhero@gmail.com</a>',
            use_markup=True
        )
        email_lbl.set_valign(Gtk.Align.CENTER)
        row_email.add_suffix(email_lbl)
        listbox.append(row_email)

        row_web = Adw.ActionRow(title="Website")
        web_lbl = Gtk.Label(
            label='<a href="https://aystat.com">aystat.com</a>',
            use_markup=True
        )
        web_lbl.set_valign(Gtk.Align.CENTER)
        row_web.add_suffix(web_lbl)
        listbox.append(row_web)

        row_lic = Adw.ActionRow(title="License", subtitle="MIT License")
        listbox.append(row_lic)

        row_cpr = Adw.ActionRow(title="Copyright", subtitle="© 2026 stone")
        listbox.append(row_cpr)

        box.append(listbox)

        if hasattr(Adw, "AlertDialog"):
            dialog = Adw.AlertDialog(heading="About Asd")
            dialog.set_extra_child(box)
            dialog.add_response("close", "Close")
            dialog.set_default_response("close")
            dialog.set_close_response("close")
            dialog.present(self)
        else:
            win = Adw.Window(transient_for=self, modal=True, title="About Asd")
            win.set_default_size(360, 420)
            win.set_content(box)
            win.present()

    def show_toast(self, message: str) -> None:
        """Display an Adw.Toast floating notification banner."""
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _build_setup_view(self) -> Gtk.Widget:
        """First-time setup screen: prompts user to define their Master Password in borderless card."""
        handle = Gtk.WindowHandle()
        overlay = Gtk.Overlay()
        handle.set_child(overlay)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("auth-card")
        card.set_valign(Gtk.Align.CENTER)
        card.set_vexpand(True)
        card.set_margin_top(20)
        card.set_margin_bottom(20)
        card.set_margin_start(28)
        card.set_margin_end(28)

        # Subtle close button in top right
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.add_css_class("circular")
        close_btn.add_css_class("auth-close-btn")
        close_btn.set_halign(Gtk.Align.END)
        close_btn.set_valign(Gtk.Align.START)
        close_btn.set_margin_top(8)
        close_btn.set_margin_end(8)
        close_btn.set_tooltip_text("Minimize to Tray (Esc)")
        close_btn.connect("clicked", lambda _: self.minimize_to_tray())
        overlay.add_overlay(close_btn)

        # Icon & Title
        icon = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        icon.set_pixel_size(64)
        icon.add_css_class("accent")
        icon.add_css_class("auth-icon")

        title = Gtk.Label(label="Initialize Asd Vault")
        title.add_css_class("auth-title")

        subtitle = Gtk.Label(
            label="Set a Master Password to protect your notes with\n"
                  "AES-256 encryption. Your password is never stored."
        )
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.add_css_class("auth-subtitle")
        subtitle.set_wrap(True)

        card.append(icon)
        card.append(title)
        card.append(subtitle)

        # Form Entries
        form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        self.setup_pwd_entry = Gtk.PasswordEntry(placeholder_text="Master Password (min 8 characters)")
        self.setup_pwd_entry.connect("activate", self._on_setup_submit)

        self.setup_confirm_entry = Gtk.PasswordEntry(placeholder_text="Confirm Master Password")
        self.setup_confirm_entry.connect("activate", self._on_setup_submit)

        self.setup_error_label = Gtk.Label()
        self.setup_error_label.add_css_class("error-banner")
        self.setup_error_label.set_visible(False)
        self.setup_error_label.set_wrap(True)

        self.init_btn = Gtk.Button(label="Initialize Encrypted Vault")
        self.init_btn.add_css_class("suggested-action")
        self.init_btn.add_css_class("pill")
        self.init_btn.connect("clicked", self._on_setup_submit)

        form_box.append(self.setup_pwd_entry)
        form_box.append(self.setup_confirm_entry)
        form_box.append(self.setup_error_label)
        form_box.append(self.init_btn)

        card.append(form_box)
        overlay.set_child(card)
        return handle

    def _build_unlock_view(self) -> Gtk.Widget:
        """Unlock screen: challenge user for Master Password upon opening in borderless card."""
        handle = Gtk.WindowHandle()
        overlay = Gtk.Overlay()
        handle.set_child(overlay)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.add_css_class("auth-card")
        card.set_valign(Gtk.Align.CENTER)
        card.set_vexpand(True)
        card.set_margin_top(20)
        card.set_margin_bottom(20)
        card.set_margin_start(28)
        card.set_margin_end(28)

        # Subtle close button in top right
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.add_css_class("circular")
        close_btn.add_css_class("auth-close-btn")
        close_btn.set_halign(Gtk.Align.END)
        close_btn.set_valign(Gtk.Align.START)
        close_btn.set_margin_top(8)
        close_btn.set_margin_end(8)
        close_btn.set_tooltip_text("Minimize to Tray (Esc)")
        close_btn.connect("clicked", lambda _: self.minimize_to_tray())
        overlay.add_overlay(close_btn)

        icon = Gtk.Image.new_from_icon_name("system-lock-screen-symbolic")
        icon.set_pixel_size(64)
        icon.add_css_class("accent")
        icon.add_css_class("auth-icon")

        title = Gtk.Label(label="Unlock Asd")
        title.add_css_class("auth-title")

        subtitle = Gtk.Label(label="Enter your Master Password to decrypt your vault.")
        subtitle.add_css_class("auth-subtitle")
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.set_wrap(True)

        card.append(icon)
        card.append(title)
        card.append(subtitle)

        # Form Entries
        form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        self.unlock_pwd_entry = Gtk.PasswordEntry(placeholder_text="Master Password")
        self.unlock_pwd_entry.connect("activate", self._on_unlock_submit)

        self.unlock_error_label = Gtk.Label()
        self.unlock_error_label.add_css_class("error-banner")
        self.unlock_error_label.set_visible(False)
        self.unlock_error_label.set_wrap(True)

        self.unlock_btn = Gtk.Button(label="Unlock Vault")
        self.unlock_btn.add_css_class("suggested-action")
        self.unlock_btn.add_css_class("pill")
        self.unlock_btn.connect("clicked", self._on_unlock_submit)

        form_box.append(self.unlock_pwd_entry)
        form_box.append(self.unlock_error_label)
        form_box.append(self.unlock_btn)

        card.append(form_box)
        overlay.set_child(card)
        return handle

    def _build_vault_view(self) -> Gtk.Widget:
        """Two-Pane Split View: Sidebar (search + note list) and Note Editor."""
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.add_css_class("vault-paned")
        self.paned.set_position(300)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)

        # --- LEFT PANE (Sidebar) ---
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_box.add_css_class("sidebar-pane")

        # Top Search Entry
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_box.set_margin_start(8)
        search_box.set_margin_end(8)
        search_box.set_margin_top(8)
        search_box.set_margin_bottom(6)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search notes (Ctrl+F)...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("stop-search", self._on_search_cleared)
        search_box.append(self.search_entry)
        left_box.append(search_box)

        # Scrollable Note ListBox
        scrolled_sidebar = Gtk.ScrolledWindow()
        scrolled_sidebar.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_sidebar.set_vexpand(True)
        scrolled_sidebar.set_hexpand(True)

        self.notes_list = Gtk.ListBox()
        self.notes_list.add_css_class("navigation-sidebar")
        self.notes_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.notes_list.connect("row-selected", self._on_note_row_selected)
        scrolled_sidebar.set_child(self.notes_list)
        left_box.append(scrolled_sidebar)

        # Sidebar Footer
        self.footer_label = Gtk.Label(label="0 notes found")
        self.footer_label.add_css_class("dim-label")
        self.footer_label.set_margin_top(6)
        self.footer_label.set_margin_bottom(8)
        left_box.append(self.footer_label)

        self.paned.set_start_child(left_box)

        # --- RIGHT PANE (Editor / Empty State) ---
        self.editor_stack = Gtk.Stack()
        self.editor_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.editor_stack.set_transition_duration(150)

        # Empty State
        empty_page = Adw.StatusPage()
        empty_page.set_icon_name("document-edit-symbolic")
        empty_page.set_title("No Note Selected")
        empty_page.set_description(
            "Select a note from the sidebar or click '+ New Note' (Ctrl+N) to create one."
        )
        self.editor_stack.add_named(empty_page, "empty")

        # Editor View
        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        editor_box.set_margin_start(20)
        editor_box.set_margin_end(20)
        editor_box.set_margin_top(16)
        editor_box.set_margin_bottom(14)

        # Title Entry with clean styling and focus border
        self.title_entry = Gtk.Entry()
        self.title_entry.set_placeholder_text("Note Title...")
        self.title_entry.add_css_class("editor-title-entry")
        self.title_entry.connect("changed", self._on_title_changed)
        editor_box.append(self.title_entry)

        # Content TextView & Per-Row Copy Column inside ScrolledWindow
        self.scrolled_editor = Gtk.ScrolledWindow()
        self.scrolled_editor.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_editor.set_vexpand(True)
        self.scrolled_editor.set_hexpand(True)
        self.scrolled_editor.add_css_class("editor-content-scrolled")

        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content_box.set_hexpand(True)
        content_box.set_vexpand(True)

        self.text_view = Gtk.TextView()
        self.text_view.add_css_class("editor-content-textview")
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_hexpand(True)
        self.text_view.set_vexpand(True)
        self.text_view.set_left_margin(14)
        self.text_view.set_right_margin(8)
        self.text_view.set_top_margin(12)
        self.text_view.set_bottom_margin(12)
        self.text_view.set_pixels_above_lines(4)
        self.text_view.set_pixels_below_lines(4)

        self.row_copy_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.row_copy_box.set_margin_top(12)
        self.row_copy_box.set_margin_end(8)
        self.row_copy_box.set_valign(Gtk.Align.START)

        self.text_buffer = self.text_view.get_buffer()
        self.text_buffer.connect("changed", self._on_content_changed)

        content_box.append(self.text_view)
        content_box.append(self.row_copy_box)
        self.scrolled_editor.set_child(content_box)
        editor_box.append(self.scrolled_editor)

        # Editor Bottom Bar (Status + Delete Button)
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bottom_bar.set_margin_top(6)

        self.status_label = Gtk.Label(label="", xalign=0.0)
        self.status_label.set_hexpand(True)
        self.status_label.add_css_class("dim-label")

        self.delete_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self.delete_btn.add_css_class("destructive-action")
        self.delete_btn.set_tooltip_text("Delete Note")
        self.delete_btn.connect("clicked", self._on_delete_clicked)

        bottom_bar.append(self.status_label)
        bottom_bar.append(self.delete_btn)
        editor_box.append(bottom_bar)

        self.editor_stack.add_named(editor_box, "editor")
        self.editor_stack.set_visible_child_name("empty")

        self.paned.set_end_child(self.editor_stack)
        return self.paned

    def _setup_shortcuts(self) -> None:
        """Register application window keyboard shortcuts via Gtk.EventControllerKey."""
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType
    ) -> bool:
        """Handle window-level keyboard accelerators."""
        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        # Escape -> Minimize to tray
        if keyval == Gdk.KEY_Escape:
            self.minimize_to_tray()
            return True

        if is_ctrl and not is_shift:
            # Standard Ctrl Accelerators
            if keyval in (Gdk.KEY_n, Gdk.KEY_N):
                if self.crypto.is_unlocked:
                    self.create_new_note()
                    return True
            elif keyval in (Gdk.KEY_f, Gdk.KEY_F):
                if self.crypto.is_unlocked:
                    self.search_entry.grab_focus()
                    return True
            elif keyval in (Gdk.KEY_l, Gdk.KEY_L):
                if self.crypto.is_unlocked:
                    self.lock_vault()
                    return True

        return False

    def minimize_to_tray(self) -> None:
        """Hide window to tray without locking vault."""
        self._flush_pending_save()
        if self.crypto.is_unlocked and self.main_stack.get_visible_child_name() == "vault":
            w = self.get_width()
            h = self.get_height()
            if w > 500 and h > 400:
                self.vault_width = w
                self.vault_height = h
        self.set_visible(False)

    def exit_app(self) -> None:
        """Completely shut down the application, terminate background daemons, and exit."""
        self._flush_pending_save()
        self.crypto.lock()
        app = self.get_application()
        if app is not None and hasattr(app, "quit_app"):
            app.quit_app()
        else:
            self.destroy()
            sys.exit(0)

    def center_and_present(self, token: Optional[str] = None) -> None:
        """Reveal, raise, and present the window to the user with optional activation token."""
        is_auth = self.main_stack.get_visible_child_name() in ("unlock", "setup") or not self.crypto.is_unlocked
        if is_auth:
            target_w = AUTH_SETUP_WIDTH if self.main_stack.get_visible_child_name() == "setup" else AUTH_UNLOCK_WIDTH
            target_h = AUTH_SETUP_HEIGHT if self.main_stack.get_visible_child_name() == "setup" else AUTH_UNLOCK_HEIGHT
            self.set_default_size(target_w, target_h)
            self.header_bar.set_visible(False)
            self.add_css_class("auth-mode")
        else:
            self.set_default_size(self.vault_width, self.vault_height)
            self.header_bar.set_visible(True)
            self.remove_css_class("auth-mode")

        self.set_visible(True)
        self.unminimize()
        self.realize()

        if token:
            surface = self.get_surface()
            if surface and hasattr(surface, "set_startup_id"):
                try:
                    surface.set_startup_id(token)
                except Exception:
                    pass

        self.present()

        if is_auth:
            if self.main_stack.get_visible_child_name() == "setup":
                GLib.idle_add(self._focus_widget, self.setup_pwd_entry)
            else:
                GLib.idle_add(self._focus_widget, self.unlock_pwd_entry)
        else:
            self.title_entry.select_region(0, 0)
            if self.crypto.is_unlocked and self.main_stack.get_visible_child_name() == "vault":
                GLib.idle_add(self._focus_widget, self.search_entry)

    def _on_close_request(self, window: Gtk.Window) -> bool:
        """Intercept close button (X): minimize to top panel tray without locking."""
        self.minimize_to_tray()
        return True  # Stop GTK default window destruction

    # --- View Transitions ---

    def show_setup_view(self) -> None:
        """Transition to Setup view for initial master password generation in compact borderless card mode."""
        self.add_css_class("auth-mode")
        self.header_bar.set_visible(False)
        self.new_note_btn.set_visible(False)
        self.lock_btn.set_visible(False)
        self.menu_button.set_visible(False)
        self.window_title.set_subtitle("Setup Encrypted Vault")
        self.setup_pwd_entry.set_text("")
        self.setup_confirm_entry.set_text("")
        self.setup_error_label.set_visible(False)
        self.main_stack.set_visible_child_name("setup")
        GLib.idle_add(self._focus_widget, self.setup_pwd_entry)

        self.set_default_size(AUTH_SETUP_WIDTH, AUTH_SETUP_HEIGHT)
        if self.is_visible():
            self.set_visible(False)
            self.unrealize()
            self.set_visible(True)
            self.present()

    def lock_vault(self, present: bool = True) -> None:
        """
        Wipe sensitive data from memory and UI, clear encryption key from RAM,
        and display the Unlock view in compact borderless card mode.
        """
        self._flush_pending_save()
        if self._status_clear_timeout_id is not None:
            GLib.source_remove(self._status_clear_timeout_id)
            self._status_clear_timeout_id = None
        self.status_label.set_text("")

        if self.main_stack.get_visible_child_name() == "vault":
            w = self.get_width()
            h = self.get_height()
            if w > 500 and h > 400:
                self.vault_width = w
                self.vault_height = h

        self.updating_ui = True
        # Clear editor buffers
        self.title_entry.set_text("")
        self.text_buffer.set_text("")
        self.current_note_id = None

        # Clear sidebar list items
        while True:
            row = self.notes_list.get_row_at_index(0)
            if row is None:
                break
            self.notes_list.remove(row)

        self.footer_label.set_text("0 notes found")
        self.search_entry.set_text("")
        self.editor_stack.set_visible_child_name("empty")
        self._update_row_copy_buttons()
        self.updating_ui = False

        # Wipe cryptography key from memory immediately
        self.crypto.lock()

        # Update HeaderBar & Mode: borderless card look
        self.add_css_class("auth-mode")
        self.header_bar.set_visible(False)
        self.new_note_btn.set_visible(False)
        self.lock_btn.set_visible(False)
        self.menu_button.set_visible(False)
        self.window_title.set_subtitle("Vault Locked")

        # Show Unlock view
        self.unlock_pwd_entry.set_text("")
        self.unlock_error_label.set_visible(False)
        self.main_stack.set_visible_child_name("unlock")
        GLib.idle_add(self._focus_widget, self.unlock_pwd_entry)

        # Resize to compact card size
        self.set_default_size(AUTH_UNLOCK_WIDTH, AUTH_UNLOCK_HEIGHT)
        if self.is_visible() and present:
            self.present()

    def show_vault_view(self, present: bool = True) -> None:
        """Transition to Vault view upon successful unlock and restore full window size."""
        self.remove_css_class("auth-mode")
        self.header_bar.set_visible(True)
        self.new_note_btn.set_visible(True)
        self.lock_btn.set_visible(True)
        self.menu_button.set_visible(True)
        self.window_title.set_subtitle("Encrypted Desktop Vault")
        self.main_stack.set_visible_child_name("vault")
        self.refresh_notes_list()
        self.title_entry.select_region(0, 0)
        GLib.idle_add(self._focus_widget, self.search_entry)

        # Restore full vault window size
        self.set_default_size(self.vault_width, self.vault_height)
        if self.is_visible() and present:
            self.present()

    # --- Setup & Unlock Actions ---

    def _on_setup_submit(self, *args: Any) -> None:
        """Validate passwords and initialize the encrypted database."""
        pwd = self.setup_pwd_entry.get_text()
        confirm = self.setup_confirm_entry.get_text()

        if len(pwd) < 8:
            self.setup_error_label.set_text("Master Password must be at least 8 characters.")
            self.setup_error_label.set_visible(True)
            self.setup_pwd_entry.grab_focus()
            return

        if pwd != confirm:
            self.setup_error_label.set_text("Passwords do not match. Please re-enter.")
            self.setup_error_label.set_visible(True)
            self.setup_confirm_entry.grab_focus()
            return

        self.setup_error_label.set_visible(False)
        try:
            salt, verify_token = self.crypto.setup_master_password(pwd)
            self.db.save_master_credentials(salt, verify_token)
        except Exception as e:
            self.setup_error_label.set_text(f"Initialization error: {e}")
            self.setup_error_label.set_visible(True)
            return

        # Seed initial welcoming note
        welcome_title = "Welcome to Asd 📝"
        welcome_content = (
            "Welcome to your personal encrypted notepad!\n\n"
            "Security Architecture:\n"
            "• AES-256 (Fernet) symmetric encryption on disk.\n"
            "• PBKDF2-HMAC-SHA256 key derivation with 480,000 iterations.\n"
            "• In-memory encryption key wiped immediately when locked or closed.\n\n"
            "Encrypted Binary Backup (.asd):\n"
            "• Use Header Menu (≡) -> 'Export/Import Encrypted Vault (.asd)'\n"
            "• Backup files are 100% binary ciphertext (.asd) with zero plaintext or JSON columns\n"
            "• Cross-vault restore supports entering the backup's master password\n\n"
            "Per-Row Copy & Quick Actions:\n"
            "• Click the copy icon beside any line to copy only that line to clipboard\n\n"
            "Keyboard Shortcuts:\n"
            "• Ctrl+N : Create a new note\n"
            "• Ctrl+F : Search notes case-insensitively\n"
            "• Ctrl+L : Lock vault immediately\n"
            "• Escape : Minimize to tray\n"
        )
        self.db.create_note(welcome_title, welcome_content)

        self.setup_pwd_entry.set_text("")
        self.setup_confirm_entry.set_text("")
        self.show_vault_view()

    def _on_unlock_submit(self, *args: Any) -> None:
        """Authenticate user against stored credentials and unlock the vault."""
        pwd = self.unlock_pwd_entry.get_text()
        if not pwd:
            return

        salt, verify_token = self.db.get_master_credentials()
        if not salt or not verify_token:
            self.show_setup_view()
            return

        if self.crypto.unlock(pwd, salt, verify_token):
            self.unlock_pwd_entry.set_text("")
            self.unlock_error_label.set_visible(False)
            self.show_vault_view()
        else:
            self.unlock_error_label.set_text("Incorrect master password. Please try again.")
            self.unlock_error_label.set_visible(True)
            self.unlock_pwd_entry.select_region(0, -1)
            self.unlock_pwd_entry.grab_focus()

    # --- Note List & Selection ---

    def _find_row_by_id(self, note_id: int) -> Optional[NoteRow]:
        """Find a NoteRow in the ListBox matching note_id."""
        idx = 0
        while True:
            row = self.notes_list.get_row_at_index(idx)
            if row is None:
                return None
            if isinstance(row, NoteRow) and row.note_id == note_id:
                return row
            idx += 1

    def refresh_notes_list(self, query: Optional[str] = None) -> None:
        """
        Reload decrypted notes from SQLite, populate the sidebar list,
        and manage selection state.
        """
        if not self.crypto.is_unlocked:
            return

        if query is None:
            query = self.search_entry.get_text()

        notes = self.db.get_notes(query)

        self.updating_ui = True
        while True:
            row = self.notes_list.get_row_at_index(0)
            if row is None:
                break
            self.notes_list.remove(row)
        self.updating_ui = False

        target_row: Optional[NoteRow] = None
        for note in notes:
            row = NoteRow(
                note_id=note["id"],
                title=note["title"],
                content=note["content"],
                updated_at=note.get("updated_at", "")
            )
            self.notes_list.append(row)
            if self.current_note_id == note["id"]:
                target_row = row

        count = len(notes)
        self.footer_label.set_text(f"{count} {'note' if count == 1 else 'notes'} found")

        if target_row is not None:
            self.notes_list.select_row(target_row)
            self.title_entry.select_region(0, 0)
        elif count > 0:
            first_row = self.notes_list.get_row_at_index(0)
            self.notes_list.select_row(first_row)
            self.title_entry.select_region(0, 0)
            GLib.idle_add(self._focus_widget, self.search_entry)
        else:
            self.current_note_id = None
            self.editor_stack.set_visible_child_name("empty")
            GLib.idle_add(self._focus_widget, self.search_entry)

    def _on_note_row_selected(self, list_box: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]) -> None:
        """Load selected note into the editor pane."""
        if self.updating_ui:
            return

        if row is None or not isinstance(row, NoteRow):
            self.current_note_id = None
            self.editor_stack.set_visible_child_name("empty")
            return

        note = self.db.get_note(row.note_id)
        if not note:
            self.current_note_id = None
            self.editor_stack.set_visible_child_name("empty")
            return

        self._flush_pending_save()
        if self._status_clear_timeout_id is not None:
            GLib.source_remove(self._status_clear_timeout_id)
            self._status_clear_timeout_id = None
        self.status_label.set_text("")

        self.updating_ui = True
        self.current_note_id = note["id"]
        self.title_entry.set_text(note["title"])
        self.title_entry.select_region(0, 0)
        self.text_buffer.set_text(note["content"])
        self.updating_ui = False
        self._update_row_copy_buttons()

        self.editor_stack.set_visible_child_name("editor")

    # --- Live Auto-Save ---

    def _on_title_changed(self, entry: Gtk.Entry) -> None:
        """Update sidebar preview live and schedule debounced save to SQLite."""
        if self.updating_ui or self.current_note_id is None:
            return

        title = self.title_entry.get_text()
        start = self.text_buffer.get_start_iter()
        end = self.text_buffer.get_end_iter()
        content = self.text_buffer.get_text(start, end, True)

        row = self._find_row_by_id(self.current_note_id)
        if row:
            row.update_data(title, content)

        self._schedule_save()

    def _on_content_changed(self, buffer: Gtk.TextBuffer) -> None:
        """Update sidebar preview live and schedule debounced save to SQLite."""
        if self.updating_ui or self.current_note_id is None:
            return

        self._update_row_copy_buttons()

        title = self.title_entry.get_text()
        start = self.text_buffer.get_start_iter()
        end = self.text_buffer.get_end_iter()
        content = self.text_buffer.get_text(start, end, True)

        row = self._find_row_by_id(self.current_note_id)
        if row:
            row.update_data(title, content)

        self._schedule_save()

    def _schedule_save(self) -> None:
        """Debounce auto-save by 400ms after user pauses typing, then execute write."""
        if self._save_timeout_id is not None:
            GLib.source_remove(self._save_timeout_id)
            self._save_timeout_id = None

        self._save_timeout_id = GLib.timeout_add(400, self._do_save)

    def _do_save(self) -> bool:
        """Execute SQLite update and display saved status message for 2 seconds."""
        self._save_timeout_id = None
        if self.updating_ui or self.current_note_id is None or not self.crypto.is_unlocked:
            return GLib.SOURCE_REMOVE

        title = self.title_entry.get_text()
        start = self.text_buffer.get_start_iter()
        end = self.text_buffer.get_end_iter()
        content = self.text_buffer.get_text(start, end, True)

        self.db.update_note(self.current_note_id, title, content)
        row = self._find_row_by_id(self.current_note_id)
        if row:
            row.update_data(title, content)

        self._show_saved_status()
        return GLib.SOURCE_REMOVE

    def _flush_pending_save(self) -> None:
        """Immediately execute any pending auto-save before view change or exit."""
        if self._save_timeout_id is not None:
            GLib.source_remove(self._save_timeout_id)
            self._save_timeout_id = None
            self._do_save()

    def _show_saved_status(self) -> None:
        """Display 'Saved' for 2 seconds then disappear."""
        self.status_label.set_text("Saved")

        if self._status_clear_timeout_id is not None:
            GLib.source_remove(self._status_clear_timeout_id)
            self._status_clear_timeout_id = None

        self._status_clear_timeout_id = GLib.timeout_add(2000, self._clear_saved_status)

    def _clear_saved_status(self) -> bool:
        """Clear the saved status indicator."""
        self._status_clear_timeout_id = None
        self.status_label.set_text("")
        return GLib.SOURCE_REMOVE

    # --- Search & Actions ---

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Filter notes dynamically as the user types."""
        self.refresh_notes_list(query=entry.get_text())

    def _on_search_cleared(self, entry: Gtk.SearchEntry) -> None:
        """Reset search filter."""
        entry.set_text("")
        self.refresh_notes_list("")

    def create_new_note(self) -> None:
        """Create a new encrypted note and focus the title editor."""
        if not self.crypto.is_unlocked:
            return

        self._flush_pending_save()
        new_id = self.db.create_note(title="Untitled Note", content="")
        self.current_note_id = new_id
        self.search_entry.set_text("")
        self.refresh_notes_list("")

        row = self._find_row_by_id(new_id)
        if row:
            self.notes_list.select_row(row)

        self._show_saved_status()
        self.title_entry.grab_focus()
        self.title_entry.select_region(0, -1)

    def _update_row_copy_buttons(self) -> None:
        """Dynamically render an aligned copy button for every non-empty row in note content."""
        if not hasattr(self, "row_copy_box"):
            return

        while True:
            child = self.row_copy_box.get_first_child()
            if child is None:
                break
            self.row_copy_box.remove(child)

        if self.current_note_id is None:
            return

        start = self.text_buffer.get_start_iter()
        end = self.text_buffer.get_end_iter()
        text = self.text_buffer.get_text(start, end, True)
        if not text:
            return

        lines = text.splitlines()
        for idx, line in enumerate(lines):
            line_val = line.strip()
            if line_val:
                btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
                btn.add_css_class("flat")
                btn.add_css_class("circular")
                btn.add_css_class("row-copy-btn")
                btn.set_size_request(26, 26)
                btn.set_tooltip_text(f"Copy row {idx + 1}: {line_val}")
                btn.connect("clicked", lambda _, val=line_val, b=btn: self._copy_content_row(b, val))
                self.row_copy_box.append(btn)
            else:
                spacer = Gtk.Box()
                spacer.set_size_request(26, 26)
                self.row_copy_box.append(spacer)

    def _copy_content_row(self, button: Gtk.Button, text: str) -> None:
        """Copy specific row content to system clipboard with visual feedback."""
        if not text:
            return
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        button.set_icon_name("object-select-symbolic")
        GLib.timeout_add(1200, lambda: button.set_icon_name("edit-copy-symbolic") and False)
        display_preview = text if len(text) <= 32 else f"{text[:30]}..."
        self.show_toast(f'Copied: "{display_preview}"')

    def _on_delete_clicked(self, button: Gtk.Button) -> None:
        """Prompt confirmation and delete the active note."""
        if self.current_note_id is None:
            return

        note_id_to_delete = self.current_note_id

        def do_delete() -> None:
            if self._save_timeout_id is not None:
                GLib.source_remove(self._save_timeout_id)
                self._save_timeout_id = None
            if self._status_clear_timeout_id is not None:
                GLib.source_remove(self._status_clear_timeout_id)
                self._status_clear_timeout_id = None
            self.status_label.set_text("")

            self.db.delete_note(note_id_to_delete)
            self.current_note_id = None
            self.updating_ui = True
            self.title_entry.set_text("")
            self.text_buffer.set_text("")
            self.updating_ui = False
            self.refresh_notes_list()

        self._show_confirm_dialog(
            title="Delete Note?",
            body="Are you sure you want to permanently delete this note? This action cannot be undone.",
            on_confirm=do_delete
        )

    def _show_confirm_dialog(
        self,
        title: str,
        body: str,
        on_confirm: Callable[[], None]
    ) -> None:
        """Display an Adwaita confirmation dialog."""
        def on_response(_dlg: Any, response: str) -> None:
            if response == "delete":
                on_confirm()

        if hasattr(Adw, "AlertDialog"):
            dialog = Adw.AlertDialog(heading=title, body=body)
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("delete", "Delete")
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect("response", on_response)
            dialog.present(self)
        else:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading=title,
                body=body
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("delete", "Delete")
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect("response", on_response)
            dialog.present()

    # --- Pure Encrypted Binary .asd Import & Export Engine ---

    def export_encrypted_vault(self) -> None:
        """
        Export all notes to a fully encrypted binary .asd file.
        The entire payload is encrypted with AES-256 (Fernet) — zero plaintext,
        zero JSON keys or columns are stored on disk.
        Format: [4 bytes MAGIC (b"ASD\\x01")] + [16 bytes SALT] + [Fernet CIPHERTEXT]
        """
        if not self.crypto.is_unlocked or self.crypto.fernet is None:
            return

        notes = self.db.get_notes()
        if not notes:
            self.show_toast("No notes available to export.")
            return

        # Prepare payload in memory
        notes_payload = [
            {
                "title": n["title"],
                "content": n["content"],
                "updated_at": n.get("updated_at", "")
            }
            for n in notes
        ]
        raw_json_bytes = json.dumps(notes_payload, ensure_ascii=False).encode("utf-8")

        # Encrypt the entire payload with the vault's master Fernet cipher
        try:
            ciphertext_bytes = self.crypto.fernet.encrypt(raw_json_bytes)
        except Exception as e:
            self.show_toast(f"Encryption failed: {e}")
            return

        salt, _ = self.db.get_master_credentials()
        if not salt or len(salt) != 16:
            self.show_toast("Export error: Master salt not found.")
            return

        # Pure binary container: Magic (4) + Salt (16) + Ciphertext
        asd_binary_data = ASD_MAGIC + salt + ciphertext_bytes

        dialog = Gtk.FileDialog(title="Export Asd Encrypted Vault (.asd)")
        today_str = datetime.now().strftime("%Y-%m-%d")
        dialog.set_initial_name(f"asd_backup_{today_str}.asd")

        asd_filter = Gtk.FileFilter()
        asd_filter.set_name("Asd Encrypted Vault (*.asd)")
        asd_filter.add_pattern("*.asd")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(asd_filter)
        dialog.set_filters(filters)

        def on_save_finish(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                gfile = dlg.save_finish(result)
                if not gfile:
                    return
                path = gfile.get_path()
                if not path:
                    return

                if not path.endswith(".asd"):
                    path += ".asd"

                with open(path, "wb") as f:
                    f.write(asd_binary_data)
                try:
                    os.chmod(path, 0o600)
                except Exception:
                    pass

                self.show_toast(f"Successfully exported {len(notes)} notes to .asd backup")
            except GLib.GError as err:
                if err.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    return
                self.show_toast(f"Export error: {err.message}")
            except Exception as exc:
                self.show_toast(f"Export failed: {exc}")

        dialog.save(self, None, on_save_finish)

    def import_encrypted_vault(self) -> None:
        """Import notes from an encrypted binary .asd backup file."""
        if not self.crypto.is_unlocked:
            return

        dialog = Gtk.FileDialog(title="Import Asd Encrypted Vault (.asd)")

        asd_filter = Gtk.FileFilter()
        asd_filter.set_name("Asd Encrypted Vault (*.asd)")
        asd_filter.add_pattern("*.asd")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(asd_filter)
        dialog.set_filters(filters)

        def on_open_finish(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                gfile = dlg.open_finish(result)
                if not gfile:
                    return
                path = gfile.get_path()
                if not path:
                    return

                self._process_asd_import_file(path)
            except GLib.GError as err:
                if err.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    return
                self.show_toast(f"Import error: {err.message}")
            except Exception as exc:
                self.show_toast(f"Import failed: {exc}")

        dialog.open(self, None, on_open_finish)

    def _process_asd_import_file(self, path: str) -> None:
        """
        Process the encrypted binary .asd file.
        Format: [4 bytes ASD_MAGIC] + [16 bytes SALT] + [Fernet CIPHERTEXT]
        """
        MAX_ASD_IMPORT_BYTES: int = 50 * 1024 * 1024  # 50 MB safety threshold
        try:
            if os.path.getsize(path) > MAX_ASD_IMPORT_BYTES:
                self.show_toast("Import error: File exceeds maximum allowed size (50 MB).")
                return
            with open(path, "rb") as f:
                raw_data = f.read()
        except Exception as exc:
            self.show_toast(f"Failed to read file: {exc}")
            return

        if not raw_data.startswith(ASD_MAGIC) or len(raw_data) < 24:
            self.show_toast("Invalid file: Not a valid .asd encrypted backup.")
            return

        salt = raw_data[4:20]
        ciphertext = raw_data[20:]

        # Try decrypting with active vault's key first
        try:
            assert self.crypto.fernet is not None
            decrypted_bytes = self.crypto.fernet.decrypt(ciphertext)
            self._insert_imported_notes(decrypted_bytes.decode("utf-8"))
            return
        except Exception:
            # Key differs: prompt user for the backup password
            self._prompt_asd_backup_password(ciphertext, salt)

    def _prompt_asd_backup_password(self, ciphertext: bytes, salt: bytes) -> None:
        """Prompt user for the master password used when creating this .asd backup."""
        dialog = Adw.AlertDialog(
            heading="Enter Backup Password",
            body="This .asd backup was encrypted with a master password from another vault. "
                 "Please enter the password used to create it:"
        )

        pwd_entry = Gtk.PasswordEntry(placeholder_text="Backup Password")
        dialog.set_extra_child(pwd_entry)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("unlock", "Decrypt & Import")
        dialog.set_response_appearance("unlock", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("unlock")
        dialog.set_close_response("cancel")

        def on_response(_dlg: Any, response: str) -> None:
            if response != "unlock":
                return

            pwd = pwd_entry.get_text()
            if not pwd:
                self.show_toast("Password cannot be empty.")
                return

            try:
                backup_key = CryptoManager.derive_key(pwd, salt)
                backup_fernet = Fernet(backup_key)
                decrypted_bytes = backup_fernet.decrypt(ciphertext)
                decrypted_json = decrypted_bytes.decode("utf-8")
                self._insert_imported_notes(decrypted_json)
            except (InvalidToken, Exception):
                self.show_toast("Decryption failed: Incorrect password for this .asd file.")

        dialog.connect("response", on_response)
        dialog.present(self)

    def _insert_imported_notes(self, raw_json: str) -> None:
        """Parse decrypted JSON note list and persist to the current vault."""
        try:
            notes = json.loads(raw_json)
        except Exception as e:
            self.show_toast(f"Corrupt backup content: {e}")
            return

        if not isinstance(notes, list):
            self.show_toast("Backup content is invalid.")
            return

        count = 0
        for item in notes:
            if isinstance(item, dict):
                title = str(item.get("title", "Untitled Note"))
                content = str(item.get("content", ""))
                self.db.create_note(title, content)
                count += 1

        self.refresh_notes_list()
        self.show_toast(f"Successfully imported {count} notes from .asd backup")
