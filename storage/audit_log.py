"""
The most important part of the project: keeps an immutable (append-only)
record of every decision card, human action, and executed order. The
Streamlit UI's 'Audit Trail' tab reads this table.

On top of the plain tables, every write is also appended to a hash-chained
`ledger` table (each row's hash covers the previous row's hash + its own
payload), giving a tamper-evident record: `verify_ledger()` recomputes the
chain and reports the first row where it no longer matches, if any.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                event_summary TEXT,
                event_type TEXT,
                sentiment TEXT,
                confidence_score INTEGER,
                already_priced_in INTEGER,
                reasoning_steps TEXT,
                risk_flags TEXT,
                sources TEXT,
                strategy TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS human_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                note TEXT,
                acted_at TEXT NOT NULL,
                FOREIGN KEY (card_id) REFERENCES decision_cards (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                order_id TEXT,
                status TEXT,
                legs TEXT,
                limit_price REAL,
                quantity INTEGER,
                executed_at TEXT NOT NULL,
                FOREIGN KEY (card_id) REFERENCES decision_cards (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT NOT NULL,
                ref_id INTEGER NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        # Migration: older DBs created before analyst_opinions existed.
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(decision_cards)").fetchall()]
        if "analyst_opinions" not in cols:
            conn.execute("ALTER TABLE decision_cards ADD COLUMN analyst_opinions TEXT")


def _canonical(payload: Dict) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _ledger_append(conn: sqlite3.Connection, entry_type: str, ref_id: int, payload: Dict) -> str:
    """Appends one hash-chained entry. Must be called with the same connection/transaction as the write it logs."""
    prev = conn.execute("SELECT hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = prev["hash"] if prev else "0" * 64
    body = _canonical(payload)
    digest = hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO ledger (entry_type, ref_id, payload, prev_hash, hash, created_at) VALUES (?,?,?,?,?,?)",
        (entry_type, ref_id, body, prev_hash, digest, datetime.now(timezone.utc).isoformat()),
    )
    return digest


def verify_ledger() -> Dict:
    """Recomputes the hash chain from scratch. Returns whether it's intact, and where it broke if not."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM ledger ORDER BY id ASC").fetchall()

    prev_hash = "0" * 64
    for row in rows:
        expected = hashlib.sha256((prev_hash + row["payload"]).encode("utf-8")).hexdigest()
        if row["prev_hash"] != prev_hash or row["hash"] != expected:
            return {"valid": False, "broken_at_id": row["id"], "entry_type": row["entry_type"]}
        prev_hash = row["hash"]

    return {"valid": True, "entries": len(rows), "last_hash": prev_hash}


def save_decision_card(card: Dict, strategy: Optional[Dict]) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO decision_cards
                (symbol, event_summary, event_type, sentiment, confidence_score,
                 already_priced_in, reasoning_steps, risk_flags, sources, strategy,
                 analyst_opinions, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                card["symbol"],
                card["event_summary"],
                card["event_type"],
                card["sentiment"],
                card["confidence_score"],
                int(bool(card["already_priced_in"])),
                json.dumps(card["reasoning_steps"], ensure_ascii=False),
                json.dumps(card["risk_flags"], ensure_ascii=False),
                json.dumps(card.get("sources", {}), ensure_ascii=False),
                json.dumps(strategy, ensure_ascii=False) if strategy else None,
                json.dumps(card.get("analyst_opinions"), ensure_ascii=False) if card.get("analyst_opinions") else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        card_id = cur.lastrowid
        _ledger_append(conn, "decision_card", card_id, {
            "symbol": card["symbol"],
            "sentiment": card["sentiment"],
            "confidence_score": card["confidence_score"],
            "event_summary": card["event_summary"],
        })
        return card_id


def record_human_action(card_id: int, action: str, note: str = "") -> None:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO human_actions (card_id, action, note, acted_at) VALUES (?,?,?,?)",
            (card_id, action, note, datetime.now(timezone.utc).isoformat()),
        )
        _ledger_append(conn, "human_action", cur.lastrowid, {
            "card_id": card_id, "action": action, "note": note,
        })


def record_execution(card_id: int, execution_result: Dict, quantity: int) -> None:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO executions (card_id, order_id, status, legs, limit_price, quantity, executed_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                card_id,
                execution_result.get("order_id"),
                execution_result.get("status"),
                json.dumps(execution_result.get("legs", []), ensure_ascii=False),
                execution_result.get("limit_price"),
                quantity,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        _ledger_append(conn, "execution", cur.lastrowid, {
            "card_id": card_id,
            "order_id": execution_result.get("order_id"),
            "status": execution_result.get("status"),
            "quantity": quantity,
        })


def get_full_audit_trail() -> List[Dict]:
    """Returns decisions + human actions + executions as one combined timeline."""
    with _connect() as conn:
        cards = conn.execute("SELECT * FROM decision_cards ORDER BY id DESC").fetchall()
        result = []
        for c in cards:
            actions = conn.execute(
                "SELECT * FROM human_actions WHERE card_id = ? ORDER BY id", (c["id"],)
            ).fetchall()
            execs = conn.execute(
                "SELECT * FROM executions WHERE card_id = ? ORDER BY id", (c["id"],)
            ).fetchall()
            result.append(
                {
                    "card": dict(c),
                    "actions": [dict(a) for a in actions],
                    "executions": [dict(e) for e in execs],
                }
            )
        return result
