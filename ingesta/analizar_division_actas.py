#!/usr/bin/env python3
"""Calcula el índice de división de cada acta FONDO_GENERAL, para separar
votaciones de consenso de votaciones disputadas. Trabaja sobre
data/processed/votos_consolidado.csv.

Índice de división de una acta:
    minoria = total_posiciones_validas - max(afirmativos, negativos, abstenciones)
    division = minoria / total_posiciones_validas

"Posición válida" = AFIRMATIVO, NEGATIVO o ABSTENCION (se excluyen
AUSENTE, PRESIDENTE y cualquier otro valor, igual que en la matriz de
acuerdo y la cohesión de bloque).

La "minoría" es todo lo que no forma parte del grupo más grande de las
tres categorías -no asume que la abstención sea irrelevante: si en una
acta la abstención fuera el segundo grupo más numeroso, cuenta como parte
de la minoría igual que un NEGATIVO. Con dos grupos (caso típico:
abstenciones ~0), esto se reduce a min(afirmativos, negativos)/total,
que es la lectura intuitiva de "qué tan peleada estuvo la votación".

Ejemplo: 220 vs 0 -> división 0.0 (consenso). 70 vs 65 -> división
65/135 ≈ 0.48 (muy disputada).

Solo mapea división — no recalcula cohesión ni subgrupos.

Uso:
    python ingesta/analizar_division_actas.py [UMBRAL]
    python ingesta/analizar_division_actas.py 0.15   # default
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

VOTOS_PATH = Path(__file__).parent.parent / "data" / "processed" / "votos_consolidado.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "processed" / "division_actas_fondo_general.csv"

CATEGORIA_UNIVERSO = "FONDO_GENERAL"
UMBRAL_DEFAULT = 0.15


def cargar_actas_fondo_general():
    actas = {}  # acta_id -> {titulo, resultado, afirm, neg, abst}
    with open(VOTOS_PATH, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["categoria_votacion"] != CATEGORIA_UNIVERSO:
                continue
            acta_id = fila["acta_id"]
            if acta_id not in actas:
                actas[acta_id] = {
                    "titulo": fila["titulo"],
                    "resultado": fila["resultado"],
                    "afirmativos": 0,
                    "negativos": 0,
                    "abstenciones": 0,
                }
            voto = fila["voto"]
            if voto == "AFIRMATIVO":
                actas[acta_id]["afirmativos"] += 1
            elif voto == "NEGATIVO":
                actas[acta_id]["negativos"] += 1
            elif voto == "ABSTENCION":
                actas[acta_id]["abstenciones"] += 1
            # AUSENTE, PRESIDENTE u otro: no cuentan como posición válida
    return actas


def calcular_division(actas):
    filas = []
    for acta_id, d in actas.items():
        total = d["afirmativos"] + d["negativos"] + d["abstenciones"]
        mayoria = max(d["afirmativos"], d["negativos"], d["abstenciones"])
        minoria = total - mayoria
        division = minoria / total if total > 0 else None
        filas.append({"acta_id": acta_id, **d, "total_posiciones": total, "division": division})

    filas.sort(key=lambda f: (f["division"] is None, -(f["division"] or 0)))
    return filas


def main():
    umbral = float(sys.argv[1]) if len(sys.argv) > 1 else UMBRAL_DEFAULT

    actas = cargar_actas_fondo_general()
    filas = calcular_division(actas)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "acta_id", "titulo", "resultado", "afirmativos", "negativos",
            "abstenciones", "total_posiciones", "division",
        ])
        writer.writeheader()
        writer.writerows(filas)

    print(f"Actas FONDO_GENERAL: {len(filas)}\n")
    print(f"{'acta':>6} {'div.':>6} {'A':>4} {'N':>4} {'Ab':>3} {'result.':<11} titulo")
    for f in filas:
        div_str = f"{f['division']:.3f}" if f["division"] is not None else "  N/A"
        print(f"{f['acta_id']:>6} {div_str:>6} {f['afirmativos']:>4} {f['negativos']:>4} "
              f"{f['abstenciones']:>3} {f['resultado']:<11} {f['titulo'][:90]}")

    con_division = [f for f in filas if f["division"] is not None]
    disputadas = [f for f in con_division if f["division"] > umbral]
    consenso = [f for f in con_division if f["division"] <= umbral]

    print(f"\n=== corte con umbral división > {umbral} (minoría > {umbral*100:.0f}% del total) ===")
    print(f"disputadas: {len(disputadas)}")
    print(f"consenso: {len(consenso)}")

    print(f"\nGuardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
