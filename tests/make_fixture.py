"""Genera datos simulados que imitan la respuesta de la Search API de GitHub.

Sirve para probar el pipeline completo sin gastar llamadas reales:

    python tests/make_fixture.py --out tests/tmp/run1.json --day 0
    python tests/make_fixture.py --out tests/tmp/run2.json --day 2
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

LICENSES = [
    {"key": "mit", "name": "MIT License"},
    {"key": "apache-2.0", "name": "Apache License 2.0"},
    {"key": "bsd-3-clause", "name": "BSD 3-Clause"},
    None,
]
LANGS = ["Python", "TypeScript", "JavaScript", "Go", "Rust", "R"]

# Perfiles de crecimiento: (nombre, estrellas base, crecimiento diario)
PROFILES = [
    ("cohete", 900, 0.030),    # en llamas
    ("solido", 2600, 0.004),   # crecimiento sano
    ("estable", 5200, 0.0008),  # maduro pero plano
    ("frio", 140, 0.0002),     # casi muerto
]


def make_repo(axis, core, idx, day, rng):
    profile_name, base_stars, growth = PROFILES[idx % len(PROFILES)]
    slug = core.replace("topic:", "").replace(" ", "-").replace(":", "-")
    name = f"{slug}-{profile_name}-{idx}"
    owner = f"org{(idx * 7) % 23}"

    age_days = rng.randint(40, 500)
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    pushed = datetime.now(timezone.utc) - timedelta(days=rng.randint(0, 45))

    stars = int(base_stars * ((1 + growth) ** day))
    is_resource = idx % 9 == 0

    desc = (f"Awesome tutorial collection about {core}" if is_resource
            else f"Herramienta de {axis['name'].lower()} para {core}. "
                 f"Perfil {profile_name}.")
    if idx % 6 == 0:
        desc += " Soporta español y análisis electoral."

    return {
        "id": abs(hash(name)) % 10**8,
        "full_name": f"{owner}/{name}",
        "name": name,
        "owner": {"login": owner},
        "description": desc,
        "html_url": f"https://github.com/{owner}/{name}",
        "homepage": f"https://{name}.dev" if idx % 3 == 0 else "",
        "language": LANGS[idx % len(LANGS)],
        "license": LICENSES[idx % len(LICENSES)],
        "topics": (axis.get("lexicon", [])[: (idx % 5)] or ["tooling"]),
        "created_at": created.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "pushed_at": pushed.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "archived": False,
        "fork": False,
        "has_wiki": idx % 2 == 0,
        "has_pages": idx % 4 == 0,
        "stargazers_count": stars,
        "forks_count": int(stars * (0.02 + (idx % 5) * 0.02)),
        "watchers_count": stars,
        "open_issues_count": int(stars * 0.05),
        "size": [12, 90, 450, 2300][idx % 4],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--day", type=int, default=0,
                    help="días transcurridos desde la corrida base")
    ap.add_argument("--per-query", type=int, default=6)
    args = ap.parse_args()

    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    rng = random.Random(42)  # semilla fija: los mismos repos en ambas corridas
    fixture = {}
    for axis in cfg["axes"]:
        for core in axis["queries"]:
            fixture[core] = [
                make_repo(axis, core, i, args.day, rng)
                for i in range(args.per_query)
            ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    n = sum(len(v) for v in fixture.values())
    print(f"Fixture escrito: {out} ({len(fixture)} queries, {n} repos, día {args.day})")


if __name__ == "__main__":
    main()
