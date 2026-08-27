"""Recolector: consulta la Search API de GitHub y guarda todo en SQLite.

Uso:
    python -m radar.collector                 # corrida normal
    python -m radar.collector --dry-run       # muestra las queries sin ejecutar
    python -m radar.collector --fixture x.json  # corre con datos simulados
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from .common import (CONFIG_PATH, DB_PATH, connect, env_token, jload,
                     load_config, now_iso)

API = "https://api.github.com/search/repositories"
USER_AGENT = "radar-repos/1.0"


# --------------------------------------------------------------------------
# Construcción de queries
# --------------------------------------------------------------------------

def build_query(core: str, settings: dict) -> str:
    """Añade los filtros duros a la parte semántica de la query."""
    now = datetime.now(timezone.utc)
    created_after = now - timedelta(days=int(settings["max_age_months"] * 30.44))
    pushed_after = now - timedelta(days=int(settings["max_idle_days"]))

    parts = [
        core.strip(),
        f"stars:>={settings['min_stars']}",
        f"created:>{created_after:%Y-%m-%d}",
        f"pushed:>{pushed_after:%Y-%m-%d}",
        "is:public",
        "archived:false",
        "fork:false",
    ]
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------
# Llamada a la API
# --------------------------------------------------------------------------

def search(query: str, limit: int, token: str | None,
           session: requests.Session) -> list[dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    for attempt in range(4):
        try:
            resp = session.get(API, headers=headers, params=params, timeout=45)
        except requests.RequestException as exc:
            wait = 5 * (attempt + 1)
            print(f"    ! error de red ({exc.__class__.__name__}), "
                  f"reintento en {wait}s", flush=True)
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp.json().get("items", [])

        if resp.status_code in (403, 429):
            reset = resp.headers.get("X-RateLimit-Reset")
            wait = 60
            if reset:
                wait = max(5, int(reset) - int(time.time()) + 5)
            wait = min(wait, 180)
            print(f"    ! rate limit, esperando {wait}s", flush=True)
            time.sleep(wait)
            continue

        if resp.status_code == 422:
            print(f"    ! query inválida, se omite: {query}", flush=True)
            return []

        print(f"    ! HTTP {resp.status_code}: {resp.text[:160]}", flush=True)
        time.sleep(5 * (attempt + 1))

    print("    ! se agotaron los reintentos, se omite la query", flush=True)
    return []


# --------------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------------

def upsert_repo(conn, item: dict, axis_id: str, query: str, ts: str) -> bool:
    """Inserta o actualiza el repo. Devuelve True si es nuevo."""
    full_name = item["full_name"]
    row = conn.execute(
        "SELECT axes, queries, first_seen FROM repos WHERE full_name = ?",
        (full_name,),
    ).fetchone()

    axes = jload(row["axes"]) if row else []
    queries = jload(row["queries"]) if row else []
    if axis_id not in axes:
        axes.append(axis_id)
    if query not in queries:
        queries.append(query)

    license_info = item.get("license") or {}
    conn.execute(
        """
        INSERT INTO repos (full_name, repo_id, owner, name, description,
            html_url, homepage, language, license_key, license_name, topics,
            created_at, pushed_at, archived, is_fork, has_wiki, has_pages,
            axes, queries, first_seen, last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(full_name) DO UPDATE SET
            description = excluded.description,
            homepage    = excluded.homepage,
            language    = excluded.language,
            license_key = excluded.license_key,
            license_name= excluded.license_name,
            topics      = excluded.topics,
            pushed_at   = excluded.pushed_at,
            archived    = excluded.archived,
            has_wiki    = excluded.has_wiki,
            has_pages   = excluded.has_pages,
            axes        = excluded.axes,
            queries     = excluded.queries,
            last_seen   = excluded.last_seen
        """,
        (
            full_name,
            item.get("id"),
            (item.get("owner") or {}).get("login"),
            item.get("name"),
            item.get("description"),
            item.get("html_url"),
            item.get("homepage"),
            item.get("language"),
            license_info.get("key"),
            license_info.get("name"),
            json.dumps(item.get("topics") or []),
            item.get("created_at"),
            item.get("pushed_at"),
            int(bool(item.get("archived"))),
            int(bool(item.get("fork"))),
            int(bool(item.get("has_wiki"))),
            int(bool(item.get("has_pages"))),
            json.dumps(axes),
            json.dumps(queries),
            row["first_seen"] if row else ts,
            ts,
        ),
    )
    return row is None


def save_snapshot(conn, item: dict, run_id: int, ts: str) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (full_name, run_id, captured_at, stars, forks,
            watchers, open_issues, size_kb, pushed_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(full_name, run_id) DO UPDATE SET
            stars = excluded.stars, forks = excluded.forks,
            watchers = excluded.watchers, open_issues = excluded.open_issues,
            size_kb = excluded.size_kb, pushed_at = excluded.pushed_at
        """,
        (
            item["full_name"], run_id, ts,
            item.get("stargazers_count", 0),
            item.get("forks_count", 0),
            item.get("watchers_count", 0),
            item.get("open_issues_count", 0),
            item.get("size", 0),
            item.get("pushed_at"),
        ),
    )


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------

def run(config_path=None, db_path=None, fixture=None, dry_run=False) -> int:
    cfg = load_config(config_path or CONFIG_PATH)
    settings = cfg["settings"]
    token = env_token()

    if dry_run:
        for axis in cfg["axes"]:
            print(f"\n[{axis['id']}]")
            for core in axis["queries"]:
                print("  " + build_query(core, settings))
        return 0

    if not token and not fixture:
        print("AVISO: sin token. La API sin autenticar permite solo 10 "
              "búsquedas por minuto y esta corrida será muy lenta o fallará.",
              file=sys.stderr)

    fixture_data = None
    if fixture:
        with open(fixture, "r", encoding="utf-8") as fh:
            fixture_data = json.load(fh)

    conn = connect(db_path or DB_PATH)
    ts = now_iso()
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (ts,))
    run_id = cur.lastrowid
    conn.commit()

    session = requests.Session()
    n_queries = n_new = 0
    seen: set[str] = set()

    for axis in cfg["axes"]:
        print(f"\n[{axis['id']}] {axis['name']}", flush=True)
        for core in axis["queries"]:
            query = build_query(core, settings)
            n_queries += 1

            if fixture_data is not None:
                items = fixture_data.get(core, [])
            else:
                items = search(query, settings["per_query_limit"], token, session)
                time.sleep(settings["sleep_between_queries"])

            for item in items:
                if upsert_repo(conn, item, axis["id"], core, ts):
                    n_new += 1
                save_snapshot(conn, item, run_id, ts)
                seen.add(item["full_name"])

            print(f"  {len(items):>3} resultados  ·  {core}", flush=True)
            conn.commit()

    conn.execute(
        "UPDATE runs SET finished_at=?, n_queries=?, n_repos=?, n_new=? "
        "WHERE run_id=?",
        (now_iso(), n_queries, len(seen), n_new, run_id),
    )
    conn.commit()

    print(f"\nCorrida #{run_id}: {n_queries} queries · {len(seen)} repos "
          f"únicos · {n_new} nuevos", flush=True)
    conn.close()
    return run_id


def main() -> None:
    ap = argparse.ArgumentParser(description="Recolector del radar de repos")
    ap.add_argument("--config")
    ap.add_argument("--db")
    ap.add_argument("--fixture", help="JSON con resultados simulados")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.config, args.db, args.fixture, args.dry_run)


if __name__ == "__main__":
    main()
