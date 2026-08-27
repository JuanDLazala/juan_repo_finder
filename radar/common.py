"""Utilidades compartidas: configuración, base de datos y helpers de texto."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "radar.db"
CONFIG_PATH = ROOT / "config.yaml"


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

def load_config(path: Path | None = None) -> dict:
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    weights = cfg.get("weights", {})
    total = sum(weights.values())
    if abs(total - 1.0) > 0.01:
        raise ValueError(
            f"Los pesos en config.yaml suman {total:.2f}, deben sumar 1.0"
        )

    seen_ids = set()
    for axis in cfg.get("axes", []):
        if axis["id"] in seen_ids:
            raise ValueError(f"Eje duplicado en config.yaml: {axis['id']}")
        seen_ids.add(axis["id"])
    if not seen_ids:
        raise ValueError("config.yaml no define ningún eje")

    return cfg


# --------------------------------------------------------------------------
# Base de datos
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    n_queries   INTEGER DEFAULT 0,
    n_repos     INTEGER DEFAULT 0,
    n_new       INTEGER DEFAULT 0,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS repos (
    full_name    TEXT PRIMARY KEY,
    repo_id      INTEGER,
    owner        TEXT,
    name         TEXT,
    description  TEXT,
    html_url     TEXT,
    homepage     TEXT,
    language     TEXT,
    license_key  TEXT,
    license_name TEXT,
    topics       TEXT,      -- JSON list
    created_at   TEXT,
    pushed_at    TEXT,
    archived     INTEGER DEFAULT 0,
    is_fork      INTEGER DEFAULT 0,
    has_wiki     INTEGER DEFAULT 0,
    has_pages    INTEGER DEFAULT 0,
    axes         TEXT,      -- JSON list de ids de eje
    queries      TEXT,      -- JSON list de queries que lo encontraron
    first_seen   TEXT,
    last_seen    TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name    TEXT NOT NULL,
    run_id       INTEGER NOT NULL,
    captured_at  TEXT NOT NULL,
    stars        INTEGER,
    forks        INTEGER,
    watchers     INTEGER,
    open_issues  INTEGER,
    size_kb      INTEGER,
    pushed_at    TEXT,
    UNIQUE(full_name, run_id)
);

CREATE INDEX IF NOT EXISTS idx_snap_repo ON snapshots(full_name, captured_at);

CREATE TABLE IF NOT EXISTS scores (
    full_name       TEXT NOT NULL,
    run_id          INTEGER NOT NULL,
    momentum        REAL,
    maturity        REAL,
    relevance       REAL,
    total           REAL,
    stars_delta     INTEGER,
    days_elapsed    REAL,
    provisional     INTEGER DEFAULT 0,
    flags           TEXT,   -- JSON list
    PRIMARY KEY (full_name, run_id)
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def days_between(a: str | None, b: str | None) -> float | None:
    da, db = parse_iso(a), parse_iso(b)
    if not da or not db:
        return None
    return (db - da).total_seconds() / 86400.0


def normalize_text(*parts) -> str:
    """Junta y normaliza texto para el matching de léxico (sin acentos)."""
    raw = " ".join(str(p) for p in parts if p).lower()
    for src, dst in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"),
                     ("ú", "u"), ("ñ", "n")):
        raw = raw.replace(src, dst)
    return re.sub(r"[^a-z0-9 ]+", " ", raw)


def jload(value, default=None):
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


def env_token() -> str | None:
    for key in ("RADAR_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value
    return None
