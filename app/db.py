"""SQLite storage: farmer registry, consent, cases.

Privacy: raw phone numbers are never stored, only a salted SHA-256 hash.
No audio is stored here.
"""
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    phone_hash TEXT PRIMARY KEY,
    name TEXT,
    village TEXT,
    lat REAL,
    lon REAL,
    crop TEXT DEFAULT 'coffee',
    consent_service INTEGER DEFAULT 0,
    consent_improve INTEGER DEFAULT 0,
    synthetic INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_hash TEXT,
    village TEXT,
    lat REAL,
    lon REAL,
    created_at TEXT,
    transcript TEXT,
    features TEXT,
    ranking TEXT,
    predicted TEXT,
    confidence REAL,
    decision TEXT,
    confirmed_label TEXT,
    confirmed_by TEXT,
    synthetic INTEGER DEFAULT 0
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def hash_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")
    return hashlib.sha256((config.PHONE_HASH_SALT + digits).encode()).hexdigest()


def get_or_create_farmer(phone: str) -> dict:
    """Look the caller up in the registry. Unknown callers get the demo location."""
    ph = hash_phone(phone)
    with connect() as conn:
        row = conn.execute("SELECT * FROM farmers WHERE phone_hash=?", (ph,)).fetchone()
        if row:
            return dict(row)
        conn.execute(
            "INSERT INTO farmers(phone_hash, name, village, lat, lon, created_at) VALUES (?,?,?,?,?,?)",
            (ph, None, config.DEMO_VILLAGE, config.DEMO_LAT, config.DEMO_LON, now_iso()),
        )
        row = conn.execute("SELECT * FROM farmers WHERE phone_hash=?", (ph,)).fetchone()
        return dict(row)


def set_consent(phone: str, service: bool | None = None, improve: bool | None = None) -> None:
    ph = hash_phone(phone)
    get_or_create_farmer(phone)
    with connect() as conn:
        if service is not None:
            conn.execute("UPDATE farmers SET consent_service=? WHERE phone_hash=?", (int(service), ph))
        if improve is not None:
            conn.execute("UPDATE farmers SET consent_improve=? WHERE phone_hash=?", (int(improve), ph))


def delete_farmer_data(phone: str) -> None:
    """Right to delete: remove the farmer and all their cases."""
    ph = hash_phone(phone)
    with connect() as conn:
        conn.execute("DELETE FROM cases WHERE phone_hash=?", (ph,))
        conn.execute("DELETE FROM farmers WHERE phone_hash=?", (ph,))


def save_case(farmer: dict, transcript: str, features: dict, result: dict, store_transcript: bool) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO cases(phone_hash, village, lat, lon, created_at, transcript, features,
                                 ranking, predicted, confidence, decision)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                farmer["phone_hash"], farmer["village"], farmer["lat"], farmer["lon"], now_iso(),
                transcript if store_transcript else None,
                json.dumps(features), json.dumps(result["ranking"]),
                result["top"], result["confidence"], result["decision"],
            ),
        )
        return cur.lastrowid


def confirm_case(case_id: int, label: str, by: str = "officer") -> None:
    """An extension officer (or a photo check) confirms the real problem.
    Only confirmed cases feed the 'nearby reports' signal and future learning."""
    with connect() as conn:
        conn.execute("UPDATE cases SET confirmed_label=?, confirmed_by=? WHERE id=?", (label, by, case_id))


def _km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearby_confirmed_counts(lat: float, lon: float, radius_km: float = 10, days: int = 30) -> dict:
    """Count CONFIRMED cases per problem near this farm in the last N days.
    Unconfirmed reports are ignored on purpose, to avoid a self-reinforcing loop."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    with connect() as conn:
        rows = conn.execute(
            "SELECT lat, lon, confirmed_label FROM cases WHERE confirmed_label IS NOT NULL AND created_at>=?",
            (since,),
        ).fetchall()
    for r in rows:
        if r["lat"] is None:
            continue
        if _km(lat, lon, r["lat"], r["lon"]) <= radius_km:
            counts[r["confirmed_label"]] = counts.get(r["confirmed_label"], 0) + 1
    return counts


def list_cases(limit: int = 100) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM cases ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
