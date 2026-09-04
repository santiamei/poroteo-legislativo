#!/usr/bin/env python3
"""Compara la cohesión de bloque (Rice) sobre las 42 actas FONDO_GENERAL
contra la cohesión sobre solo las 13 disputadas (división > 0.15), para
ver qué bloques eran disciplinados nomás por el consenso y se quiebran
cuando hay conflicto real.

Reutiliza calcular_cohesion_bloques.calcular_cohesion() -la misma
definición de Rice, mismo umbral de 2 miembros con posición- restringiendo
las filas de entrada a los acta_id disputados.

No calcula subgrupos -eso es el paso siguiente, sobre estas 13 actas.

Uso:
    python ingesta/comparar_cohesion_disputadas.py
"""

import csv
from pathlib import Path

from calcular_cohesion_bloques import VOTOS_PATH, calcular_cohesion

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "processed" / "cohesion_comparativa_disputadas.csv"

# Las 13 actas FONDO_GENERAL con índice de división > 0.15 (ver
# division_actas_fondo_general.csv del paso anterior).
ACTAS_DISPUTADAS = {
    "5822", "5956", "5853", "5838", "5902", "5931", "5974",
    "5971", "5919", "5955", "5847", "5981", "5849",
}


def cargar_filas(categoria_universo="FONDO_GENERAL"):
    with open(VOTOS_PATH, encoding="utf-8") as f:
        return [
            fila for fila in csv.DictReader(f)
            if fila["categoria_votacion"] == categoria_universo
        ]


def main():
    filas_42 = cargar_filas()
    filas_13 = [f for f in filas_42 if f["acta_id"] in ACTAS_DISPUTADAS]

    assert len(ACTAS_DISPUTADAS) == 13, "esperaba exactamente 13 actas disputadas"
    assert {f["acta_id"] for f in filas_13} == ACTAS_DISPUTADAS, \
        "alguna acta disputada no aparece en el universo FONDO_GENERAL"

    tabla_42 = {r["bloque"]: r for r in calcular_cohesion(filas_42)}
    tabla_13 = {r["bloque"]: r for r in calcular_cohesion(filas_13)}

    comparativa = []
    for bloque, r42 in tabla_42.items():
        r13 = tabla_13.get(bloque)
        rice_42 = r42["cohesion_rice_promedio"]
        rice_13 = r13["cohesion_rice_promedio"] if r13 else None
        diferencia = (rice_13 - rice_42) if (rice_13 is not None and rice_42 is not None) else None
        comparativa.append({
            "bloque": bloque,
            "rice_42": rice_42,
            "rice_13": rice_13,
            "diputados_en_13": r13["diputados_del_bloque"] if r13 else 0,
            "actas_incluidas_13": r13["actas_incluidas_en_cohesion"] if r13 else 0,
            "diferencia": diferencia,
        })

    comparativa.sort(key=lambda r: (r["rice_13"] is None, -(r["rice_13"] or 0)))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "bloque", "rice_42", "rice_13", "diputados_en_13", "actas_incluidas_13", "diferencia",
        ])
        writer.writeheader()
        writer.writerows(comparativa)

    print(f"Actas disputadas usadas: {len(ACTAS_DISPUTADAS)}\n")
    print(f"{'bloque':<75} {'rice42':>7} {'rice13':>7} {'dip.':>5} {'actas13':>7} {'diff':>7}")
    for r in comparativa:
        r42_s = f"{r['rice_42']:.3f}" if r["rice_42"] is not None else "  N/A"
        r13_s = f"{r['rice_13']:.3f}" if r["rice_13"] is not None else "  N/A"
        diff_s = f"{r['diferencia']:+.3f}" if r["diferencia"] is not None else "  N/A"
        print(f"{r['bloque']:<75} {r42_s:>7} {r13_s:>7} {r['diputados_en_13']:>5} "
              f"{r['actas_incluidas_13']:>7} {diff_s:>7}")

    print(f"\nGuardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
