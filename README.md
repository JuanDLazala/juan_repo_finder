# Radar de Repos

Monitorea GitHub cada dos días y rankea los repositorios más relevantes en cinco
ejes: escucha social, política y electoral, producción creativa, adtech y
performance, y agentes/LLM/MCP.

No hace *web scraping*: usa la API oficial de búsqueda de GitHub, que es más
rápida, más completa y no se bloquea.

---

## 1. Qué hace, en orden

| Paso | Archivo | Qué hace |
|---|---|---|
| Recolectar | `radar/collector.py` | Ejecuta 46 búsquedas contra la API y guarda todo en `data/radar.db` |
| Rankear | `radar/scorer.py` | Calcula momentum, madurez y relevancia de cada repo |
| Publicar | `radar/build_dashboard.py` | Genera `docs/index.html`, un dashboard de un solo archivo |

Todo lo orquesta `.github/workflows/radar.yml`, que corre solo cada dos días a
las 6:00 a.m. hora Colombia y commitea los resultados de vuelta al repo.

## 2. Cómo se calcula el ranking

**Momentum (50%)** — estrellas ganadas desde la corrida anterior. Combina el
ritmo absoluto (estrellas/día) con el relativo (% de crecimiento diario), así
que un repo pequeño que crece 3% al día puede ganarle a uno gigante y estancado.

> La primera corrida no tiene con qué comparar. En ese caso el momentum se
> estima con el ritmo promedio desde que nació el repo y se marca como
> **provisional** (con un castigo del 30%). Desde la segunda corrida el dato
> es real.

**Madurez (35%)** — suma de señales verificables: descripción real, licencia
permisiva, push reciente, temas declarados, proporción sana de forks e issues,
tamaño de código, documentación publicada y edad suficiente para no ser humo.

**Relevancia (15%)** — cuántos términos del léxico del eje aparecen en el
nombre, la descripción y los temas. Suma extra si aparece en varios ejes o si
menciona español, Latinoamérica o contexto electoral. Resta si parece un recurso
de estudio (lista *awesome*, tutorial, curso) en vez de una librería usable.

## 3. Instalación

### Paso 1 — Crear el repositorio privado

1. En GitHub, arriba a la derecha, **+** → **New repository**.
2. Nombre: `radar-repos`. Marca **Private**. No añadas README ni .gitignore.
3. **Create repository**.

### Paso 2 — Subir los archivos

Descomprime la carpeta que te entregué y, dentro de ella:

```bash
git init
git add .
git commit -m "Radar de repos: versión inicial"
git branch -M main
git remote add origin https://github.com/JuanDLazala/juan_repo_finder.git
git push -u origin main
```

Si prefieres no usar la terminal: en el repo vacío, **uploading an existing
file**, y arrastra todo. Ojo — el explorador de archivos de Windows y macOS
oculta la carpeta `.github`, y sin ella no hay automatización. Con arrastrar y
soltar suele subir igual; verifica después que `.github/workflows/radar.yml`
aparezca en el repo.

### Paso 3 — Dar permiso de escritura al workflow

Esto es lo que más se olvida y hace fallar la primera corrida.

1. En tu repo: **Settings** → **Actions** → **General**.
2. Baja hasta **Workflow permissions**.
3. Marca **Read and write permissions** y **Save**.

### Paso 4 — La primera corrida

1. Pestaña **Actions** → si aparece un aviso de workflows deshabilitados,
   dale **I understand my workflows, go ahead and enable them**.
2. En la izquierda, **Radar de repos** → botón **Run workflow** → **Run**.
3. Tarda entre 3 y 6 minutos.

Cuando termine, el dashboard queda en `docs/index.html` dentro del repo, y
también como archivo descargable en la sección **Artifacts** de esa corrida.

### Paso 5 — El token (solo si el paso 4 falla)

El workflow usa primero el token automático de GitHub Actions, que normalmente
alcanza para buscar repositorios públicos. **Prueba sin token primero.** Si la
corrida falla con errores 401 o 403, entonces crea uno:

1. Tu foto de perfil → **Settings** (los ajustes de tu cuenta, no los del repo).
2. Al final del menú izquierdo: **Developer settings**.
3. **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
4. Rellena así:
   - **Token name**: `radar-repos`
   - **Expiration**: 1 año (anótalo, hay que renovarlo)
   - **Resource owner**: tu usuario
   - **Repository access**: **Public repositories (read-only)**
   - No toques ningún otro permiso. Este token solo puede *leer* repos
     públicos: no puede tocar nada tuyo ni aunque se filtre.
5. **Generate token** y copia el valor. Solo se muestra una vez.
6. Vuelve a tu repo → **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**.
   - **Name**: `RADAR_GITHUB_TOKEN`
   - **Secret**: pega el token
7. **Add secret** y vuelve a lanzar el workflow.

## 4. Cómo cambiar qué busca

Todo vive en `config.yaml` y no necesitas tocar código.

- **Añadir un tema**: agrega una línea a `queries` dentro del eje que
  corresponda. Cualquier búsqueda que funcione en la barra de GitHub funciona
  aquí (`topic:algo`, `palabras sueltas`, `language:Python`).
- **Cambiar el umbral de ruido**: sube `min_stars` si ves demasiada paja,
  bájalo si sientes que se te escapan proyectos nuevos.
- **Ampliar la ventana**: `max_age_months` controla qué tan viejo puede ser un
  repo; `max_idle_days`, qué tan abandonado.
- **Reajustar el ranking**: los tres pesos en `weights` deben sumar 1.0. Si
  quieres cosas más estables y menos hype, sube `maturity` y baja `momentum`.

Para ver qué búsquedas se van a ejecutar sin gastar llamadas:

```bash
python -m radar.collector --dry-run
```

## 5. Probar en local

```bash
pip install -r requirements.txt
python tests/test_pipeline.py
```

Simula dos corridas separadas por dos días con datos falsos y verifica que el
momentum, el ranking y el dashboard funcionen. No toca la API real.

## 6. Cosas que conviene saber

- **Costo**: cero. Actions da 2.000 minutos gratis al mes en repos privados y
  este proyecto gasta unos 75.
- **La base de datos crece con el tiempo** y esa es la gracia: cada corrida
  añade una foto del estado de cada repo. Después de un mes puedes responder
  preguntas como "qué creció más en agosto".
- **GitHub apaga los workflows programados** en repos sin actividad humana
  durante 60 días. Si un día notas que dejó de correr, haz cualquier commit
  (por ejemplo, editar este README) y se reactiva.
- **El dashboard no se publica en internet** porque el repo es privado. Se
  descarga desde Actions, o se abre desde `docs/index.html` en tu equipo.
