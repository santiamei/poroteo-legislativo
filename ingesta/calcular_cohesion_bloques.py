#!/usr/bin/env python3
"""Calcula la cohesión de bloque (índice de Rice) sobre las votaciones de
fondo (paso siguiente a la matriz de acuerdo; universo configurable, por
defecto FONDO_GENERAL). Trabaja sobre data/processed/votos_consolidado.csv.

Índice de Rice por (acta, bloque):
    Rice = |afirmativos - negativos| / (afirmativos + negativos)
dentro del bloque CANÓNICO que cada diputado tenía en la fecha de esa
acta (bloque_canonico_en_esa_fecha, ya resuelto en la tabla consolidada).
Cuenta solo AFIRMATIVO/NEGATIVO — abstención, ausente, presidente y
cualquier otro valor quedan fuera del cálculo de Rice.

Un bloque solo entra en el promedio de una acta si tuvo al menos
UMBRAL_MIEMBROS (2) diputados con AFIRMATIVO o NEGATIVO en esa acta —
con 0 o 1 no hay cohesión que medir.

La tasa de abstención se reporta aparte (no entra en el Rice clásico):
abstenciones del bloque / (afirmativos + negativos + abstenciones del
bloque), sobre TODO el universo, sin el umbral de 2 miembros.

"Diputados del bloque" cuenta personas distintas que aparecieron bajo ese
bloque canónico en el universo, sin importar qué votaron (incluye
ausentes) — es tamaño de bloque, no participación.

No calcula subgrupos — eso es el paso siguiente.

Uso:
    python ingesta/calcular_cohesion_bloques.py [CATEGORIA[,CATEGORIA...]]
    python ingesta/calcular_cohesion_bloques.py FONDO_GENERAL   # default
"""

import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

VOTOS_PATH = Path(__file__).parent.parent / "data" / "processed" / "votos_consolidado.csv"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"

CATEGORIAS_UNIVERSO_DEFAULT = ["FONDO_GENERAL"]
UMBRAL_MIEMBROS = 2


def cargar_filas(categorias_universo):
    with open(VOTOS_PATH, encoding="utf-8") as f:
        return [
            fila for fila in csv.DictReader(f)
            if fila["categoria_votacion"] in categorias_universo
        ]


def calcular_cohesion(filas):
    votos_por_acta_bloque = defaultdict(list)  # (acta_id, bloque) -> [voto,...]
    diputados_por_bloque = defaultdict(set)

    for fila in filas:
        bloque = fila["bloque_canonico_en_esa_fecha"]
        votos_por_acta_bloque[(fila["acta_id"], bloque)].append(fila["voto"])
        diputados_por_bloque[bloque].add(fila["id_diputado"])

    rice_por_bloque = defaultdict(list)
    actas_incluidas_por_bloque = defaultdict(set)
    abstenciones_por_bloque = Counter()
    posiciones_con_abstencion_por_bloque = Counter()  # afirmativo+negativo+abstencion

    for (acta_id, bloque), votos in votos_por_acta_bloque.items():
        afirmativos = votos.count("AFIRMATIVO")
        negativos = votos.count("NEGATIVO")
        abstenciones = votos.count("ABSTENCION")

        abstenciones_por_bloque[bloque] += abstenciones
        posiciones_con_abstencion_por_bloque[bloque] += afirmativos + negativos + abstenciones

        n_rice = afirmativos + negativos
        if n_rice >= UMBRAL_MIEMBROS:
            rice = abs(afirmativos - negativos) / n_rice
            rice_por_bloque[bloque].append(rice)
            actas_incluidas_por_bloque[bloque].add(acta_id)

    tabla = []
    for bloque, diputados in diputados_por_bloque.items():
        rices = rice_por_bloque.get(bloque, [])
        total_posiciones = posiciones_con_abstencion_por_bloque[bloque]
        tabla.append({
            "bloque": bloque,
            "cohesion_rice_promedio": statistics.mean(rices) if rices else None,
            "diputados_del_bloque": len(diputados),
            "actas_incluidas_en_cohesion": len(actas_incluidas_por_bloque[bloque]),
            "tasa_abstencion": (
                abstenciones_por_bloque[bloque] / total_posiciones if total_posiciones else None
            ),
        })

    tabla.sort(key=lambda r: (r["cohesion_rice_promedio"] is None, -(r["cohesion_rice_promedio"] or 0)))
    return tabla


def main():
    categorias_universo = (
        sys.argv[1].split(",") if len(sys.argv) > 1 else CATEGORIAS_UNIVERSO_DEFAULT
    )
    filas = cargar_filas(categorias_universo)
    tabla = calcular_cohesion(filas)

    sufijo = "_".join(c.lower() for c in categorias_universo)
    output_path = OUTPUT_DIR / f"cohesion_bloques_{sufijo}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "bloque", "cohesion_rice_promedio", "diputados_del_bloque",
            "actas_incluidas_en_cohesion", "tasa_abstencion",
        ])
        writer.writeheader()
        writer.writerows(tabla)

    print(f"Universo: {categorias_universo}")
    print(f"Bloques: {len(tabla)}")
    print(f"\n{'bloque':<75} {'rice':>6} {'dip.':>5} {'actas':>6} {'absten.':>8}")
    for r in tabla:
        rice_str = f"{r['cohesion_rice_promedio']:.3f}" if r["cohesion_rice_promedio"] is not None else "  N/A"
        abst_str = f"{r['tasa_abstencion']*100:.1f}%" if r["tasa_abstencion"] is not None else "  N/A"
        print(f"{r['bloque']:<75} {rice_str:>6} {r['diputados_del_bloque']:>5} "
              f"{r['actas_incluidas_en_cohesion']:>6} {abst_str:>8}")

    print(f"\nGuardado en: {output_path}")


if __name__ == "__main__":
    main()
