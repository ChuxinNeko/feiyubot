"""SQLite 存储。全部群聊与网页对话都写在这里，进程重启后仍在。"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from feiyubot.core.models import (
    DEFAULT_PERSONA_NAME,
    DEFAULT_PERSONA_PROMPT,
    ChatMessage,
    Persona,
    Provider,
    ProviderHealth,
    Session,
    Settings,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    return (moment or utcnow()).isoformat()


def new_id() -> str:
    return secrets.token_hex(6)


def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••"
    return secret[:3] + "••••" + secret[-4:]


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS providers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                timeout_seconds REAL NOT NULL DEFAULT 60,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_health (
                provider_id TEXT PRIMARY KEY,
                ok INTEGER,
                last_error TEXT NOT NULL DEFAULT '',
                last_checked_at TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                cooldown_until TEXT
            );
            CREATE TABLE IF NOT EXISTS personas (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                group_id TEXT,
                persona_id TEXT,
                wake_mode TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                summary TEXT NOT NULL DEFAULT '',
                summary_until_id INTEGER NOT NULL DEFAULT 0,
                memory_notes TEXT NOT NULL DEFAULT '',
                memory_until_id INTEGER NOT NULL DEFAULT 0,
                knowledge TEXT NOT NULL DEFAULT '',
                last_reply_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sender_id TEXT,
                sender_name TEXT,
                notice INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ling_atoms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                level INTEGER NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                strength REAL NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0,
                last_hit_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ling_affinity (
                subject TEXT PRIMARY KEY,
                score REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ling_diary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                body TEXT NOT NULL,
                mood TEXT NOT NULL DEFAULT '',
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ling_dreams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                night_key TEXT NOT NULL,
                body TEXT NOT NULL,
                level INTEGER NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(ling_atoms)")}
        if "injected_at" not in columns:
            self._conn.execute("ALTER TABLE ling_atoms ADD COLUMN injected_at TEXT")
            self._conn.commit()

    def ensure_defaults(self, admin_password: str | None, password_file: Path | None = None) -> str | None:
        """补齐默认人格和初始密码。返回仅在自动生成密码时的明文，调用方负责落盘。"""
        generated: str | None = None
        with self._lock:
            if not self._meta("password_hash"):
                password = admin_password or ""
                if not password:
                    password = secrets.token_urlsafe(9)
                    generated = password
                self._set_meta("password_hash", _hash_password(password))
            if self._conn.execute("SELECT COUNT(*) AS n FROM personas").fetchone()["n"] == 0:
                now = iso()
                self._conn.execute(
                    """
                    INSERT INTO personas (id, name, prompt, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (new_id(), DEFAULT_PERSONA_NAME, DEFAULT_PERSONA_PROMPT, now, now),
                )
            self._conn.commit()
        if generated and password_file is not None:
            password_file.write_text(generated + "\n", encoding="utf-8")
            try:
                password_file.chmod(0o600)
            except OSError:
                pass
        return generated

    def verify_password(self, password: str) -> bool:
        with self._lock:
            stored = self._meta("password_hash") or ""
        if not stored or ":" not in stored:
            return False
        salt, digest = stored.split(":", 1)
        candidate = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return secrets.compare_digest(candidate, digest)

    def set_password(self, password: str) -> None:
        if len(password) < 4:
            raise ValueError("密码至少 4 位")
        with self._lock:
            self._set_meta("password_hash", _hash_password(password))
            self._conn.execute("DELETE FROM admin_sessions")
            self._conn.commit()

    def create_admin_session(self) -> str:
        token = secrets.token_urlsafe(32)
        now = utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO admin_sessions (token, created_at, expires_at) VALUES (?, ?, ?)",
                (token, iso(now), iso(now + timedelta(days=7))),
            )
            self._conn.commit()
        return token

    def admin_session_valid(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT expires_at FROM admin_sessions WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                return False
            if row["expires_at"] < iso():
                self._conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
                self._conn.commit()
                return False
        return True

    def delete_admin_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
            self._conn.commit()

    def get_settings(self) -> Settings:
        with self._lock:
            raw = self._meta("settings")
        if not raw:
            return Settings()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return Settings()
        return Settings.from_dict(data if isinstance(data, dict) else {})

    def save_settings(self, settings: Settings) -> Settings:
        normalized = Settings.from_dict(settings.to_dict())
        with self._lock:
            self._set_meta("settings", json.dumps(normalized.to_dict(), ensure_ascii=False))
            self._conn.commit()
        return normalized

    def add_event(self, level: str, message: str) -> None:
        text = message.replace("\n", " ")[:500]
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (level, message, created_at) VALUES (?, ?, ?)",
                (level, text, iso()),
            )
            self._conn.execute(
                """
                DELETE FROM events WHERE id NOT IN (
                    SELECT id FROM events ORDER BY id DESC LIMIT 500
                )
                """
            )
            self._conn.commit()

    def list_events(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT level, message, created_at FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_providers(self) -> list[Provider]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM providers ORDER BY priority ASC, name ASC"
            ).fetchall()
        return [_provider(row) for row in rows]

    def get_provider(self, provider_id: str) -> Provider | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        return _provider(row) if row else None

    def upsert_provider(
        self,
        *,
        provider_id: str | None,
        name: str,
        base_url: str,
        api_key: str | None,
        model: str,
        enabled: bool,
        priority: int,
        timeout_seconds: float,
    ) -> Provider:
        name = name.strip()
        model = model.strip()
        base_url = base_url.strip()
        if not name:
            raise ValueError("请填写提供商名称")
        if not model:
            raise ValueError("请填写模型名")
        _validate_base_url(base_url)
        now = iso()
        with self._lock:
            existing = None
            if provider_id:
                existing = self._conn.execute(
                    "SELECT * FROM providers WHERE id = ?", (provider_id,)
                ).fetchone()
            if existing is None:
                provider_id = new_id()
                secret = (api_key or "").strip()
                self._conn.execute(
                    """
                    INSERT INTO providers (
                        id, name, base_url, api_key, model, enabled, priority,
                        timeout_seconds, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        provider_id,
                        name,
                        base_url,
                        secret,
                        model,
                        int(enabled),
                        int(priority),
                        float(timeout_seconds),
                        now,
                        now,
                    ),
                )
            else:
                secret = existing["api_key"] if api_key is None else api_key.strip()
                self._conn.execute(
                    """
                    UPDATE providers
                    SET name = ?, base_url = ?, api_key = ?, model = ?, enabled = ?,
                        priority = ?, timeout_seconds = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        base_url,
                        secret,
                        model,
                        int(enabled),
                        int(priority),
                        float(timeout_seconds),
                        now,
                        existing["id"],
                    ),
                )
                provider_id = existing["id"]
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        return _provider(row)

    def delete_provider(self, provider_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
            self._conn.execute("DELETE FROM provider_health WHERE provider_id = ?", (provider_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def list_health(self) -> list[ProviderHealth]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM provider_health").fetchall()
        return [_health(row) for row in rows]

    def mark_provider_ok(self, provider_id: str) -> None:
        now = iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO provider_health (
                    provider_id, ok, last_error, last_checked_at, consecutive_failures, cooldown_until
                ) VALUES (?, 1, '', ?, 0, NULL)
                ON CONFLICT(provider_id) DO UPDATE SET
                    ok = 1,
                    last_error = '',
                    last_checked_at = excluded.last_checked_at,
                    consecutive_failures = 0,
                    cooldown_until = NULL
                """,
                (provider_id, now),
            )
            self._conn.commit()

    def mark_provider_failed(self, provider_id: str, error: str, *, cooldown_seconds: int = 60) -> None:
        now = utcnow()
        with self._lock:
            row = self._conn.execute(
                "SELECT consecutive_failures FROM provider_health WHERE provider_id = ?",
                (provider_id,),
            ).fetchone()
            failures = (row["consecutive_failures"] if row else 0) + 1
            cooldown = iso(now + timedelta(seconds=cooldown_seconds)) if failures >= 3 else None
            self._conn.execute(
                """
                INSERT INTO provider_health (
                    provider_id, ok, last_error, last_checked_at, consecutive_failures, cooldown_until
                ) VALUES (?, 0, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    ok = 0,
                    last_error = excluded.last_error,
                    last_checked_at = excluded.last_checked_at,
                    consecutive_failures = excluded.consecutive_failures,
                    cooldown_until = excluded.cooldown_until
                """,
                (provider_id, error[:300], iso(now), failures, cooldown),
            )
            self._conn.commit()

    def list_personas(self) -> list[Persona]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM personas ORDER BY is_active DESC, name ASC"
            ).fetchall()
        return [_persona(row) for row in rows]

    def get_persona(self, persona_id: str) -> Persona | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        return _persona(row) if row else None

    def active_persona(self) -> Persona | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM personas WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                row = self._conn.execute("SELECT * FROM personas ORDER BY name ASC LIMIT 1").fetchone()
        return _persona(row) if row else None

    def upsert_persona(self, *, persona_id: str | None, name: str, prompt: str, activate: bool) -> Persona:
        name = name.strip()
        prompt = prompt.strip()
        if not name:
            raise ValueError("请填写人格名称")
        if not prompt:
            raise ValueError("请填写人格提示词")
        now = iso()
        with self._lock:
            existing = None
            if persona_id:
                existing = self._conn.execute(
                    "SELECT * FROM personas WHERE id = ?", (persona_id,)
                ).fetchone()
            if activate:
                self._conn.execute("UPDATE personas SET is_active = 0")
            if existing is None:
                persona_id = new_id()
                is_active = 1 if activate or self._conn.execute("SELECT COUNT(*) AS n FROM personas").fetchone()["n"] == 0 else 0
                if is_active:
                    self._conn.execute("UPDATE personas SET is_active = 0")
                self._conn.execute(
                    """
                    INSERT INTO personas (id, name, prompt, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (persona_id, name, prompt, is_active, now, now),
                )
            else:
                is_active = 1 if activate else existing["is_active"]
                self._conn.execute(
                    """
                    UPDATE personas SET name = ?, prompt = ?, is_active = ?, updated_at = ? WHERE id = ?
                    """,
                    (name, prompt, is_active, now, existing["id"]),
                )
                persona_id = existing["id"]
            if self._conn.execute("SELECT COUNT(*) AS n FROM personas WHERE is_active = 1").fetchone()["n"] == 0:
                self._conn.execute(
                    "UPDATE personas SET is_active = 1 WHERE id = ?",
                    (persona_id,),
                )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        return _persona(row)

    def activate_persona(self, persona_id: str) -> Persona | None:
        now = iso()
        with self._lock:
            row = self._conn.execute("SELECT id FROM personas WHERE id = ?", (persona_id,)).fetchone()
            if row is None:
                return None
            self._conn.execute("UPDATE personas SET is_active = 0")
            self._conn.execute(
                "UPDATE personas SET is_active = 1, updated_at = ? WHERE id = ?",
                (now, persona_id),
            )
            self._conn.commit()
            saved = self._conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        return _persona(saved)

    def delete_persona(self, persona_id: str) -> bool:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) AS n FROM personas").fetchone()["n"]
            if count <= 1:
                raise ValueError("至少保留一个人格")
            row = self._conn.execute(
                "SELECT is_active FROM personas WHERE id = ?", (persona_id,)
            ).fetchone()
            if row is None:
                return False
            self._conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
            if row["is_active"]:
                replacement = self._conn.execute("SELECT id FROM personas ORDER BY name ASC LIMIT 1").fetchone()
                if replacement:
                    self._conn.execute(
                        "UPDATE personas SET is_active = 1 WHERE id = ?", (replacement["id"],)
                    )
            self._conn.commit()
        return True

    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return _session(row) if row else None

    def ensure_session(
        self,
        session_id: str,
        *,
        kind: str,
        title: str,
        group_id: str | None = None,
    ) -> Session:
        now = iso()
        title = (title or session_id).strip()[:80]
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO sessions (
                        id, kind, title, group_id, persona_id, wake_mode, enabled, summary,
                        summary_until_id, memory_notes, memory_until_id, knowledge, last_reply_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, NULL, NULL, 1, '', 0, '', 0, '', NULL, ?, ?)
                    """,
                    (session_id, kind, title, group_id, now, now),
                )
            else:
                placeholder = str(row["title"]).startswith("群 ") or row["title"] == row["id"]
                if title and row["title"] != title and placeholder:
                    self._conn.execute(
                        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                        (title, now, session_id),
                    )
            self._conn.commit()
            saved = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return _session(saved)

    def update_session(self, session_id: str, **fields: object) -> Session | None:
        allowed = {
            "title",
            "persona_id",
            "wake_mode",
            "enabled",
            "summary",
            "summary_until_id",
            "memory_notes",
            "memory_until_id",
            "knowledge",
            "last_reply_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError("不能修改这些字段: " + ", ".join(sorted(unknown)))
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            assignments = []
            values: list[object] = []
            for key, value in fields.items():
                if key == "enabled":
                    value = int(bool(value))
                if key == "title" and isinstance(value, str):
                    value = value.strip()[:80] or row["title"]
                if key in {"summary", "memory_notes", "knowledge"} and isinstance(value, str):
                    value = value[:20000]
                if key == "wake_mode" and value not in {None, "", "at", "always", "keyword"}:
                    raise ValueError("唤醒方式无效")
                if key == "wake_mode" and value == "":
                    value = None
                if key == "persona_id" and value == "":
                    value = None
                assignments.append(f"{key} = ?")
                values.append(value)
            assignments.append("updated_at = ?")
            values.append(iso())
            values.append(session_id)
            self._conn.execute(
                f"UPDATE sessions SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            saved = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return _session(saved)

    def list_sessions(self, kind: str | None = None) -> list[dict]:
        query = """
            SELECT s.*, (
                SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id
            ) AS message_count
            FROM sessions s
        """
        args: tuple = ()
        if kind:
            query += " WHERE s.kind = ?"
            args = (kind,)
        query += " ORDER BY s.updated_at DESC"
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        result = []
        for row in rows:
            session = _session(row)
            item = _public_session(session)
            item["message_count"] = row["message_count"]
            result.append(item)
        return result

    def add_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        sender_id: str | None = None,
        sender_name: str | None = None,
        notice: bool = False,
    ) -> ChatMessage:
        now = iso()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO messages (
                    session_id, role, content, sender_id, sender_name, notice, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, sender_id, sender_name, int(notice), now),
            )
            self._conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _message(row)

    def list_messages(self, session_id: str, *, limit: int = 100, before_id: int | None = None) -> list[ChatMessage]:
        limit = max(1, min(limit, 500))
        with self._lock:
            if before_id is None:
                rows = self._conn.execute(
                    """
                    SELECT * FROM messages WHERE session_id = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM messages WHERE session_id = ? AND id < ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (session_id, before_id, limit),
                ).fetchall()
        return [_message(row) for row in reversed(rows)]

    def messages_after(self, session_id: str, after_id: int, *, include_notices: bool = False) -> list[ChatMessage]:
        query = "SELECT * FROM messages WHERE session_id = ? AND id > ?"
        if not include_notices:
            query += " AND notice = 0"
        query += " ORDER BY id ASC"
        with self._lock:
            rows = self._conn.execute(query, (session_id, after_id)).fetchall()
        return [_message(row) for row in rows]

    def count_user_messages_after(self, session_id: str, after_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM messages
                WHERE session_id = ? AND id > ? AND role = 'user' AND notice = 0
                """,
                (session_id, after_id),
            ).fetchone()
        return int(row["n"])

    def clear_conversation(self, session_id: str) -> bool:
        """清空对话、摘要和长期记忆，保留人设、资料和群设置。"""
        with self._lock:
            row = self._conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return False
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.execute(
                """
                UPDATE sessions
                SET summary = '', summary_until_id = 0, memory_notes = '', memory_until_id = 0,
                    last_reply_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (iso(), session_id),
            )
            self._conn.commit()
        return True

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def counts(self) -> dict[str, int]:
        with self._lock:
            messages = self._conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
            sessions = self._conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        return {"messages": int(messages), "sessions": int(sessions)}

    def _meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            return self._meta(key)

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._set_meta(key, value)
            self._conn.commit()

    def add_ling_atom(self, *, scope: str, subject: str, content: str, level: int, tags: list[str], strength: float) -> int:
        now = iso()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO ling_atoms (
                    scope, subject, content, level, tags, strength, hits, last_hit_at, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'active', ?)
                """,
                (scope, subject, content[:500], int(level), ",".join(tags), float(strength), now, now),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def list_ling_atoms(self, *, subject: str | None = None, limit: int = 50, include_archived: bool = False) -> list[dict]:
        sql = "SELECT * FROM ling_atoms"
        args: list[object] = []
        where = []
        if subject:
            where.append("subject = ?")
            args.append(subject)
        if not include_archived:
            where.append("status = 'active'")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

    def touch_ling_atom(self, atom_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE ling_atoms SET hits = hits + 1, last_hit_at = ? WHERE id = ?",
                (iso(), atom_id),
            )
            self._conn.commit()

    def archive_ling_atom(self, atom_id: int, status: str = "archived") -> None:
        with self._lock:
            self._conn.execute("UPDATE ling_atoms SET status = ? WHERE id = ?", (status, atom_id))
            self._conn.commit()

    def set_ling_atom_level(self, atom_id: int, level: int, strength: float) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE ling_atoms SET level = ?, strength = ? WHERE id = ?",
                (int(level), float(strength), atom_id),
            )
            self._conn.commit()

    def mark_ling_injected(self, atom_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE ling_atoms SET injected_at = ? WHERE id = ?", (iso(), atom_id))
            self._conn.commit()

    def retime_ling_atom(self, atom_id: int, when: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE ling_atoms SET last_hit_at = ? WHERE id = ?", (when, atom_id))
            self._conn.commit()

    def forget_ling_atoms(self, keyword: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE ling_atoms SET status = 'forgotten' WHERE status = 'active' AND content LIKE ?",
                (f"%{keyword}%",),
            )
            self._conn.commit()
            return int(cursor.rowcount)

    def count_ling_atoms(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM ling_atoms WHERE status = 'active'").fetchone()
        return int(row["n"])

    def add_affinity(self, subject: str, delta: float, *, cap: float = 15) -> float:
        now = iso()
        with self._lock:
            row = self._conn.execute("SELECT score FROM ling_affinity WHERE subject = ?", (subject,)).fetchone()
            score = float(row["score"]) if row else 0.0
            score = max(0.0, score + max(-cap, min(cap, delta)))
            self._conn.execute(
                """
                INSERT INTO ling_affinity (subject, score, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(subject) DO UPDATE SET score = excluded.score, updated_at = excluded.updated_at
                """,
                (subject, score, now),
            )
            self._conn.commit()
        return score

    def affinity_of(self, subject: str) -> float:
        with self._lock:
            row = self._conn.execute("SELECT score FROM ling_affinity WHERE subject = ?", (subject,)).fetchone()
        return 0.0 if row is None else float(row["score"])

    def add_diary(self, day: str, body: str, mood: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO ling_diary (day, body, mood, pinned, created_at) VALUES (?, ?, ?, 0, ?)",
                (day, body[:4000], mood[:40], iso()),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def list_diary(self, limit: int = 14) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ling_diary ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def add_dream(self, night_key: str, body: str, level: int, *, pinned: bool = False) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO ling_dreams (night_key, body, level, pinned, created_at) VALUES (?, ?, ?, ?, ?)",
                (night_key, body[:2000], int(level), int(pinned), iso()),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def list_dreams(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ling_dreams ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{digest}"


def _validate_base_url(base_url: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API 地址必须是 http 或 https")


def _provider(row: sqlite3.Row) -> Provider:
    return Provider(
        id=row["id"],
        name=row["name"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        model=row["model"],
        enabled=bool(row["enabled"]),
        priority=int(row["priority"]),
        timeout_seconds=float(row["timeout_seconds"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _health(row: sqlite3.Row) -> ProviderHealth:
    ok = row["ok"]
    return ProviderHealth(
        provider_id=row["provider_id"],
        ok=None if ok is None else bool(ok),
        last_error=row["last_error"] or "",
        last_checked_at=row["last_checked_at"],
        consecutive_failures=int(row["consecutive_failures"]),
        cooldown_until=row["cooldown_until"],
    )


def _persona(row: sqlite3.Row) -> Persona:
    return Persona(
        id=row["id"],
        name=row["name"],
        prompt=row["prompt"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        kind=row["kind"],
        title=row["title"],
        group_id=row["group_id"],
        persona_id=row["persona_id"],
        wake_mode=row["wake_mode"],
        enabled=bool(row["enabled"]),
        summary=row["summary"] or "",
        summary_until_id=int(row["summary_until_id"]),
        memory_notes=row["memory_notes"] or "",
        memory_until_id=int(row["memory_until_id"]),
        knowledge=row["knowledge"] or "",
        last_reply_at=row["last_reply_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message(row: sqlite3.Row) -> ChatMessage:
    return ChatMessage(
        id=int(row["id"]),
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        sender_id=row["sender_id"],
        sender_name=row["sender_name"],
        notice=bool(row["notice"]),
        created_at=row["created_at"],
    )


def _public_session(session: Session) -> dict:
    return {
        "id": session.id,
        "kind": session.kind,
        "title": session.title,
        "group_id": session.group_id,
        "persona_id": session.persona_id,
        "wake_mode": session.wake_mode,
        "enabled": session.enabled,
        "summary": session.summary,
        "summary_until_id": session.summary_until_id,
        "memory_notes": session.memory_notes,
        "memory_until_id": session.memory_until_id,
        "knowledge": session.knowledge,
        "last_reply_at": session.last_reply_at,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def public_message(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "sender_id": message.sender_id,
        "sender_name": message.sender_name,
        "notice": message.notice,
        "created_at": message.created_at,
    }
