"""Motor de ranking: momentum + madurez + relevancia.

Uso:
    python -m radar.scorer            # puntúa la última corrida
    python -m radar.scorer --run 3    # puntúa una corrida concreta
"""

from __future__ import annotations

import argparse
import json
import math

from .common import (CONFIG_PATH, DB_PATH, connect, days_between, jload,
                     load_config, normalize_text)

PERMISSIVE = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc",
              "mpl-2.0", "unlicense", "0bsd", "zlib"}

# Referencias de normalización
HOT_DAILY_STARS = 50.0     # 50 estrellas/día = momentum absoluto máximo
HOT_DAILY_GROWTH = 0.02    # crecer 2% diario = momentum relativo máximo
PROVISIONAL_DAMPING = 0.70  # castigo mientras no haya histórico real


# --------------------------------------------------------------------------
# Momentum
# --------------------------------------------------------------------------

def momentum_score(stars_now, stars_prev, days, created_at, captured_at):
    """Devuelve (score 0-1, delta, días, provisional)."""
    provisional = False

    if stars_prev is None or days is None or days <= 0:
        # Sin histórico: proxy = ritmo promedio desde que nació el repo.
        provisional = True
        age = days_between(created_at, captured_at) or 1.0
        age = max(age, 1.0)
        daily = stars_now / age
        rel_daily = daily / max(stars_now, 1)
        delta = None
        days = None
    else:
        delta = stars_now - stars_prev
        daily = max(delta, 0) / days
        rel_daily = daily / max(stars_prev, 1)

    abs_part = math.log10(1 + max(daily, 0)) / math.log10(1 + HOT_DAILY_STARS)
    rel_part = rel_daily / HOT_DAILY_GROWTH

    score = 0.45 * min(abs_part, 1.0) + 0.55 * min(rel_part, 1.0)
    if provisional:
        score *= PROVISIONAL_DAMPING

    return round(min(max(score, 0.0), 1.0), 4), delta, days, provisional


# --------------------------------------------------------------------------
# Madurez
# --------------------------------------------------------------------------

def maturity_score(repo, snap, captured_at):
    score = 0.0
    flags = []

    desc = (repo["description"] or "").strip()
    if len(desc) >= 30:
        score += 0.10
    elif desc:
        score += 0.05

    lic = (repo["license_key"] or "").lower()
    if lic in PERMISSIVE:
        score += 0.18
    elif lic and lic != "other":
        score += 0.08
    else:
        flags.append("sin-licencia")

    idle = days_between(snap["pushed_at"] or repo["pushed_at"], captured_at)
    if idle is not None:
        if idle <= 14:
            score += 0.18
        elif idle <= 30:
            score += 0.12
        elif idle <= 60:
            score += 0.06

    topics = jload(repo["topics"])
    if len(topics) >= 3:
        score += 0.10
    elif topics:
        score += 0.05

    stars = max(snap["stars"] or 0, 1)
    fork_ratio = (snap["forks"] or 0) / stars
    if fork_ratio >= 0.05:
        score += 0.10
    elif fork_ratio >= 0.02:
        score += 0.05

    size = snap["size_kb"] or 0
    if size >= 200:
        score += 0.08
    elif size >= 50:
        score += 0.04
    else:
        flags.append("codigo-minimo")

    if (repo["homepage"] or "").strip() or repo["has_pages"]:
        score += 0.08

    age = days_between(repo["created_at"], captured_at) or 0
    if age >= 90:
        score += 0.10
    elif age >= 30:
        score += 0.05

    issue_ratio = (snap["open_issues"] or 0) / stars
    if 0 < issue_ratio < 0.15:
        score += 0.08

    return round(min(score, 1.0), 4), flags


# --------------------------------------------------------------------------
# Relevancia
# --------------------------------------------------------------------------

def relevance_score(repo, axes_cfg, boosts, penalties):
    haystack = normalize_text(
        repo["name"], repo["description"], " ".join(jload(repo["topics"])),
        repo["owner"],
    )
    repo_axes = jload(repo["axes"])
    queries = jload(repo["queries"])
    flags = []

    score = 0.35 if repo_axes else 0.0

    hits = set()
    for axis in axes_cfg:
        if axis["id"] not in repo_axes:
            continue
        for term in axis.get("lexicon", []):
            if normalize_text(term) in haystack:
                hits.add(term)
    score += min(len(hits) * 0.08, 0.40)

    if len(queries) >= 2:
        score += 0.10
    if len(repo_axes) >= 2:
        score += 0.05
        flags.append("transversal")

    if any(normalize_text(b) in haystack for b in boosts):
        score += 0.10
        flags.append("contexto-hispano")

    if any(normalize_text(p) in haystack for p in penalties):
        score -= 0.30
        flags.append("recurso")

    return round(min(max(score, 0.0), 1.0), 4), sorted(hits), flags


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------

def run(config_path=None, db_path=None, run_id=None) -> int:
    cfg = load_config(config_path or CONFIG_PATH)
    weights = cfg["weights"]
    conn = connect(db_path or DB_PATH)

    if run_id is None:
        row = conn.execute("SELECT MAX(run_id) AS r FROM runs").fetchone()
        run_id = row["r"]
    if not run_id:
        print("No hay corridas en la base de datos.")
        return 0

    snaps = conn.execute(
        "SELECT * FROM snapshots WHERE run_id = ?", (run_id,)
    ).fetchall()

    scored = 0
    for snap in snaps:
        repo = conn.execute(
            "SELECT * FROM repos WHERE full_name = ?", (snap["full_name"],)
        ).fetchone()
        if repo is None:
            continue

        prev = conn.execute(
            """SELECT stars, captured_at FROM snapshots
               WHERE full_name = ? AND run_id < ?
               ORDER BY run_id DESC LIMIT 1""",
            (snap["full_name"], run_id),
        ).fetchone()

        days = None
        stars_prev = None
        if prev:
            stars_prev = prev["stars"]
            days = days_between(prev["captured_at"], snap["captured_at"])

        mom, delta, days_used, provisional = momentum_score(
            snap["stars"] or 0, stars_prev, days,
            repo["created_at"], snap["captured_at"],
        )
        mat, mat_flags = maturity_score(repo, snap, snap["captured_at"])
        rel, hits, rel_flags = relevance_score(
            repo, cfg["axes"], cfg.get("boosts", []), cfg.get("penalties", [])
        )

        total = (weights["momentum"] * mom
                 + weights["maturity"] * mat
                 + weights["relevance"] * rel)

        flags = mat_flags + rel_flags
        if provisional:
            flags.append("provisional")
        if repo["first_seen"] == snap["captured_at"]:
            flags.append("nuevo")
        if mom >= 0.75 and not provisional:
            flags.append("en-llamas")
        if mat >= 0.75:
            flags.append("maduro")

        conn.execute(
            """INSERT INTO scores (full_name, run_id, momentum, maturity,
                   relevance, total, stars_delta, days_elapsed, provisional,
                   flags)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(full_name, run_id) DO UPDATE SET
                   momentum=excluded.momentum, maturity=excluded.maturity,
                   relevance=excluded.relevance, total=excluded.total,
                   stars_delta=excluded.stars_delta,
                   days_elapsed=excluded.days_elapsed,
                   provisional=excluded.provisional, flags=excluded.flags""",
            (snap["full_name"], run_id, mom, mat, rel, round(total, 4),
             delta, days_used, int(provisional),
             json.dumps(sorted(set(flags)))),
        )
        scored += 1

    conn.commit()
    n_prov = conn.execute(
        "SELECT COUNT(*) AS c FROM scores WHERE run_id=? AND provisional=1",
        (run_id,),
    ).fetchone()["c"]

    print(f"Corrida #{run_id}: {scored} repos puntuados "
          f"({n_prov} provisionales, sin histórico todavía)")
    conn.close()
    return run_id


def main() -> None:
    ap = argparse.ArgumentParser(description="Ranking del radar de repos")
    ap.add_argument("--config")
    ap.add_argument("--db")
    ap.add_argument("--run", type=int)
    args = ap.parse_args()
    run(args.config, args.db, args.run)


if __name__ == "__main__":
    main()
