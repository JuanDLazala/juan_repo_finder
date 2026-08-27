"""Genera el dashboard HTML autocontenido a partir de la base de datos.

Uso:
    python -m radar.build_dashboard
    python -m radar.build_dashboard --out docs/index.html
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .common import (CONFIG_PATH, DB_PATH, ROOT, connect, days_between, jload,
                     load_config, parse_iso)

DEFAULT_OUT = ROOT / "docs" / "index.html"

MESES = ["ene", "feb", "mar", "abr", "may", "jun",
         "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_corta(iso: str | None) -> str:
    dt = parse_iso(iso)
    if not dt:
        return "—"
    return f"{dt.day} {MESES[dt.month - 1]} {dt.year}"


def collect_data(conn, cfg, run_id):
    settings = cfg["settings"]
    axes = {a["id"]: a for a in cfg["axes"]}

    run = conn.execute(
        "SELECT * FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    n_runs = conn.execute(
        "SELECT COUNT(*) AS c FROM runs WHERE finished_at IS NOT NULL"
    ).fetchone()["c"]

    rows = conn.execute(
        """SELECT s.*, sc.momentum, sc.maturity, sc.relevance, sc.total,
                  sc.stars_delta, sc.days_elapsed, sc.provisional, sc.flags,
                  r.description, r.html_url, r.homepage, r.language,
                  r.license_key, r.license_name, r.topics, r.created_at,
                  r.axes, r.owner, r.name, r.first_seen
           FROM snapshots s
           JOIN scores sc ON sc.full_name = s.full_name AND sc.run_id = s.run_id
           JOIN repos  r  ON r.full_name  = s.full_name
           WHERE s.run_id = ?
           ORDER BY sc.total DESC
           LIMIT ?""",
        (run_id, settings.get("dashboard_top_n", 120)),
    ).fetchall()

    captured = run["started_at"] if run else None
    repos = []
    for row in rows:
        repo_axes = [a for a in jload(row["axes"]) if a in axes]
        idle = days_between(row["pushed_at"], captured)
        repos.append({
            "full_name": row["full_name"],
            "owner": row["owner"],
            "name": row["name"],
            "url": row["html_url"],
            "home": (row["homepage"] or "").strip(),
            "desc": (row["description"] or "").strip() or "Sin descripción.",
            "lang": row["language"] or "—",
            "license": row["license_name"] or "Sin licencia",
            "topics": jload(row["topics"])[:6],
            "axes": repo_axes,
            "stars": row["stars"] or 0,
            "forks": row["forks"] or 0,
            "delta": row["stars_delta"],
            "days": round(row["days_elapsed"], 1) if row["days_elapsed"] else None,
            "created": fecha_corta(row["created_at"]),
            "pushed": round(idle) if idle is not None else None,
            "mom": row["momentum"],
            "mat": row["maturity"],
            "rel": row["relevance"],
            "total": row["total"],
            "prov": bool(row["provisional"]),
            "flags": jload(row["flags"]),
            "nuevo": row["first_seen"] == captured,
        })

    n_prov = sum(1 for r in repos if r["prov"])
    meta = {
        "run_id": run_id,
        "captured": fecha_corta(captured),
        "captured_iso": captured,
        "generated": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
        "n_runs": n_runs,
        "n_total": run["n_repos"] if run else len(repos),
        "n_new": run["n_new"] if run else 0,
        "n_queries": run["n_queries"] if run else 0,
        "n_shown": len(repos),
        "n_hot": sum(1 for r in repos if "en-llamas" in r["flags"]),
        "all_provisional": n_prov == len(repos) and len(repos) > 0,
        "weights": cfg["weights"],
        "axes": [
            {"id": a["id"], "name": a["name"], "short": a["short"],
             "color": a["color"],
             "count": sum(1 for r in repos if a["id"] in r["axes"])}
            for a in cfg["axes"]
        ],
    }
    return meta, repos


TEMPLATE = r"""<title>Radar de Repos</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root {
  --ground: #f6f8f7;
  --surface: #ffffff;
  --surface-2: #eef2f1;
  --ink: #141d1c;
  --muted: #5c6a68;
  --faint: #8b9a97;
  --rule: #dee4e2;
  --accent: #0e5f5b;
  --accent-soft: #d7e8e6;
  --cold: #8fa09d;
  --warm: #b8862f;
  --hot: #b83f28;
  --shadow: 0 1px 2px rgba(20,29,28,.06), 0 8px 24px -16px rgba(20,29,28,.28);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #0d1312;
    --surface: #151d1c;
    --surface-2: #1d2726;
    --ink: #e7edeb;
    --muted: #8fa09d;
    --faint: #6b7a78;
    --rule: #243130;
    --accent: #4ccfbe;
    --accent-soft: #17332f;
    --cold: #6b7a78;
    --warm: #d9a03c;
    --hot: #e0644a;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"] {
  --ground: #0d1312;
  --surface: #151d1c;
  --surface-2: #1d2726;
  --ink: #e7edeb;
  --muted: #8fa09d;
  --faint: #6b7a78;
  --rule: #243130;
  --accent: #4ccfbe;
  --accent-soft: #17332f;
  --cold: #6b7a78;
  --warm: #d9a03c;
  --hot: #e0644a;
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: Archivo, "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.wrap { max-width: 1140px; margin: 0 auto; padding: 32px 20px 72px; }

/* ---------- masthead ---------- */
.masthead {
  display: flex; flex-wrap: wrap; align-items: baseline;
  justify-content: space-between; gap: 12px 24px;
  padding-bottom: 18px; border-bottom: 2px solid var(--ink);
}
.masthead h1 {
  margin: 0; font-size: clamp(30px, 5vw, 42px); font-weight: 700;
  letter-spacing: -.028em; text-wrap: balance;
}
.masthead .sub {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 12px; color: var(--muted); letter-spacing: .04em;
  text-transform: uppercase;
}

/* ---------- stat strip ---------- */
.stats {
  display: grid; gap: 1px; margin-top: 1px;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  background: var(--rule); border-bottom: 1px solid var(--rule);
}
.stat { background: var(--ground); padding: 16px 4px 18px; }
.stat .n {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 28px; font-weight: 500; letter-spacing: -.02em;
  font-variant-numeric: tabular-nums; display: block;
}
.stat .l {
  font-size: 11px; color: var(--muted); text-transform: uppercase;
  letter-spacing: .07em; font-weight: 500;
}

/* ---------- aviso ---------- */
.notice {
  margin-top: 24px; padding: 14px 16px; border-radius: 3px;
  background: var(--accent-soft); color: var(--ink);
  border-left: 3px solid var(--accent); font-size: 14px;
}
.notice strong { font-weight: 600; }

/* ---------- controles ---------- */
.controls {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  margin: 28px 0 6px; padding-bottom: 16px;
}
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 11.5px; letter-spacing: .03em; text-transform: uppercase;
  padding: 6px 11px; border-radius: 2px; cursor: pointer;
  border: 1px solid var(--rule); background: var(--surface);
  color: var(--muted); font-weight: 500; transition: all .12s ease;
}
.chip:hover { color: var(--ink); border-color: var(--faint); }
.chip[aria-pressed="true"] {
  color: var(--surface); border-color: transparent;
  background: var(--chip-color, var(--accent));
}
:root[data-theme="dark"] .chip[aria-pressed="true"],
:root:not([data-theme="light"]) .chip[aria-pressed="true"] { color: #0d1312; }
.chip .c {
  font-variant-numeric: tabular-nums; opacity: .65; margin-left: 5px;
}
.spacer { flex: 1 1 auto; }
input[type="search"], select {
  font-family: Archivo, sans-serif; font-size: 14px;
  padding: 7px 11px; border-radius: 2px;
  border: 1px solid var(--rule); background: var(--surface); color: var(--ink);
}
input[type="search"] { min-width: 190px; }
label.toggle {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 13px; color: var(--muted); cursor: pointer;
}
:is(button, input, select, a):focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}

/* ---------- lista ---------- */
.count {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 11.5px; color: var(--faint); text-transform: uppercase;
  letter-spacing: .06em; padding: 10px 0; border-top: 1px solid var(--rule);
}
.list { display: flex; flex-direction: column; }

.row {
  display: grid; gap: 4px 18px; padding: 18px 0;
  grid-template-columns: 42px minmax(0, 1fr) 176px;
  border-bottom: 1px solid var(--rule);
}
.rank {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 13px; color: var(--faint); font-variant-numeric: tabular-nums;
  padding-top: 3px;
}
.body { min-width: 0; }
.title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.title a {
  color: var(--ink); text-decoration: none; font-weight: 600;
  font-size: 17px; letter-spacing: -.012em;
}
.title a:hover { color: var(--accent); text-decoration: underline; }
.title .owner { color: var(--faint); font-weight: 400; }
.desc { color: var(--muted); margin: 5px 0 9px; max-width: 66ch; font-size: 14px; }
.tags { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.tag {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 10.5px; letter-spacing: .04em; text-transform: uppercase;
  padding: 3px 7px; border-radius: 2px; font-weight: 500;
  border: 1px solid var(--rule); color: var(--muted);
}
.tag.axis { border-color: transparent; color: #fff; }
.tag.flag-nuevo { border-color: var(--accent); color: var(--accent); }
.tag.flag-en-llamas { border-color: var(--hot); color: var(--hot); }
.tag.flag-maduro { border-color: var(--warm); color: var(--warm); }
.tag.meta { border: 0; color: var(--faint); padding-left: 0; }

/* ---------- panel de datos ---------- */
.data { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px; }
.score {
  font-size: 26px; font-weight: 600; letter-spacing: -.02em;
  font-variant-numeric: tabular-nums; line-height: 1.1;
}
.score .max { font-size: 12px; color: var(--faint); font-weight: 400; }
.bar {
  display: flex; height: 5px; border-radius: 3px; overflow: hidden;
  background: var(--surface-2); margin: 7px 0 9px;
}
.bar i { display: block; height: 100%; }
.bar .m { background: var(--hot); }
.bar .u { background: var(--warm); }
.bar .r { background: var(--accent); }
.kv { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); }
.kv b {
  font-weight: 500; color: var(--ink); font-variant-numeric: tabular-nums;
}
.kv .up { color: var(--hot); }
.kv .flat { color: var(--faint); }

.legend {
  display: flex; flex-wrap: wrap; gap: 16px; margin-top: 26px;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 11px; color: var(--muted); text-transform: uppercase;
  letter-spacing: .05em;
}
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 18px; height: 5px; border-radius: 3px; display: block; }

.empty { padding: 48px 0; color: var(--muted); text-align: center; }

footer {
  margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--rule);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 11px; color: var(--faint); letter-spacing: .04em;
  display: flex; flex-wrap: wrap; gap: 8px 20px; justify-content: space-between;
}

@media (max-width: 720px) {
  .row { grid-template-columns: 30px minmax(0, 1fr); }
  .data { grid-column: 2; margin-top: 10px; }
  .score { font-size: 22px; }
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
</style>

<div class="wrap">
  <header class="masthead">
    <h1>Radar de Repos</h1>
    <div class="sub" id="sub"></div>
  </header>

  <div class="stats" id="stats"></div>
  <div id="notice"></div>

  <div class="controls">
    <div class="chips" id="chips"></div>
    <span class="spacer"></span>
    <input type="search" id="q" placeholder="Filtrar por nombre o tema…" aria-label="Filtrar repositorios">
    <select id="sort" aria-label="Ordenar por">
      <option value="total">Score total</option>
      <option value="mom">Momentum</option>
      <option value="mat">Madurez</option>
      <option value="stars">Estrellas</option>
      <option value="delta">Estrellas ganadas</option>
    </select>
    <label class="toggle">
      <input type="checkbox" id="hideres"> Ocultar recursos
    </label>
  </div>

  <div class="count" id="count"></div>
  <div class="list" id="list"></div>

  <div class="legend">
    <span><i style="background:var(--hot)"></i> Momentum</span>
    <span><i style="background:var(--warm)"></i> Madurez</span>
    <span><i style="background:var(--accent)"></i> Relevancia</span>
  </div>

  <footer id="footer"></footer>
</div>

<script>
const META = __META__;
const REPOS = __REPOS__;

const AXES = Object.fromEntries(META.axes.map(a => [a.id, a]));
const state = { axes: new Set(), q: "", sort: "total", hideres: false };

try {
  const saved = JSON.parse(localStorage.getItem("radar.filters") || "{}");
  if (Array.isArray(saved.axes)) saved.axes.forEach(a => { if (AXES[a]) state.axes.add(a); });
  if (typeof saved.sort === "string") state.sort = saved.sort;
  if (typeof saved.hideres === "boolean") state.hideres = saved.hideres;
} catch (e) { /* almacenamiento no disponible: se usan los valores por defecto */ }

function save() {
  try {
    localStorage.setItem("radar.filters", JSON.stringify({
      axes: [...state.axes], sort: state.sort, hideres: state.hideres
    }));
  } catch (e) { /* sin persistencia, no pasa nada */ }
}

const esc = s => String(s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- cabecera ---------- */
document.getElementById("sub").textContent =
  `Corrida #${META.run_id} · ${META.captured} · ${META.n_queries} búsquedas`;

document.getElementById("stats").innerHTML = [
  [META.n_total, "repos vigilados"],
  [META.n_new, "nuevos esta corrida"],
  [META.n_hot, "en llamas"],
  [META.n_runs, "corridas acumuladas"],
].map(([n, l]) => `<div class="stat"><span class="n">${n}</span><span class="l">${l}</span></div>`).join("");

if (META.all_provisional) {
  document.getElementById("notice").innerHTML =
    `<div class="notice"><strong>Ranking provisional.</strong> Todavía no hay una corrida
     anterior con la que comparar, así que el momentum se estima con el ritmo promedio
     de cada repo desde que nació. A partir de la segunda corrida el dato pasa a ser real.</div>`;
}

/* ---------- chips de eje ---------- */
document.getElementById("chips").innerHTML = META.axes.map(a =>
  `<button class="chip" data-axis="${a.id}" style="--chip-color:${a.color}"
     aria-pressed="${state.axes.has(a.id)}">${esc(a.short)}<span class="c">${a.count}</span></button>`
).join("");

document.getElementById("chips").addEventListener("click", ev => {
  const btn = ev.target.closest(".chip");
  if (!btn) return;
  const id = btn.dataset.axis;
  state.axes.has(id) ? state.axes.delete(id) : state.axes.add(id);
  btn.setAttribute("aria-pressed", state.axes.has(id));
  save(); render();
});

const qEl = document.getElementById("q");
const sortEl = document.getElementById("sort");
const hideEl = document.getElementById("hideres");
sortEl.value = state.sort;
hideEl.checked = state.hideres;

qEl.addEventListener("input", () => { state.q = qEl.value.toLowerCase().trim(); render(); });
sortEl.addEventListener("change", () => { state.sort = sortEl.value; save(); render(); });
hideEl.addEventListener("change", () => { state.hideres = hideEl.checked; save(); render(); });

/* ---------- render ---------- */
function deltaCell(r) {
  if (r.delta === null || r.delta === undefined)
    return `<span class="flat">sin base</span>`;
  if (r.delta <= 0) return `<span class="flat">±0</span>`;
  return `<span class="up">+${r.delta}</span>`;
}

function render() {
  let rows = REPOS.filter(r => {
    if (state.axes.size && !r.axes.some(a => state.axes.has(a))) return false;
    if (state.hideres && r.flags.includes("recurso")) return false;
    if (state.q) {
      const hay = (r.full_name + " " + r.desc + " " + r.topics.join(" ") + " " + r.lang).toLowerCase();
      if (!hay.includes(state.q)) return false;
    }
    return true;
  });

  const key = state.sort;
  rows.sort((a, b) => (b[key] ?? -1) - (a[key] ?? -1));

  document.getElementById("count").textContent =
    `${rows.length} de ${REPOS.length} repositorios`;

  const w = META.weights;
  document.getElementById("list").innerHTML = rows.length ? rows.map((r, i) => {
    const parts = [
      ["m", r.mom * w.momentum], ["u", r.mat * w.maturity], ["r", r.rel * w.relevance]
    ];
    const bar = parts.map(([c, v]) =>
      `<i class="${c}" style="width:${(v * 100).toFixed(1)}%"></i>`).join("");

    const axisTags = r.axes.map(a =>
      `<span class="tag axis" style="background:${AXES[a].color}">${esc(AXES[a].short)}</span>`).join("");

    const flagTags = r.flags
      .filter(f => ["nuevo", "en-llamas", "maduro", "recurso", "transversal", "contexto-hispano"].includes(f))
      .map(f => `<span class="tag flag-${f}">${esc(f.replace("-", " "))}</span>`).join("");

    return `<article class="row">
      <div class="rank">${String(i + 1).padStart(2, "0")}</div>
      <div class="body">
        <div class="title">
          <a href="${esc(r.url)}" target="_blank" rel="noopener">
            <span class="owner">${esc(r.owner)}/</span>${esc(r.name)}</a>
        </div>
        <p class="desc">${esc(r.desc)}</p>
        <div class="tags">
          ${axisTags}${flagTags}
          <span class="tag meta">${esc(r.lang)}</span>
          <span class="tag meta">${esc(r.license)}</span>
          <span class="tag meta">creado ${esc(r.created)}</span>
          ${r.pushed !== null ? `<span class="tag meta">push hace ${r.pushed}d</span>` : ""}
        </div>
      </div>
      <div class="data">
        <div class="score">${Math.round(r.total * 100)}<span class="max">/100</span></div>
        <div class="bar" title="momentum · madurez · relevancia">${bar}</div>
        <div class="kv"><span>estrellas</span><b>${r.stars.toLocaleString("es")}</b></div>
        <div class="kv"><span>ganadas</span><b>${deltaCell(r)}</b></div>
        <div class="kv"><span>momentum</span><b>${Math.round(r.mom * 100)}</b></div>
        <div class="kv"><span>madurez</span><b>${Math.round(r.mat * 100)}</b></div>
      </div>
    </article>`;
  }).join("") : `<div class="empty">Ningún repositorio pasa estos filtros.</div>`;
}

document.getElementById("footer").innerHTML =
  `<span>Generado ${esc(META.generated)}</span>
   <span>Pesos: momentum ${META.weights.momentum * 100}% · madurez ${META.weights.maturity * 100}% · relevancia ${META.weights.relevance * 100}%</span>`;

render();
</script>
"""


def build(config_path=None, db_path=None, out=None, run_id=None) -> Path:
    cfg = load_config(config_path or CONFIG_PATH)
    conn = connect(db_path or DB_PATH)

    if run_id is None:
        row = conn.execute("SELECT MAX(run_id) AS r FROM runs").fetchone()
        run_id = row["r"]
    if not run_id:
        raise SystemExit("No hay corridas todavía. Ejecuta el recolector primero.")

    meta, repos = collect_data(conn, cfg, run_id)
    conn.close()

    html = (TEMPLATE
            .replace("__META__", json.dumps(meta, ensure_ascii=False))
            .replace("__REPOS__", json.dumps(repos, ensure_ascii=False)))

    out_path = Path(out or DEFAULT_OUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"Dashboard generado: {out_path} ({len(repos)} repos, "
          f"{len(html) // 1024} KB)")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Dashboard del radar de repos")
    ap.add_argument("--config")
    ap.add_argument("--db")
    ap.add_argument("--out")
    ap.add_argument("--run", type=int)
    args = ap.parse_args()
    build(args.config, args.db, args.out, args.run)


if __name__ == "__main__":
    main()
