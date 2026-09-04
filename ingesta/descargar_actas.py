#!/usr/bin/env python3
"""Descarga en bulk el detalle de actas de diputados desde Data CP,
usando la misma lógica de parseo validada en datacp_acta.py (página SSR
+ payload RSC embebido en el HTML — nunca /api/, por robots.txt).

Lee ingesta/actas_a_descargar.json (lista de {actaId, titulo, fecha,
resultado}) y para cada una, si no está ya en caché local, la baja y
guarda en data/raw/datacp/acta_diputados_{actaId}.json.

Resumible: si ya existe el archivo de una acta, se saltea sin pedirla de
nuevo. Secuencial (sin concurrencia), con pausa de 3-5s con jitter entre
cada request real. Si fallan 3 actas seguidas, frena todo (probable
bloqueo) en vez de seguir insistiendo.

Uso:
    python ingesta/descargar_actas.py <N|all>
    python ingesta/descargar_actas.py 3      # modo de prueba: primeras 3
    python ingesta/descargar_actas.py all    # las 124 completas
"""

import json
import random
import sys
import time
from pathlib import Path

import requests

from datacp_acta import (
    RAW_DATA_DIR,
    extract_acta_payload,
    fetch_acta_html,
    guardar_raw,
    recalcular_agregados,
)

CAMARA = "diputados"
LISTA_PATH = Path(__file__).parent / "actas_a_descargar.json"
PAUSA_MIN_SEG = 3.0
PAUSA_MAX_SEG = 5.0
FALLOS_CONSECUTIVOS_LIMITE = 3


def ruta_cache(acta_id):
    return RAW_DATA_DIR / f"acta_{CAMARA}_{acta_id}.json"


def ya_descargada(acta_id):
    return ruta_cache(acta_id).exists()


def descargar_una(acta_id):
    """Fetch + parse + guardar. Deja que las excepciones suban — las
    maneja el loop principal para registrar el fallo y seguir."""
    html = fetch_acta_html(CAMARA, acta_id)
    payload = extract_acta_payload(html)
    recalcular_agregados(payload["roster"])  # solo para validar consistencia al vuelo
    return guardar_raw(CAMARA, acta_id, payload)


def descargar_lote(actas, limite=None):
    if limite is not None:
        actas = actas[:limite]

    total = len(actas)
    salteadas = 0
    descargadas = 0
    fallidas = []  # [{actaId, titulo, motivo}]
    fallos_consecutivos = 0
    abortado = False

    for i, acta in enumerate(actas, start=1):
        acta_id = acta["actaId"]
        titulo_corto = acta["titulo"][:60]
        restantes = total - i

        if ya_descargada(acta_id):
            salteadas += 1
            print(f"[{i}/{total}] acta {acta_id} — {titulo_corto} -> SALTEADA (ya en cache) "
                  f"| restantes: {restantes} | salteadas: {salteadas}")
            continue

        try:
            ruta = descargar_una(acta_id)
        except (requests.RequestException, RuntimeError) as exc:
            fallos_consecutivos += 1
            fallidas.append({"actaId": acta_id, "titulo": acta["titulo"], "motivo": str(exc)})
            print(f"[{i}/{total}] acta {acta_id} — {titulo_corto} -> FALLÓ: {exc} "
                  f"| fallos consecutivos: {fallos_consecutivos}")

            if fallos_consecutivos >= FALLOS_CONSECUTIVOS_LIMITE:
                print(f"\n!! {fallos_consecutivos} fallos seguidos — frenando la corrida "
                      "(probable bloqueo del sitio). No se siguió con el resto de la lista.")
                abortado = True
                break

            pausa = random.uniform(PAUSA_MIN_SEG, PAUSA_MAX_SEG)
            time.sleep(pausa)
            continue

        fallos_consecutivos = 0
        descargadas += 1
        print(f"[{i}/{total}] acta {acta_id} — {titulo_corto} -> OK ({ruta.name}) "
              f"| restantes: {restantes} | descargadas: {descargadas}")

        pausa = random.uniform(PAUSA_MIN_SEG, PAUSA_MAX_SEG)
        time.sleep(pausa)

    no_intentadas = total - (salteadas + descargadas + len(fallidas))
    return {
        "total_en_este_lote": total,
        "descargadas": descargadas,
        "salteadas_por_cache": salteadas,
        "fallidas": fallidas,
        "no_intentadas_por_aborto": no_intentadas,
        "abortado": abortado,
    }


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1]
    limite = None if arg == "all" else int(arg)

    actas = json.loads(LISTA_PATH.read_text(encoding="utf-8"))
    resumen = descargar_lote(actas, limite=limite)

    print("\n=== resumen ===")
    print(f"lote procesado: {resumen['total_en_este_lote']}")
    print(f"descargadas ahora: {resumen['descargadas']}")
    print(f"salteadas (ya en cache): {resumen['salteadas_por_cache']}")
    print(f"fallidas: {len(resumen['fallidas'])}")
    for f in resumen["fallidas"]:
        print(f"  - acta {f['actaId']}: {f['motivo']}")
    if resumen["abortado"]:
        print(f"no intentadas (corrida abortada por fallos consecutivos): "
              f"{resumen['no_intentadas_por_aborto']}")


if __name__ == "__main__":
    main()
