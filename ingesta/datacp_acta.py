#!/usr/bin/env python3
"""Ingesta de una acta de votación nominal desde Data CP (datacp.ar).

Primer paso del pipeline de ingesta: trae y parsea UNA acta para validar
el mecanismo antes de escalar a todas. No hace enumeración ni batch.

Fuente: solo páginas SSR de datacp.ar (nunca /api/ — su robots.txt lo
prohíbe explícitamente con "Disallow: /api/", aunque los endpoints
respondan igual; ver recon de datacp.ar). La página de detalle de acta es
Next.js App Router con RSC streaming: el JSON completo (metadata del acta
+ roster de votos por diputado) viene embebido en el HTML inicial dentro
de un <script>self.__next_f.push(...)</script>, así que un solo GET con
requests alcanza — no hace falta ni XHR adicional ni un navegador headless.

Uso:
    python ingesta/datacp_acta.py [camara] [acta_id]
    python ingesta/datacp_acta.py diputados 5995   # default si no se pasan args
"""

import json
import re
import sys
from pathlib import Path

import requests

BASE_URL = "https://www.datacp.ar"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = (5, 15)  # (connect, read) segundos
RAW_DATA_DIR = Path(__file__).parent.parent / "data" / "raw" / "datacp"


def fetch_acta_html(camara, acta_id):
    url = f"{BASE_URL}/congreso/votacion/{camara}/{acta_id}"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def extract_acta_payload(html):
    """Extrae {"acta": {...}, "roster": [...]} del payload RSC embebido en
    el HTML de la página de detalle. Ver recon de datacp.ar para el porqué
    de este parseo: los datos vienen server-side dentro de un
    self.__next_f.push([1, "<json escapado>"]) </script>, no en un <table>
    a scrapear."""
    marker = '\\"roster\\"'
    marker_idx = html.find(marker)
    if marker_idx == -1:
        raise RuntimeError(
            "No se encontró el marcador 'roster' en el HTML — el sitio "
            "puede haber cambiado de formato (era Next.js RSC streaming "
            "al momento del reconocimiento)."
        )

    script_start = html.rfind("<script>self.__next_f.push", 0, marker_idx)
    script_end = html.find("</script>", script_start)
    if script_start == -1 or script_end == -1:
        raise RuntimeError("No se pudo delimitar el <script> que contiene el payload RSC.")

    raw_script = html[script_start:script_end]
    m = re.search(r'push\(\[1,"(.*)"\]\)$', raw_script, re.S)
    if not m:
        raise RuntimeError("No se pudo extraer el string interno del chunk self.__next_f.push.")

    # El contenido es el cuerpo de un string JSON (comillas exteriores ya
    # quitadas por el regex) — envolverlo en comillas y usar json.loads para
    # des-escaparlo correctamente (\", \\, \uXXXX) sin romper acentos UTF-8
    # (un .encode().decode('unicode_escape') directo los corrompe).
    text = json.loads('"' + m.group(1) + '"')

    acta_idx = text.find('"acta":{')
    if acta_idx == -1:
        raise RuntimeError("El chunk no contiene la clave 'acta' esperada.")

    obj_start = text.rfind("{", 0, acta_idx)
    depth = 0
    i = obj_start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        raise RuntimeError("No se pudo balancear las llaves del objeto acta+roster.")

    return json.loads(text[obj_start : i + 1])


def recalcular_agregados(roster):
    """Cuenta los votos del roster. Los campos agregados que trae Data CP
    en el objeto "acta" (afirmativos/negativos/abstenciones/ausentes) están
    rotos: para el acta 5995 dan 0/0/1/0 cuando el roster real tiene
    220 AFIRMATIVO + 36 AUSENTE + 1 PRESIDENTE = 257. Por eso siempre se
    recalculan contando el roster, nunca se usan esos campos de Data CP."""
    conteo = {}
    for persona in roster:
        voto = persona["voto"]
        conteo[voto] = conteo.get(voto, 0) + 1
    return conteo


def guardar_raw(camara, acta_id, payload):
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DATA_DIR / f"acta_{camara}_{acta_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def ingerir_acta(camara, acta_id):
    html = fetch_acta_html(camara, acta_id)
    payload = extract_acta_payload(html)
    agregados = recalcular_agregados(payload["roster"])
    ruta = guardar_raw(camara, acta_id, payload)
    return payload, agregados, ruta


if __name__ == "__main__":
    camara = sys.argv[1] if len(sys.argv) > 1 else "diputados"
    acta_id = sys.argv[2] if len(sys.argv) > 2 else "5995"

    payload, agregados, ruta = ingerir_acta(camara, acta_id)
    acta = payload["acta"]
    roster = payload["roster"]

    print("=== metadata del acta ===")
    for campo in ("acta_id", "titulo", "fecha", "resultado", "article", "url"):
        print(f"{campo}: {acta.get(campo)!r}")

    print("\n=== agregados recalculados desde el roster (NO los de Data CP) ===")
    for voto, n in sorted(agregados.items()):
        print(f"{voto}: {n}")
    print(f"total roster: {len(roster)}")

    print(f"\n=== primeras 10 filas del roster (de {len(roster)}) ===")
    for fila in roster[:10]:
        print(fila)

    print(f"\nGuardado en: {ruta}")
