#!/usr/bin/env python3
"""Reconocimiento de solo lectura del portal CKAN de datos.hcdn.gob.ar.

No descarga datasets completos. Solo consulta metadata (package_list /
package_show) y, para los recursos CSV relevantes, los primeros KB del
archivo (via Range request) para inferir codificación, columnas y una
fila de ejemplo. Pensado para mapear qué hay disponible antes de
construir el pipeline de datos real.

Uso:
    python recon/recon_ckan.py
Genera recon/manifest.txt además de imprimir todo por stdout.
"""

import csv
import re
import time
from datetime import date
from pathlib import Path

import requests
from charset_normalizer import from_bytes
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://datos.hcdn.gob.ar/api/3/action"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT = (5, 15)  # (connect, read) segundos — ninguna llamada queda colgada
MAX_RETRIES = 2
BACKOFF_FACTOR = 1.0  # espera ~1s, 2s entre reintentos (corta, no exponencial larga)
PARTIAL_BYTES = 16 * 1024
DATE_THRESHOLD = date(2025, 12, 10)
MANIFEST_PATH = Path(__file__).parent / "manifest.txt"

# Grupos de palabras clave para identificar datasets relevantes por su slug/título.
# Nota: NO se usa "diputado" como keyword — aparece en el nombre institucional
# ("Cámara de Diputados") de datasets sin relación con legisladores/votaciones
# (ej. "ejecucion-presupuestaria-de-la-camara-de-diputados..."), y generaba
# falsos positivos que disparaban descargas de muestra innecesarias.
KEYWORDS = {
    "votaciones": ["votacion"],
    "bloques": ["bloque", "interbloque"],
    "legisladores": ["legislador"],
    "comisiones": ["comision"],
}

# Slugs de los datasets "maestro" reales de cada categoría — el muestreo de
# CSV (paso 4) se limita a estos, aunque otros datasets matcheen la keyword
# (ej. "dietas-y-gastos-de-representacion-legisladores-as" es de legisladores
# pero no es el maestro de legisladores; se identifica pero no se muestrea).
MASTER_SLUGS = {
    "bloques": {"bloques-interbloques-e-integracion"},
    "legisladores": {"legisladores"},
}

# Heurística de fecha por número de período: el dataset "Votaciones Nominales
# período 135" fue publicado en oct-2017 con datos de ese año, así que
# estimamos año_calendario = período + 1882. Es una aproximación para
# marcar candidatos a revisar a mano, no un mapeo oficial de la HCDN.
PERIOD_YEAR_OFFSET = 1882
PERIOD_RE = re.compile(r"per[ií]odos?\s+(\d+)(?:\s+an?\s+(\d+))?", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(20\d{2})\b")
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")

manifest_lines = []


def log(msg=""):
    print(msg, flush=True)
    manifest_lines.append(msg)


def step(msg):
    """Log de progreso en vivo (también queda en el manifiesto)."""
    log(f">> {msg}")


def build_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def ckan_get(session, action, **params):
    resp = session.get(f"{BASE_URL}/{action}", params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"CKAN action {action} devolvió success=false: {data}")
    return data["result"]


def relevant_categories(text):
    text_l = text.lower()
    return [cat for cat, kws in KEYWORDS.items() if any(kw in text_l for kw in kws)]


def estimate_date_flag(name):
    """Heurística de fecha a partir del nombre del recurso. Devuelve
    (flag_posterior_al_umbral | None, explicación)."""
    iso = ISO_DATE_RE.search(name)
    if iso:
        y, m, d = map(int, iso.groups())
        try:
            found = date(y, m, d)
        except ValueError:
            found = None
        if found:
            return found >= DATE_THRESHOLD, f"fecha explícita en nombre: {found.isoformat()}"

    period_match = PERIOD_RE.search(name)
    if period_match:
        periods = [int(g) for g in period_match.groups() if g]
        max_period = max(periods)
        est_year = max_period + PERIOD_YEAR_OFFSET
        est_date = date(est_year, 12, 10)
        flag = est_date >= DATE_THRESHOLD
        return (
            flag,
            f"período {max_period} -> año estimado {est_year} "
            f"(heurística no oficial, revisar a mano)",
        )

    year_match = YEAR_RE.search(name)
    if year_match:
        y = int(year_match.group(1))
        return (
            y >= 2026,
            f"año suelto detectado en nombre: {y} (sin período ni fecha completa, revisar a mano)",
        )

    return None, "sin período ni fecha detectable en el nombre del recurso"


def fetch_partial(session, url, n_bytes=PARTIAL_BYTES):
    headers = {"Range": f"bytes=0-{n_bytes - 1}"}
    resp = session.get(url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT)
    try:
        resp.raise_for_status()
        chunk = b""
        for part in resp.iter_content(chunk_size=4096):
            chunk += part
            if len(chunk) >= n_bytes:
                break
        return chunk[:n_bytes]
    finally:
        resp.close()


def sniff_csv(raw_bytes):
    """Devuelve (encoding, header, sample_row) a partir de bytes parciales."""
    detected = from_bytes(raw_bytes).best()
    encoding = detected.encoding if detected else "utf-8"
    try:
        text = raw_bytes.decode(encoding, errors="replace")
    except (LookupError, TypeError):
        encoding = "utf-8 (fallback)"
        text = raw_bytes.decode("utf-8", errors="replace")

    lines = text.splitlines()
    # Descartamos la última línea: puede estar cortada por el límite de bytes.
    usable_lines = lines[:-1] if len(lines) > 1 else lines
    if not usable_lines:
        return encoding, [], None

    sample_block = "\n".join(usable_lines[:5])
    try:
        dialect = csv.Sniffer().sniff(sample_block, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if usable_lines[0].count(";") >= usable_lines[0].count(",") else ","

    rows = list(csv.reader(usable_lines, delimiter=delimiter))
    header = rows[0] if rows else []
    sample_row = rows[1] if len(rows) > 1 else None
    return encoding, header, sample_row


def is_votaciones_resource(name):
    name_l = name.lower()
    return "cabecera" in name_l or "detalle" in name_l


def extract_periods(name):
    """Todos los números de período referenciados en el nombre (soporta rangos)."""
    m = PERIOD_RE.search(name)
    if not m:
        return []
    return [int(g) for g in m.groups() if g]


def find_fecha_sample(header, sample_row):
    """Busca una columna de fecha en la muestra y devuelve (nombre_col, valor)."""
    for i, col in enumerate(header):
        if "fecha" in col.lower():
            value = sample_row[i] if sample_row and i < len(sample_row) else None
            return col, value
    return None, None


def main(smoke_test=False):
    session = build_session()
    log(f"# Reconocimiento CKAN — datos.hcdn.gob.ar")
    log(f"# Generado: {date.today().isoformat()} | umbral de fecha: {DATE_THRESHOLD.isoformat()}")
    log("")

    # 1) package_list
    log("## 1. Datasets disponibles (package_list)")
    step("consultando package_list...")
    all_slugs = ckan_get(session, "package_list")
    log(f"Total datasets: {len(all_slugs)}")
    for slug in all_slugs:
        log(f"  - {slug}")
    log("")

    if smoke_test:
        log(">> SMOKE TEST: package_list respondió OK, frenando acá (--smoke-test).")
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        return

    time.sleep(REQUEST_DELAY_SECONDS)

    # 2) Filtrar slugs relevantes por nombre
    matched = []
    for slug in all_slugs:
        cats = relevant_categories(slug)
        if cats:
            matched.append((slug, cats))

    log("## 2. Datasets relevantes identificados por slug")
    for slug, cats in matched:
        log(f"  - {slug}  ->  categorías: {', '.join(cats)}")
    log("")

    # 3) package_show por cada dataset relevante
    download_targets = []  # (categoria, dataset_slug, resource dict)
    log("## 3. Detalle de recursos por dataset")
    for slug, cats in matched:
        step(f"procesando dataset {slug} (package_show)...")
        try:
            pkg = ckan_get(session, "package_show", id=slug)
        except requests.RequestException as exc:
            log(f"### {slug}: FALLÓ package_show ({exc}) — se saltea y se sigue con el resto")
            log("")
            time.sleep(REQUEST_DELAY_SECONDS)
            continue
        time.sleep(REQUEST_DELAY_SECONDS)

        title = pkg.get("title", "")
        resources = pkg.get("resources", [])
        log(f"### {slug}  |  título: {title}  |  categorías: {', '.join(cats)}")
        log(f"    metadata_modified (dataset): {pkg.get('metadata_modified')}")
        log(f"    recursos: {len(resources)}")
        for res in resources:
            name = res.get("name") or "(sin nombre)"
            rid = res.get("id")
            fmt = (res.get("format") or "").upper()
            url = res.get("url")
            last_mod = res.get("last_modified") or res.get("created") or "(sin fecha)"
            log(f"    - [{fmt}] {name}")
            log(f"        id: {rid}")
            log(f"        url: {url}")
            log(f"        última modificación: {last_mod}")

            if fmt == "CSV" and url:
                if "votaciones" in cats and is_votaciones_resource(name):
                    download_targets.append(("votaciones", slug, res))
                elif "bloques" in cats and slug in MASTER_SLUGS["bloques"]:
                    download_targets.append(("bloques", slug, res))
                elif "legisladores" in cats and slug in MASTER_SLUGS["legisladores"]:
                    download_targets.append(("legisladores", slug, res))
        log("")

    # 4) Descarga parcial + sniff de columnas para recursos CSV relevantes
    log("## 4. Muestreo de recursos CSV relevantes (primeros "
        f"{PARTIAL_BYTES // 1024} KB, sin descargar el archivo completo)")
    failed_samples = []
    votaciones_samples = []  # info detallada por recurso de votaciones muestreado
    for cat, slug, res in download_targets:
        name = res.get("name") or "(sin nombre)"
        url = res.get("url")
        step(f"descargando muestra de recurso: {slug} :: {name}...")
        log(f"### [{cat}] {slug} :: {name}")
        try:
            raw = fetch_partial(session, url)
        except requests.RequestException as exc:
            log(f"    FALLÓ la descarga de muestra: {exc} — se saltea y se sigue con el resto")
            log("")
            failed_samples.append((slug, name))
            time.sleep(REQUEST_DELAY_SECONDS)
            continue
        time.sleep(REQUEST_DELAY_SECONDS)

        encoding, header, sample_row = sniff_csv(raw)
        log(f"    bytes muestreados: {len(raw)}")
        log(f"    codificación detectada: {encoding}")
        log(f"    columnas ({len(header)}): {header}")
        log(f"    fila de ejemplo: {sample_row}")

        if cat == "votaciones":
            tipo = "cabecera" if "cabecera" in name.lower() else "detalle"
            flag, reason = estimate_date_flag(name)
            if flag is True:
                marca = "POSTERIOR a 2025-12-10 (revisar)"
            elif flag is False:
                marca = "anterior a 2025-12-10"
            else:
                marca = "indeterminado"
            fecha_col, fecha_val = find_fecha_sample(header, sample_row)
            log(f"    tipo de recurso de votación: {tipo}")
            log(f"    fecha vs. umbral 2025-12-10 (heurística por período): {marca} — {reason}")
            if fecha_col:
                log(f"    columna de fecha real en la muestra: '{fecha_col}' = {fecha_val!r} "
                    "(fecha del primer registro de la muestra, no necesariamente representativa "
                    "de todo el archivo)")
            else:
                log("    no se encontró columna de fecha en las columnas muestreadas")
            votaciones_samples.append({
                "slug": slug,
                "name": name,
                "tipo": tipo,
                "url": url,
                "last_modified": res.get("last_modified") or res.get("created"),
                "periods": extract_periods(name),
                "flag": flag,
                "reason": reason,
                "fecha_col": fecha_col,
                "fecha_val": fecha_val,
            })
        log("")

    # 5) Resumen de recursos de votaciones posteriores al umbral
    log("## 5. Resumen — recursos de votaciones posteriores a 2025-12-10")
    posteriores = []
    for cat, slug, res in download_targets:
        if cat != "votaciones":
            continue
        name = res.get("name") or ""
        flag, reason = estimate_date_flag(name)
        if flag:
            posteriores.append((slug, name, reason))
    if posteriores:
        for slug, name, reason in posteriores:
            log(f"  - {slug} :: {name}  ({reason})")
    else:
        log("  Ninguno de los recursos de votaciones muestreados parece "
            "posterior al 2025-12-10 según nombre/período disponible. "
            "El período más reciente encontrado en el portal es anterior "
            "a esa fecha; puede haber datos más nuevos aún no publicados "
            "como dataset, o publicados con un nombre que esta heurística "
            "no reconoce.")
    log("")

    # 5b) Período más reciente vs. período inmediatamente anterior — para
    # ubicar el corte del 10/12/2025 (votos desde esa fecha pueden estar
    # repartidos entre el último período y el que lo precede).
    log("## 5b. Período más reciente vs. anterior (corte 10/12/2025)")
    all_periods = sorted({p for s in votaciones_samples for p in s["periods"]}, reverse=True)
    if len(all_periods) < 2:
        log("  No se encontraron al menos dos números de período distintos entre "
            "los recursos de votaciones muestreados; no se puede armar la "
            "comparación más reciente / anterior.")
    else:
        latest_period, previous_period = all_periods[0], all_periods[1]
        for period, etiqueta in (
            (latest_period, "PERÍODO MÁS RECIENTE (candidato a cubrir 2026)"),
            (previous_period, "PERÍODO ANTERIOR (candidato a cubrir fin de 2025 / dic-2025)"),
        ):
            est_year = period + PERIOD_YEAR_OFFSET
            log(f"  --- {etiqueta}: período {period} (año estimado {est_year}, heurística) ---")
            matches = [s for s in votaciones_samples if period in s["periods"]]
            if not matches:
                log(f"      (no se tomó muestra CSV de ningún recurso que referencie el período {period})")
                continue
            for s in matches:
                log(f"      - [{s['tipo']}] {s['slug']} :: {s['name']}")
                log(f"          url: {s['url']}")
                log(f"          última modificación (metadata CKAN): {s['last_modified']}")
                if s["fecha_col"]:
                    log(f"          fecha real de ejemplo (columna '{s['fecha_col']}'): {s['fecha_val']!r}")
                else:
                    log("          fecha real de ejemplo: no encontrada en las columnas muestreadas")
        log("")
        log("  Nota: el corte de período de HCDN no necesariamente coincide con "
            "el 10/12/2025 exacto (los períodos son heurísticos, no un mapeo "
            "oficial). Para votaciones desde el 10/12/2025 en adelante hay que "
            "revisar ambos recursos de arriba y filtrar por la columna de fecha "
            "real del archivo completo, no solo por el número de período.")
    log("")

    log("## Nota sobre 'comisiones'")
    log("  El dataset de comisiones se identificó y se listaron sus recursos "
        "en la sección 3, pero -según lo pedido- no se tomó muestra parcial "
        "de sus CSV (el muestreo se limitó a votaciones, bloques y legisladores).")
    log("")

    log("## Recursos cuya muestra falló")
    if failed_samples:
        for slug, name in failed_samples:
            log(f"  - {slug} :: {name}")
    else:
        log("  Ninguno.")

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(f"\nManifiesto guardado en: {MANIFEST_PATH}")


if __name__ == "__main__":
    import sys

    main(smoke_test="--smoke-test" in sys.argv)
