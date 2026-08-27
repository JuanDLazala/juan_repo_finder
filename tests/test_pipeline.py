"""Prueba de extremo a extremo con datos simulados.

Simula dos corridas separadas por dos días y verifica que:
  1. La primera corrida marca todo como provisional (no hay con qué comparar).
  2. La segunda corrida calcula momentum real y detecta las estrellas ganadas.
  3. Los repos "cohete" rankean por encima de los "frío".
  4. El dashboard se genera y contiene los datos.

    python tests/test_pipeline.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / "tests" / "tmp"
DB = TMP / "test.db"

sys.path.insert(0, str(ROOT))

from radar.common import connect, jload  # noqa: E402


def sh(*args):
    result = subprocess.run(
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"Falló: {' '.join(args)}")
    return result.stdout


def backdate_run(run_id: int, days: int) -> None:
    """Mueve una corrida N días hacia atrás para simular el paso del tiempo."""
    conn = connect(DB)
    row = conn.execute(
        "SELECT started_at FROM runs WHERE run_id=?", (run_id,)
    ).fetchone()
    old = row["started_at"]
    new = (datetime.fromisoformat(old) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    conn.execute("UPDATE runs SET started_at=? WHERE run_id=?", (new, run_id))
    conn.execute(
        "UPDATE snapshots SET captured_at=? WHERE run_id=?", (new, run_id)
    )
    conn.execute(
        "UPDATE repos SET first_seen=? WHERE first_seen=?", (new, old)
    )
    conn.commit()
    conn.close()


def main() -> None:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)

    checks = []

    def check(label, condition, detail=""):
        checks.append((label, bool(condition), detail))
        mark = "OK  " if condition else "FALLA"
        print(f"  [{mark}] {label} {detail}")

    print("\n1. Generando datos simulados")
    sh("tests/make_fixture.py", "--out", str(TMP / "run1.json"), "--day", "0")
    sh("tests/make_fixture.py", "--out", str(TMP / "run2.json"), "--day", "2")

    print("\n2. Primera corrida (sin histórico)")
    sh("-m", "radar.collector", "--db", str(DB), "--fixture", str(TMP / "run1.json"))
    sh("-m", "radar.scorer", "--db", str(DB))

    conn = connect(DB)
    n_repos = conn.execute("SELECT COUNT(*) c FROM repos").fetchone()["c"]
    n_prov = conn.execute(
        "SELECT COUNT(*) c FROM scores WHERE run_id=1 AND provisional=1"
    ).fetchone()["c"]
    n_scores = conn.execute(
        "SELECT COUNT(*) c FROM scores WHERE run_id=1"
    ).fetchone()["c"]
    conn.close()

    check("Se guardaron repos", n_repos > 50, f"({n_repos} repos únicos)")
    check("Todo provisional en la corrida 1", n_prov == n_scores,
          f"({n_prov}/{n_scores})")

    print("\n3. Simulando el paso de 2 días")
    backdate_run(1, 2)

    print("\n4. Segunda corrida (con histórico)")
    sh("-m", "radar.collector", "--db", str(DB), "--fixture", str(TMP / "run2.json"))
    sh("-m", "radar.scorer", "--db", str(DB))

    conn = connect(DB)
    n_prov2 = conn.execute(
        "SELECT COUNT(*) c FROM scores WHERE run_id=2 AND provisional=1"
    ).fetchone()["c"]
    growth = conn.execute(
        "SELECT COUNT(*) c FROM scores WHERE run_id=2 AND stars_delta > 0"
    ).fetchone()["c"]
    days = conn.execute(
        "SELECT DISTINCT ROUND(days_elapsed,1) d FROM scores WHERE run_id=2"
    ).fetchall()

    top = conn.execute(
        """SELECT s.full_name, s.total, s.momentum, s.maturity, s.relevance,
                  s.stars_delta, s.flags
           FROM scores s WHERE s.run_id=2 ORDER BY s.total DESC LIMIT 8"""
    ).fetchall()
    bottom = conn.execute(
        "SELECT full_name, total FROM scores WHERE run_id=2 "
        "ORDER BY total ASC LIMIT 3"
    ).fetchall()
    conn.close()

    check("Ya no hay provisionales", n_prov2 == 0, f"({n_prov2} provisionales)")
    check("Se detectó crecimiento de estrellas", growth > 20,
          f"({growth} repos crecieron)")
    check("El intervalo medido es de ~2 días",
          all(abs(r["d"] - 2.0) < 0.1 for r in days),
          f"({[r['d'] for r in days]})")

    top_names = " ".join(r["full_name"] for r in top)
    check("Los repos 'cohete' dominan el top 8", "cohete" in top_names)
    check("Los repos 'frío' quedan al fondo",
          any("frio" in r["full_name"] for r in bottom))

    print("\n   Top 8 de la corrida simulada:")
    for i, r in enumerate(top, 1):
        flags = ", ".join(jload(r["flags"])) or "—"
        print(f"   {i:>2}. {r['total']*100:5.1f}  mom {r['momentum']*100:5.1f}  "
              f"mad {r['maturity']*100:5.1f}  rel {r['relevance']*100:5.1f}  "
              f"+{r['stars_delta']:<5} {r['full_name'][:44]:<44} [{flags}]")

    print("\n5. Corrida inmediata (sin dejar pasar tiempo)")
    sh("-m", "radar.collector", "--db", str(DB), "--fixture", str(TMP / "run2.json"))
    sh("-m", "radar.scorer", "--db", str(DB))

    conn = connect(DB)
    n_prov3 = conn.execute(
        "SELECT COUNT(*) c FROM scores WHERE run_id=3 AND provisional=1"
    ).fetchone()["c"]
    n_real3 = conn.execute(
        "SELECT COUNT(*) c FROM scores WHERE run_id=3 AND provisional=0"
    ).fetchone()["c"]
    days3 = conn.execute(
        "SELECT DISTINCT ROUND(days_elapsed,1) d FROM scores "
        "WHERE run_id=3 AND provisional=0"
    ).fetchall()
    conn.close()

    check("Ignora la foto de hace minutos y usa la de hace 2 días",
          n_real3 > 0 and all(r["d"] >= 0.5 for r in days3),
          f"({n_real3} con base real, {n_prov3} provisionales, "
          f"intervalos {[r['d'] for r in days3]})")

    print("\n6. Generando el dashboard")
    out = TMP / "index.html"
    sh("-m", "radar.build_dashboard", "--db", str(DB), "--out", str(out))

    html = out.read_text(encoding="utf-8")
    check("El HTML se generó", out.exists() and len(html) > 20000,
          f"({len(html)//1024} KB)")
    check("No quedaron marcadores sin reemplazar",
          "__META__" not in html and "__REPOS__" not in html)
    check("Los datos están embebidos", '"full_name"' in html)
    check("Define paleta clara y oscura",
          'prefers-color-scheme: dark' in html and 'data-theme="dark"' in html)

    start = html.index("const REPOS = ") + len("const REPOS = ")
    end = html.index("\n", start)
    payload = json.loads(html[start:end].rstrip(";"))
    check("El JSON embebido es válido", isinstance(payload, list) and payload,
          f"({len(payload)} repos en el dashboard)")

    import yaml as _yaml
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        cfg = _yaml.safe_load(fh)
    axis_ids = [a["id"] for a in cfg["axes"]]
    present = {a for r in payload for a in r["axes"]}
    missing = [a for a in axis_ids if a not in present]
    check("Todos los ejes tienen espacio en el dashboard", not missing,
          f"(faltan: {missing})" if missing else f"({len(axis_ids)} ejes)")

    counts = {a: sum(1 for r in payload if a in r["axes"]) for a in axis_ids}
    quota = cfg["settings"].get("per_axis_quota", 25)
    starved = {a: c for a, c in counts.items() if c < min(quota, 5)}
    check("Ningún eje queda sepultado por otro", not starved,
          f"({counts})")

    failed = [c for c in checks if not c[1]]
    print(f"\n{'=' * 60}")
    if failed:
        print(f"FALLARON {len(failed)} de {len(checks)} verificaciones")
        raise SystemExit(1)
    print(f"Las {len(checks)} verificaciones pasaron.")


if __name__ == "__main__":
    main()
