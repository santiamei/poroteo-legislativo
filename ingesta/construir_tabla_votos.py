#!/usr/bin/env python3
"""Construye la tabla de votos consolidada (formato largo: una fila por
acta x diputado), uniendo las tres capas ya resueltas:

  1. Votos crudos de las 124 actas (data/raw/datacp/).
  2. Identidad resuelta (ingesta/tabla_maestra_diputados.json — banca
     vacante excluida, Herrera mergeado).
  3. Mapeo temporal de bloques (ingesta/mapeo_bloques_diputados.json —
     bloque canónico que cada diputado tenía en la fecha de cada acta).

Además clasifica cada acta con clasificacion.clasificador (categoria +
etiqueta), una sola vez por acta, y la propaga a todas sus filas — salvo
que exista un override manual en clasificacion/overrides.yaml para esa
acta_id, en cuyo caso el override gana. El override es una corrección
puntual por acta, separada del clasificador de texto (ver overrides.yaml).

Es el paso final de la normalización (0.3): esto es la tabla consolidada,
NO arma todavía la matriz de acuerdo entre diputados/bloques.

Uso:
    python ingesta/construir_tabla_votos.py
"""

import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))  # para importar clasificacion/

from clasificacion.clasificador import clasificar_votacion
from construir_tabla_maestra import cargar_actas, resolver_identidad

MAPEO_BLOQUES_PATH = Path(__file__).parent / "mapeo_bloques_diputados.json"
TABLA_MAESTRA_PATH = Path(__file__).parent / "tabla_maestra_diputados.json"
OVERRIDES_PATH = Path(__file__).parent.parent / "clasificacion" / "overrides.yaml"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"
OUTPUT_PATH = OUTPUT_DIR / "votos_consolidado.csv"

CAMPOS = [
    "acta_id", "fecha", "id_diputado", "nombre_canonico",
    "bloque_canonico_en_esa_fecha", "provincia", "voto",
    "titulo", "resultado", "url",
    "categoria_votacion", "etiqueta_votacion",
]


def cargar_referencias():
    mapeo_bloques = json.loads(MAPEO_BLOQUES_PATH.read_text(encoding="utf-8"))
    tabla_maestra = json.loads(TABLA_MAESTRA_PATH.read_text(encoding="utf-8"))
    nombre_canonico_por_id = {p["id"]: p["nombre_canonico"] for p in tabla_maestra}
    overrides = yaml.safe_load(OVERRIDES_PATH.read_text(encoding="utf-8")) or {}
    return mapeo_bloques, nombre_canonico_por_id, overrides


def clasificar_con_overrides(titulo, acta_id, overrides):
    """Clasificación final de una acta: el override manual gana si existe
    para ese acta_id, si no la del clasificador automático. Devuelve
    (categoria, etiqueta, fue_override)."""
    automatica = clasificar_votacion(titulo)
    override = overrides.get(acta_id)
    if override is None:
        return automatica.categoria, automatica.etiqueta, False
    return override["categoria"], override.get("etiqueta"), True


def bloque_en_fecha(mapeo_bloques, id_diputado, fecha_str):
    fecha = datetime.strptime(fecha_str, "%d/%m/%Y")
    for periodo in mapeo_bloques[id_diputado]:
        desde = datetime.strptime(periodo["desde_fecha"], "%d/%m/%Y")
        hasta = datetime.strptime(periodo["hasta_fecha"], "%d/%m/%Y")
        if desde <= fecha <= hasta:
            return periodo["bloque_canonico"]
    raise ValueError(f"Sin período de bloque para {id_diputado} en fecha {fecha_str}")


def construir_tabla(actas, mapeo_bloques, nombre_canonico_por_id, overrides):
    filas = []
    banca_vacante_excluidas = 0
    actas_con_override = []

    for acta in actas:
        meta = acta["acta"]
        categoria, etiqueta, fue_override = clasificar_con_overrides(
            meta["titulo"], meta["acta_id"], overrides
        )
        if fue_override:
            actas_con_override.append(meta["acta_id"])

        for persona in acta["roster"]:
            resuelto = resolver_identidad(persona)
            if resuelto is None:
                banca_vacante_excluidas += 1
                continue

            id_diputado, _ = resuelto
            filas.append({
                "acta_id": meta["acta_id"],
                "fecha": meta["fecha"],
                "id_diputado": id_diputado,
                "nombre_canonico": nombre_canonico_por_id[id_diputado],
                "bloque_canonico_en_esa_fecha": bloque_en_fecha(mapeo_bloques, id_diputado, meta["fecha"]),
                "provincia": persona["provincia"],
                "voto": persona["voto"],
                "titulo": meta["titulo"],
                "resultado": meta["resultado"],
                "url": meta["url"],
                "categoria_votacion": categoria,
                "etiqueta_votacion": etiqueta,
            })

    return filas, banca_vacante_excluidas, actas_con_override


def main():
    actas = cargar_actas()
    mapeo_bloques, nombre_canonico_por_id, overrides = cargar_referencias()
    filas, banca_vacante_excluidas, actas_con_override = construir_tabla(
        actas, mapeo_bloques, nombre_canonico_por_id, overrides
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS)
        writer.writeheader()
        writer.writerows(filas)

    # ---- reporte de control de calidad ----
    actas_ids = {f["acta_id"] for f in filas}
    print(f"Total de filas: {len(filas)}")
    print(f"Total de actas: {len(actas_ids)} (de {len(actas)} cargadas)")
    print(f"Filas de banca vacante excluidas: {banca_vacante_excluidas}")

    print(f"\n=== overrides manuales aplicados: {len(actas_con_override)} ===")
    for acta_id in actas_con_override:
        override = overrides[acta_id]
        print(f"  acta {acta_id} -> {override['categoria']} | motivo: {override['motivo']}")

    categoria_por_acta = {}
    etiqueta_por_acta = {}
    for f in filas:
        categoria_por_acta[f["acta_id"]] = f["categoria_votacion"]
        etiqueta_por_acta[f["acta_id"]] = f["etiqueta_votacion"]

    print("\n=== actas por categoría del clasificador ===")
    conteo_categoria = Counter(categoria_por_acta.values())
    for categoria, n in conteo_categoria.most_common():
        print(f"  {categoria}: {n}")

    conteo_etiqueta = Counter(e for e in etiqueta_por_acta.values() if e)
    print("\n=== actas por etiqueta (dentro de PROCEDIMIENTO) ===")
    for etiqueta, n in conteo_etiqueta.most_common():
        print(f"  {etiqueta}: {n}")

    print("\n=== actas en REVISAR (para revisar a mano) ===")
    for acta in actas:
        acta_id = acta["acta"]["acta_id"]
        if categoria_por_acta.get(acta_id) == "REVISAR":
            print(f"  acta {acta_id} ({acta['acta']['fecha']}): {acta['acta']['titulo']}")

    print("\n=== distribución de votos por categoría ===")
    votos_por_categoria = Counter((f["categoria_votacion"], f["voto"]) for f in filas)
    for categoria in sorted(conteo_categoria):
        print(f"  {categoria}:")
        subtotal = {voto: n for (cat, voto), n in votos_por_categoria.items() if cat == categoria}
        for voto, n in sorted(subtotal.items(), key=lambda kv: -kv[1]):
            print(f"    {voto}: {n}")

    print(f"\nGuardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
