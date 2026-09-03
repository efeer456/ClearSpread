"""
Projenin en onemli parcasi: her karar kartinin, insan aksiyonunun ve
gerceklesen emrin degismez (append-only) bir kaydini tutar. Streamlit
arayuzundeki 'Denetim Izi' sekmesi bu tabloyu okur.
"""
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


def save_decision_card(card: Dict, strategy: Optional[Dict]) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO decision_cards
                (symbol, event_summary, event_type, sentiment, confidence_score,
                 already_priced_in, reasoning_steps, risk_flags, sources, strategy, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
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
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def record_human_action(card_id: int, action: str, note: str = "") -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO human_actions (card_id, action, note, acted_at) VALUES (?,?,?,?)",
            (card_id, action, note, datetime.now(timezone.utc).isoformat()),
        )


def record_execution(card_id: int, execution_result: Dict, quantity: int) -> None:
    with _connect() as conn:
        conn.execute(
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


def get_full_audit_trail() -> List[Dict]:
    """Karar + insan aksiyonu + emir sonucunu tek bir zaman cizelgesi olarak dondurur."""
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
