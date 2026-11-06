#!/usr/bin/env python3
"""
database.py — SQLite storage manager with transparent encryption/decryption for Asd.

Stores encrypted master credentials in 'meta', AES-encrypted notes in 'notes',
pinned favorites in 'favorites', and manages cloud synchronization metadata.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple
from gi.repository import GLib

from crypto import CryptoManager


class DatabaseManager:
    """
    Manages SQLite storage for Asd.
    Encrypts note titles and contents transparently before persistence.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        crypto: Optional[CryptoManager] = None
    ) -> None:
        if db_path is None:
            user_data_dir = GLib.get_user_data_dir()
            app_dir = os.path.join(user_data_dir, "asd")
            os.makedirs(app_dir, mode=0o700, exist_ok=True)
            try:
                os.chmod(app_dir, 0o700)
            except Exception:
                pass
            db_path = os.path.join(app_dir, "notes.db")

        self.db_path = db_path
        self.crypto = crypto if crypto is not None else CryptoManager()

        # Connect to SQLite database
        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=10.0
        )
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self.enforce_file_permissions()

    def _init_schema(self) -> None:
        """Create necessary tables, apply WAL journal mode, and enforce secure delete."""
        with self.conn:
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = NORMAL;")
            self.conn.execute("PRAGMA secure_delete = ON;")
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL
                );
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_deleted INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    note_id INTEGER PRIMARY KEY,
                    position INTEGER NOT NULL,
                    FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
                );
                """
            )

            # Migration: Ensure existing tables have uuid and is_deleted columns
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA table_info(notes)")
            cols = [col["name"] for col in cursor.fetchall()]

            if "uuid" not in cols:
                self.conn.execute("ALTER TABLE notes ADD COLUMN uuid TEXT")
            if "is_deleted" not in cols:
                self.conn.execute("ALTER TABLE notes ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")

            # Backfill any existing notes lacking a UUID
            cursor.execute("SELECT id FROM notes WHERE uuid IS NULL OR uuid = ''")
            rows = cursor.fetchall()
            for r in rows:
                new_uuid = str(uuid.uuid4())
                self.conn.execute("UPDATE notes SET uuid = ? WHERE id = ?", (new_uuid, r["id"]))

            self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_uuid ON notes(uuid)")

    def is_initialized(self) -> bool:
        """Check if salt and verify_token exist in the meta table."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM meta WHERE key IN ('salt', 'verify_token')"
        )
        row = cursor.fetchone()
        return bool(row and row[0] == 2)

    def save_master_credentials(self, salt: bytes, verify_token: bytes) -> None:
        """Store the PBKDF2 salt and Fernet verify_token as BLOBs."""
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('salt', ?)",
                (sqlite3.Binary(salt),)
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('verify_token', ?)",
                (sqlite3.Binary(verify_token),)
            )

    def get_master_credentials(self) -> Tuple[Optional[bytes], Optional[bytes]]:
        """Retrieve the stored salt and verify_token BLOBs."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM meta WHERE key IN ('salt', 'verify_token')")
        rows = cursor.fetchall()
        meta_dict = {row["key"]: bytes(row["value"]) for row in rows}
        return meta_dict.get("salt"), meta_dict.get("verify_token")

    # --- Sync Settings & Metadata Storage in 'meta' ---

    def get_meta_string(self, key: str, default: str = "") -> str:
        """Retrieve a string configuration value from meta table."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row and row["value"]:
            try:
                return bytes(row["value"]).decode("utf-8")
            except Exception:
                return default
        return default

    def set_meta_string(self, key: str, value: str) -> None:
        """Store a string configuration value in meta table."""
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, sqlite3.Binary(value.encode("utf-8")))
            )

    def get_sync_settings(self) -> Dict[str, Any]:
        """Retrieve cloud sync configuration."""
        url = self.get_meta_string("sync_url", "")
        api_key = self.get_meta_string("sync_api_key", "")
        auto_sync = self.get_meta_string("sync_auto", "false").lower() == "true"
        last_sync = self.get_meta_string("sync_last_time", "")
        return {
            "url": url,
            "api_key": api_key,
            "auto_sync": auto_sync,
            "last_sync": last_sync,
        }

    def save_sync_settings(self, url: str, api_key: str, auto_sync: bool) -> None:
        """Save cloud sync configuration."""
        self.set_meta_string("sync_url", url.strip())
        self.set_meta_string("sync_api_key", api_key.strip())
        self.set_meta_string("sync_auto", "true" if auto_sync else "false")

    def create_note(
        self,
        title: str = "Untitled Note",
        content: str = "",
        note_uuid: Optional[str] = None
    ) -> int:
        """
        Encrypt and insert a new note into the database.
        Returns the new note's ID.
        """
        enc_title = self.crypto.encrypt(title)
        enc_content = self.crypto.encrypt(content)
        u = note_uuid if note_uuid else str(uuid.uuid4())

        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO notes (uuid, title, content, updated_at, is_deleted)
                VALUES (?, ?, ?, strftime('%Y-%m-%d %H:%M:%S', 'now'), 0)
                """,
                (u, enc_title, enc_content)
            )
            return int(cursor.lastrowid)

    def update_note(self, note_id: int, title: str, content: str) -> None:
        """Encrypt and update an existing note's title and content."""
        enc_title = self.crypto.encrypt(title)
        enc_content = self.crypto.encrypt(content)

        with self.conn:
            self.conn.execute(
                """
                UPDATE notes
                SET title = ?, content = ?, updated_at = strftime('%Y-%m-%d %H:%M:%S', 'now')
                WHERE id = ?
                """,
                (enc_title, enc_content, note_id)
            )

    def delete_note(self, note_id: int) -> None:
        """
        Soft delete note (set is_deleted = 1) so deletions sync across devices,
        and clean up favorites.
        """
        with self.conn:
            self.conn.execute("DELETE FROM favorites WHERE note_id = ?", (note_id,))
            self.conn.execute(
                """
                UPDATE notes
                SET is_deleted = 1, updated_at = strftime('%Y-%m-%d %H:%M:%S', 'now')
                WHERE id = ?
                """,
                (note_id,)
            )
            cursor = self.conn.cursor()
            cursor.execute("SELECT note_id FROM favorites ORDER BY position ASC")
            remaining = cursor.fetchall()
            for idx, r in enumerate(remaining):
                self.conn.execute(
                    "UPDATE favorites SET position = ? WHERE note_id = ?",
                    (idx, r["note_id"])
                )

    def get_note(self, note_id: int) -> Optional[Dict[str, Any]]:
        """Fetch and decrypt a specific note by ID."""
        if not self.crypto.is_unlocked:
            return None

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, uuid, title, content, updated_at, is_deleted FROM notes WHERE id = ? AND is_deleted = 0",
            (note_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        try:
            dec_title = self.crypto.decrypt(row["title"])
            dec_content = self.crypto.decrypt(row["content"])
        except Exception:
            dec_title = "[Decryption Error]"
            dec_content = ""

        return {
            "id": row["id"],
            "uuid": row["uuid"],
            "title": dec_title,
            "content": dec_content,
            "updated_at": row["updated_at"],
            "is_deleted": row["is_deleted"],
        }

    # --- Favorites Management (Up to 10 pinned notes) ---

    def get_favorite_ids(self) -> List[int]:
        """Return ordered list of up to 10 favorite note IDs."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT f.note_id
            FROM favorites f
            JOIN notes n ON f.note_id = n.id
            WHERE n.is_deleted = 0
            ORDER BY f.position ASC
            LIMIT 10
            """
        )
        return [row["note_id"] for row in cursor.fetchall()]

    def is_favorite(self, note_id: int) -> bool:
        """Check if a note_id is currently pinned in favorites."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM favorites WHERE note_id = ?", (note_id,))
        return cursor.fetchone() is not None

    def add_favorite(self, note_id: int) -> bool:
        """Add note_id to favorites if fewer than 10 favorites exist. Returns True if added."""
        favs = self.get_favorite_ids()
        if note_id in favs:
            return True
        if len(favs) >= 10:
            return False
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO favorites (note_id, position) VALUES (?, ?)",
                (note_id, len(favs))
            )
        return True

    def remove_favorite(self, note_id: int) -> bool:
        """Remove note_id from favorites and re-index remaining positions."""
        with self.conn:
            self.conn.execute("DELETE FROM favorites WHERE note_id = ?", (note_id,))
            cursor = self.conn.cursor()
            cursor.execute("SELECT note_id FROM favorites ORDER BY position ASC")
            remaining = cursor.fetchall()
            for idx, row in enumerate(remaining):
                self.conn.execute(
                    "UPDATE favorites SET position = ? WHERE note_id = ?",
                    (idx, row["note_id"])
                )
        return True

    def get_favorite_notes(self) -> List[Dict[str, Any]]:
        """Return decrypted favorite notes ordered by position (up to 10)."""
        if not self.crypto.is_unlocked:
            return []
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT n.id, n.uuid, n.title, n.content, n.updated_at, f.position
            FROM favorites f
            JOIN notes n ON f.note_id = n.id
            WHERE n.is_deleted = 0
            ORDER BY f.position ASC
            LIMIT 10
            """
        )
        rows = cursor.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            try:
                dec_title = self.crypto.decrypt(row["title"])
                dec_content = self.crypto.decrypt(row["content"])
            except Exception:
                dec_title = "[Decryption Error]"
                dec_content = ""
            results.append({
                "id": row["id"],
                "uuid": row["uuid"],
                "title": dec_title,
                "content": dec_content,
                "updated_at": row["updated_at"],
                "position": row["position"],
            })
        return results

    def get_notes(self, search_query: str = "") -> List[Dict[str, Any]]:
        """
        Fetch all active notes, decrypt their titles and contents in memory,
        and optionally filter case-insensitively by search_query.
        Ordered by relevance score DESC, then updated_at DESC, id DESC.
        """
        if not self.crypto.is_unlocked:
            return []

        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, uuid, title, content, updated_at, is_deleted
            FROM notes
            WHERE is_deleted = 0
            ORDER BY updated_at DESC, id DESC
            """
        )
        rows = cursor.fetchall()

        query_str = search_query.strip().lower() if search_query else ""
        query_tokens = [t for t in query_str.split() if t]
        results: List[Dict[str, Any]] = []

        for row in rows:
            try:
                dec_title = self.crypto.decrypt(row["title"])
                dec_content = self.crypto.decrypt(row["content"])
            except Exception:
                continue

            score = 0
            if query_tokens:
                title_lower = dec_title.lower()
                content_lower = dec_content.lower()
                combined_lower = f"{title_lower} {content_lower}"

                # Multi-term token matching: every query word must match somewhere in title or content
                if not all(token in combined_lower for token in query_tokens):
                    continue

                if query_str in title_lower:
                    score += 1000
                elif query_str in content_lower:
                    score += 500

                if all(token in title_lower for token in query_tokens):
                    score += 300

                if any(title_lower.startswith(token) for token in query_tokens):
                    score += 150

                for token in query_tokens:
                    if token in title_lower:
                        score += 50

                for token in query_tokens:
                    if token in content_lower:
                        score += 10

            results.append({
                "id": row["id"],
                "uuid": row["uuid"],
                "title": dec_title,
                "content": dec_content,
                "updated_at": row["updated_at"],
                "_score": score,
            })

        if query_tokens:
            results.sort(key=lambda item: (item["_score"], item["updated_at"], item["id"]), reverse=True)

        for item in results:
            item.pop("_score", None)

        return results

    # --- Cloud Sync Operations ---

    def get_notes_for_sync(self, since: str = "") -> List[Dict[str, Any]]:
        """
        Retrieve notes (including soft-deleted tombstones) modified since 'since'
        in raw encrypted ciphertext form for cloud synchronization.
        """
        cursor = self.conn.cursor()
        if since:
            cursor.execute(
                """
                SELECT uuid, title, content, updated_at, is_deleted
                FROM notes
                WHERE updated_at > ?
                ORDER BY updated_at ASC
                """,
                (since,)
            )
        else:
            cursor.execute(
                """
                SELECT uuid, title, content, updated_at, is_deleted
                FROM notes
                ORDER BY updated_at ASC
                """
            )

        rows = cursor.fetchall()
        payload = []
        for r in rows:
            payload.append({
                "uuid": r["uuid"],
                "enc_title": r["title"],
                "enc_content": r["content"],
                "updated_at": r["updated_at"],
                "is_deleted": bool(r["is_deleted"]),
            })
        return payload

    def apply_remote_sync_note(
        self,
        note_uuid: str,
        enc_title: str,
        enc_content: str,
        updated_at: str,
        is_deleted: bool
    ) -> bool:
        """
        Apply a remote note change from the server.
        Rule: "last updated_at wins".
        Returns True if a local record was inserted or updated.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, updated_at, is_deleted FROM notes WHERE uuid = ?", (note_uuid,))
        existing = cursor.fetchone()

        del_int = 1 if is_deleted else 0

        with self.conn:
            if existing:
                local_updated_at = existing["updated_at"]
                # If local version is newer than remote version, local wins
                if local_updated_at and local_updated_at > updated_at:
                    return False

                # Remote version is newer or equal: update local
                self.conn.execute(
                    """
                    UPDATE notes
                    SET title = ?, content = ?, updated_at = ?, is_deleted = ?
                    WHERE uuid = ?
                    """,
                    (enc_title, enc_content, updated_at, del_int, note_uuid)
                )
                if is_deleted:
                    self.conn.execute("DELETE FROM favorites WHERE note_id = ?", (existing["id"],))
                return True
            else:
                # Insert new note from remote
                self.conn.execute(
                    """
                    INSERT INTO notes (uuid, title, content, updated_at, is_deleted)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (note_uuid, enc_title, enc_content, updated_at, del_int)
                )
                return True

    def enforce_file_permissions(self) -> None:
        """Ensure the database directory (0700) and database files (0600) have strict POSIX permissions."""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if os.path.isdir(db_dir):
            try:
                os.chmod(db_dir, 0o700)
            except Exception:
                pass

        for ext in ("", "-wal", "-shm"):
            fpath = f"{self.db_path}{ext}"
            if os.path.exists(fpath):
                try:
                    os.chmod(fpath, 0o600)
                except Exception:
                    pass

    def close(self) -> None:
        """Close the SQLite connection and re-enforce strict permissions."""
        try:
            self.conn.close()
        except Exception:
            pass
        self.enforce_file_permissions()
