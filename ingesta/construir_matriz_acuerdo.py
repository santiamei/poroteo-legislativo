#!/usr/bin/env python3
"""Construye la matriz de acuerdo legislador x legislador (paso 0.4).

Trabaja sobre data/processed/votos_consolidado.csv. El universo de
votaciones es configurable (CATEGORIAS_UNIVERSO / primer argumento de
línea de comandos) — por defecto, solo FONDO_GENERAL.

Definición de acuerdo entre dos diputados, sobre el universo elegido:
    - Se consideran solo las actas donde AMBOS tienen una posición
      "válida": AFIRMATIVO, NEGATIVO o ABSTENCION.
    - AUSENTE, PRESIDENTE (o cualquier otro valor que no sea una de las
      tres posiciones válidas) hacen que esa acta NO cuente para ese par,
      ni en el numerador ni en el denominador.
    - La banca vacante ya no aparece en votos_consolidado.csv (se excluyó
      en la etapa de identidad), así que no hace falta filtrarla acá.
    - Acuerdo = coincidencia exacta (AFIRMATIVO=AFIRMATIVO,
      NEGATIVO=NEGATIVO, o ABSTENCION=ABSTENCION cuentan; cualquier
      combinación distinta no).

No hay umbral de descarte: se calcula el acuerdo para todos los pares,
pero cada celda de la matriz de tasa tiene su celda espejo en la matriz
de n (cantidad de votaciones compartidas válidas) para poder filtrar
después por evidencia sin perder el dato.

Esto es solo la matriz — no calcula cohesión de bloque ni subgrupos.

Uso:
    python ingesta/construir_matriz_acuerdo.py [CATEGORIA[,CATEGORIA...]]
    python ingesta/construir_matriz_acuerdo.py FONDO_GENERAL              # default
    python ingesta/construir_matriz_acuerdo.py FONDO_GENERAL,FONDO_PARTICULAR
"""

import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

VOTOS_PATH = Path(__file__).parent.parent / "data" / "processed" / "votos_consolidado.csv"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"

VOTOS_VALIDOS = {"AFIRMATIVO", "NEGATIVO", "ABSTENCION"}
CATEGORIAS_UNIVERSO_DEFAULT = ["FONDO_GENERAL"]
UMBRAL_BAJA_EVIDENCIA = 10


def cargar_votos_validos_por_diputado(categorias_universo):
    """Devuelve (votos_por_diputado, actas_del_universo) donde
    votos_por_diputado[id] = {acta_id: voto} solo con posiciones válidas
    dentro del universo de categorías elegido."""
    votos_por_diputado = defaultdict(dict)
    actas_del_universo = set()

    with open(VOTOS_PATH, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["categoria_votacion"] not in categorias_universo:
                continue
            actas_del_universo.add(fila["acta_id"])
            if fila["voto"] not in VOTOS_VALIDOS:
                continue  # AUSENTE, PRESIDENTE, u otro valor no válido
            votos_por_diputado[fila["id_diputado"]][fila["acta_id"]] = fila["voto"]

    return votos_por_diputado, actas_del_universo


def construir_matrices(votos_por_diputado):
    ids = sorted(d for d, votos in votos_por_diputado.items() if votos)
    matriz_acuerdo = {i: {} for i in ids}
    matriz_n = {i: {} for i in ids}

    for idx_i, id_i in enumerate(ids):
        votos_i = votos_por_diputado[id_i]
        for id_j in ids[idx_i:]:
            if id_i == id_j:
                matriz_acuerdo[id_i][id_j] = 1.0
                matriz_n[id_i][id_j] = len(votos_i)
                continue

            votos_j = votos_por_diputado[id_j]
            actas_compartidas = votos_i.keys() & votos_j.keys()
            n = len(actas_compartidas)
            coincidencias = sum(1 for a in actas_compartidas if votos_i[a] == votos_j[a])
            tasa = (coincidencias / n) if n > 0 else None

            matriz_acuerdo[id_i][id_j] = tasa
            matriz_acuerdo[id_j][id_i] = tasa
            matriz_n[id_i][id_j] = n
            matriz_n[id_j][id_i] = n

    return ids, matriz_acuerdo, matriz_n


def guardar_matriz(ids, matriz, path, formato_celda):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([""] + ids)
        for id_fila in ids:
            fila = [formato_celda(matriz[id_fila][id_col]) for id_col in ids]
            writer.writerow([id_fila] + fila)


def main():
    categorias_universo = (
        sys.argv[1].split(",") if len(sys.argv) > 1 else CATEGORIAS_UNIVERSO_DEFAULT
    )
    sufijo = "_".join(c.lower() for c in categorias_universo)

    votos_por_diputado, actas_del_universo = cargar_votos_validos_por_diputado(categorias_universo)
    ids, matriz_acuerdo, matriz_n = construir_matrices(votos_por_diputado)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path_acuerdo = OUTPUT_DIR / f"matriz_acuerdo_{sufijo}.csv"
    path_n = OUTPUT_DIR / f"matriz_n_{sufijo}.csv"

    guardar_matriz(ids, matriz_acuerdo, path_acuerdo, lambda v: "" if v is None else f"{v:.4f}")
    guardar_matriz(ids, matriz_n, path_n, lambda v: str(v))

    # ---- reporte de control ----
    n_off_diagonal = [
        matriz_n[ids[i]][ids[j]]
        for i in range(len(ids))
        for j in range(i + 1, len(ids))
    ]
    bajo_umbral = sum(1 for n in n_off_diagonal if n < UMBRAL_BAJA_EVIDENCIA)

    print(f"Universo: {categorias_universo}")
    print(f"Actas del universo: {len(actas_del_universo)}")
    print(f"Diputados en la matriz: {len(ids)}")
    print(f"Dimensiones: {len(ids)} x {len(ids)}")
    print(f"Pares (i<j): {len(n_off_diagonal)}")
    print("\n=== rango de n (votaciones compartidas válidas por par) ===")
    print(f"  mínimo: {min(n_off_diagonal)}")
    print(f"  mediana: {statistics.median(n_off_diagonal)}")
    print(f"  máximo: {max(n_off_diagonal)}")
    print(f"\nPares con n < {UMBRAL_BAJA_EVIDENCIA}: {bajo_umbral} de {len(n_off_diagonal)} "
          f"({100 * bajo_umbral / len(n_off_diagonal):.1f}%)")

    print(f"\nGuardado:\n  {path_acuerdo}\n  {path_n}")


if __name__ == "__main__":
    main()
