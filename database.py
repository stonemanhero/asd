#!/usr/bin/env python3
"""
database.py — SQLite storage manager with transparent encryption/decryption for Asd.

Stores encrypted master credentials in 'meta' and AES-encrypted notes in 'notes'.
"""

from __future__ import annotations

import os
import sqlite3
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
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

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

    def create_note(self, title: str = "Untitled Note", content: str = "") -> int:
        """
        Encrypt and insert a new note into the database.
        Returns the new note's ID.
        """
        enc_title = self.crypto.encrypt(title)
        enc_content = self.crypto.encrypt(content)

        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO notes (title, content, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (enc_title, enc_content)
            )
            return int(cursor.lastrowid)

    def update_note(self, note_id: int, title: str, content: str) -> None:
        """Encrypt and update an existing note's title and content."""
        enc_title = self.crypto.encrypt(title)
        enc_content = self.crypto.encrypt(content)

        with self.conn:
            self.conn.execute(
                "UPDATE notes SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (enc_title, enc_content, note_id)
            )

    def delete_note(self, note_id: int) -> None:
        """Permanently delete a note by ID."""
        with self.conn:
            self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def get_note(self, note_id: int) -> Optional[Dict[str, Any]]:
        """Fetch and decrypt a specific note by ID."""
        if not self.crypto.is_unlocked:
            return None

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, title, content, updated_at FROM notes WHERE id = ?",
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
            "title": dec_title,
            "content": dec_content,
            "updated_at": row["updated_at"],
        }

    def get_notes(self, search_query: str = "") -> List[Dict[str, Any]]:
        """
        Fetch all notes, decrypt their titles and contents in memory,
        and optionally filter case-insensitively by search_query.
        Supports multi-term tokenized search (all terms matched across title and content)
        with relevance scoring (exact phrase match, title matches, term frequency).
        Ordered by relevance score DESC, then updated_at DESC, id DESC.
        """
        if not self.crypto.is_unlocked:
            return []

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, title, content, updated_at FROM notes ORDER BY updated_at DESC, id DESC"
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

                # Relevance scoring:
                # 1. Exact full query in title (+1000)
                if query_str in title_lower:
                    score += 1000
                # 2. Exact full query in content (+500)
                elif query_str in content_lower:
                    score += 500

                # 3. All tokens in title (+300)
                if all(token in title_lower for token in query_tokens):
                    score += 300

                # 4. Title starts with any token (+150)
                if any(title_lower.startswith(token) for token in query_tokens):
                    score += 150

                # 5. Token counts in title (+50 per token match)
                for token in query_tokens:
                    if token in title_lower:
                        score += 50

                # 6. Token counts in content (+10 per token match)
                for token in query_tokens:
                    if token in content_lower:
                        score += 10

            results.append({
                "id": row["id"],
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
