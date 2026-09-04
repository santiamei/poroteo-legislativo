#!/usr/bin/env python3
"""Clustering jerárquico sobre la matriz de acuerdo restringida a las 13
actas FONDO_GENERAL disputadas (división > 0.15). Esta es la matriz "de
conflicto": la que separa de verdad, a diferencia de la matriz sobre las
42 (dominada por el consenso).

Pasos:
  1. Matriz de acuerdo + n, solo sobre las 13 actas disputadas (misma
     definición que construir_matriz_acuerdo.py).
  2. Excluye diputados con cobertura < 7/13 (menos de la mitad de las
     actas disputadas) — no se fuerzan al clustering, se listan aparte.
  3. distancia = 1 - acuerdo. Linkage jerárquico (average, sobre 1-acuerdo).
  4. Dendrograma completo -> PNG en data/processed/.
  5. Explora 3 cortes de distancia elegidos por los saltos más grandes en
     las alturas de fusión del linkage (no fijados a mano).
  6. Por cada corte: composición de cada cluster (diputado, bloque
     predominante en las 13), pureza de bloque, y un foco específico en
     Provincias Unidas y Unión por la Patria.

No interpreta políticamente — solo reporta la estructura.

Uso:
    python ingesta/clustering_conflicto.py
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import dendrogram, fcluster, linkage
from scipy.spatial.distance import squareform

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

VOTOS_PATH = Path(__file__).parent.parent / "data" / "processed" / "votos_consolidado.csv"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"
DENDROGRAMA_PATH = OUTPUT_DIR / "dendrograma_conflicto_13actas.png"
CLUSTERS_PATH = OUTPUT_DIR / "clusters_conflicto_13actas.csv"

ACTAS_DISPUTADAS = {
    "5822", "5956", "5853", "5838", "5902", "5931", "5974",
    "5971", "5919", "5955", "5847", "5981", "5849",
}
VOTOS_VALIDOS = {"AFIRMATIVO", "NEGATIVO", "ABSTENCION"}
COBERTURA_MINIMA = 7  # de 13 — más de la mitad


def cargar_datos():
    votos_por_diputado = defaultdict(dict)      # id -> {acta_id: voto}
    bloques_por_diputado = defaultdict(Counter)  # id -> Counter(bloque -> apariciones)
    nombres = {}

    with open(VOTOS_PATH, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["acta_id"] not in ACTAS_DISPUTADAS:
                continue
            id_ = fila["id_diputado"]
            nombres[id_] = fila["nombre_canonico"]
            if fila["voto"] in VOTOS_VALIDOS:
                votos_por_diputado[id_][fila["acta_id"]] = fila["voto"]
                bloques_por_diputado[id_][fila["bloque_canonico_en_esa_fecha"]] += 1

    return votos_por_diputado, bloques_por_diputado, nombres


def separar_por_cobertura(votos_por_diputado):
    incluidos, excluidos = [], []
    for id_, votos in votos_por_diputado.items():
        (incluidos if len(votos) >= COBERTURA_MINIMA else excluidos).append(id_)
    return sorted(incluidos), sorted(excluidos)


def construir_matriz_distancia(ids, votos_por_diputado):
    n_ids = len(ids)
    acuerdo = np.full((n_ids, n_ids), np.nan)
    n_compartidas = np.zeros((n_ids, n_ids), dtype=int)

    for i, id_i in enumerate(ids):
        votos_i = votos_por_diputado[id_i]
        acuerdo[i, i] = 1.0
        for j in range(i + 1, n_ids):
            id_j = ids[j]
            votos_j = votos_por_diputado[id_j]
            compartidas = votos_i.keys() & votos_j.keys()
            n = len(compartidas)
            n_compartidas[i, j] = n_compartidas[j, i] = n
            if n > 0:
                coincidencias = sum(1 for a in compartidas if votos_i[a] == votos_j[a])
                tasa = coincidencias / n
                acuerdo[i, j] = acuerdo[j, i] = tasa

    return acuerdo, n_compartidas


def main():
    votos_por_diputado, bloques_por_diputado, nombres = cargar_datos()
    incluidos, excluidos = separar_por_cobertura(votos_por_diputado)

    print(f"Diputados con voto válido en alguna de las 13 actas: {len(votos_por_diputado)}")
    print(f"Incluidos en el clustering (cobertura >= {COBERTURA_MINIMA}/13): {len(incluidos)}")
    print(f"Excluidos por baja cobertura (< {COBERTURA_MINIMA}/13): {len(excluidos)}")
    for id_ in excluidos:
        print(f"  - {id_} ({nombres[id_]}): {len(votos_por_diputado[id_])}/13")

    acuerdo, n_compartidas = construir_matriz_distancia(incluidos, votos_por_diputado)

    sin_dato = np.isnan(acuerdo)
    np.fill_diagonal(sin_dato, False)
    if sin_dato.any():
        pares_sin_dato = int(sin_dato.sum() / 2)
        print(f"\n!! {pares_sin_dato} pares SIN ninguna votación compartida en las 13 actas "
              "pese a superar la cobertura mínima individual. Se imputan con acuerdo=0.5 "
              "(distancia neutra) SOLO para que el algoritmo pueda correr — no son datos "
              "reales, listados abajo para que no se interpreten como señal.")
        idx_pares = np.argwhere(sin_dato)
        for i, j in idx_pares:
            if i < j:
                print(f"     {incluidos[i]} <-> {incluidos[j]}")
        acuerdo[sin_dato] = 0.5

    distancia = 1 - acuerdo
    np.fill_diagonal(distancia, 0.0)
    distancia = (distancia + distancia.T) / 2  # limpiar asimetría de punto flotante
    condensada = squareform(distancia, checks=False)

    Z = linkage(condensada, method="average")

    # ---- bloque predominante por diputado (modal, sobre las 13) ----
    bloque_predominante = {
        id_: bloques_por_diputado[id_].most_common(1)[0][0] for id_ in incluidos
    }

    # ---- dendrograma ----
    labels = [nombres[id_].split(",")[0].title() for id_ in incluidos]
    fig_h = max(10, 0.16 * len(incluidos))
    fig, ax = plt.subplots(figsize=(14, fig_h))
    dendrogram(Z, labels=labels, orientation="left", ax=ax, leaf_font_size=6)
    ax.set_title(
        f"Clustering jerárquico (average, 1-acuerdo) — {len(incluidos)} diputados, "
        f"13 actas disputadas FONDO_GENERAL"
    )
    ax.set_xlabel("distancia (1 - tasa de acuerdo)")
    plt.tight_layout()
    plt.savefig(DENDROGRAMA_PATH, dpi=150)
    plt.close(fig)
    print(f"\nDendrograma guardado en: {DENDROGRAMA_PATH}")

    # ---- gaps en las alturas de fusión, para proponer cortes ----
    alturas = Z[:, 2]
    gaps = np.diff(alturas)
    top_gaps_idx = np.argsort(gaps)[::-1][:6]
    print("\n=== mayores saltos en la altura de fusión (candidatos a corte) ===")
    propuestas = []
    for idx in sorted(top_gaps_idx):
        t = (alturas[idx] + alturas[idx + 1]) / 2
        k = len(set(fcluster(Z, t, criterion="distance")))
        propuestas.append((t, k))
        print(f"  entre altura {alturas[idx]:.4f} y {alturas[idx+1]:.4f} "
              f"(salto {gaps[idx]:.4f}) -> corte en {t:.4f} da {k} clusters")

    # de las propuestas, nos quedamos con 3: la que da menos clusters,
    # una intermedia, y la que da más (sin repetir k)
    propuestas_unicas = sorted(set(propuestas), key=lambda x: x[1])
    if len(propuestas_unicas) >= 3:
        cortes_elegidos = [
            propuestas_unicas[0],
            propuestas_unicas[len(propuestas_unicas) // 2],
            propuestas_unicas[-1],
        ]
    else:
        cortes_elegidos = propuestas_unicas

    filas_csv = []
    for t, k_esperado in cortes_elegidos:
        labels_cluster = fcluster(Z, t, criterion="distance")
        k = len(set(labels_cluster))
        print(f"\n\n########## CORTE a distancia {t:.4f} -> {k} clusters ##########")

        clusters = defaultdict(list)
        for id_, c in zip(incluidos, labels_cluster):
            clusters[c].append(id_)

        for c in sorted(clusters, key=lambda c: -len(clusters[c])):
            miembros = clusters[c]
            bloques_en_cluster = Counter(bloque_predominante[id_] for id_ in miembros)
            bloque_mayoritario, n_mayoritario = bloques_en_cluster.most_common(1)[0]
            pureza = n_mayoritario / len(miembros)
            print(f"\n--- cluster {c} ({len(miembros)} diputados) "
                  f"| bloque mayoritario: {bloque_mayoritario} ({pureza*100:.0f}% del cluster) ---")
            if len(bloques_en_cluster) > 1:
                otros = {b: n for b, n in bloques_en_cluster.items() if b != bloque_mayoritario}
                print(f"    otros bloques presentes: {otros}")
            for id_ in sorted(miembros, key=lambda i: nombres[i]):
                marca = "" if bloque_predominante[id_] == bloque_mayoritario else "  <-- distinto del bloque mayoritario del cluster"
                print(f"    {nombres[id_]:<40} [{bloque_predominante[id_]}]{marca}")
                filas_csv.append({
                    "corte_distancia": f"{t:.4f}",
                    "k_clusters": k,
                    "cluster": c,
                    "id_diputado": id_,
                    "nombre_canonico": nombres[id_],
                    "bloque_predominante_13": bloque_predominante[id_],
                })

        # foco especial: Provincias Unidas y UxP
        for bloque_foco in ("Provincias Unidas", "Unión por la Patria"):
            ids_bloque = [id_ for id_ in incluidos if bloque_predominante[id_] == bloque_foco]
            clusters_de_ids = Counter(
                labels_cluster[incluidos.index(id_)] for id_ in ids_bloque
            )
            if len(clusters_de_ids) > 1:
                print(f"\n    >> {bloque_foco}: sus {len(ids_bloque)} diputados se reparten en "
                      f"{len(clusters_de_ids)} clusters distintos en este corte: {dict(clusters_de_ids)}")
            else:
                print(f"\n    >> {bloque_foco}: sus {len(ids_bloque)} diputados quedan juntos en un solo cluster en este corte.")

    with open(CLUSTERS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "corte_distancia", "k_clusters", "cluster", "id_diputado",
            "nombre_canonico", "bloque_predominante_13",
        ])
        writer.writeheader()
        writer.writerows(filas_csv)
    print(f"\n\nClusters (todos los cortes explorados) guardados en: {CLUSTERS_PATH}")


if __name__ == "__main__":
    main()
