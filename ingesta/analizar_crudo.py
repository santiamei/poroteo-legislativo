#!/usr/bin/env python3
"""Reconocimiento de solo lectura sobre data/raw/datacp/ (las 124 actas ya
descargadas), para planificar la normalización. No toca red, no escribe
nada, no transforma los datos crudos — solo lee y reporta.

Uso:
    python ingesta/analizar_crudo.py
"""

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "datacp"


def cargar_actas():
    actas = []
    for path in sorted(RAW_DIR.glob("acta_diputados_*.json")):
        actas.append(json.loads(path.read_text(encoding="utf-8")))
    return actas


def main():
    actas = cargar_actas()
    print(f"Actas cargadas: {len(actas)}\n")

    # ------------------------------------------------------------------
    # 1-4: identidad de diputados
    # ------------------------------------------------------------------
    slug_a_nombres = defaultdict(set)
    nombre_a_slugs = defaultdict(set)
    slug_a_apariciones = Counter()  # en cuántas actas aparece ese slug
    slug_a_fechas = defaultdict(list)  # slug -> [(fecha, actaId), ...]
    todos_los_nombres = set()
    ejemplos_nombre = []

    for acta in actas:
        meta = acta["acta"]
        vistos_en_esta_acta = set()
        for persona in acta["roster"]:
            slug = persona["legislador_slug"]
            nombre = persona["nombre"]
            slug_a_nombres[slug].add(nombre)
            nombre_a_slugs[nombre].add(slug)
            todos_los_nombres.add(nombre)
            if len(ejemplos_nombre) < 30:
                ejemplos_nombre.append(nombre)
            if slug not in vistos_en_esta_acta:
                slug_a_apariciones[slug] += 1
                slug_a_fechas[slug].append((meta["fecha"], meta["acta_id"]))
                vistos_en_esta_acta.add(slug)

    print("=== 1-2. Identidad: slug vs. nombre ===")
    print(f"diputados únicos por legislador_slug: {len(slug_a_nombres)}")
    print(f"diputados únicos por string de nombre: {len(todos_los_nombres)}")

    slugs_con_multiples_nombres = {s: n for s, n in slug_a_nombres.items() if len(n) > 1}
    nombres_con_multiples_slugs = {n: s for n, s in nombre_a_slugs.items() if len(s) > 1}

    print(f"\nslugs asociados a más de un nombre distinto: {len(slugs_con_multiples_nombres)}")
    for slug, nombres in slugs_con_multiples_nombres.items():
        print(f"  - {slug}: {sorted(nombres)}")

    print(f"\nnombres asociados a más de un slug distinto: {len(nombres_con_multiples_slugs)}")
    for nombre, slugs in nombres_con_multiples_slugs.items():
        print(f"  - {nombre!r}: {sorted(slugs)}")

    print("\n=== 3. Cobertura temporal por diputado (sobre 124 actas) ===")
    total_actas = len(actas)
    en_todas = [s for s, c in slug_a_apariciones.items() if c == total_actas]
    parciales = [(s, c) for s, c in slug_a_apariciones.items() if c < total_actas]
    print(f"diputados distintos en total: {len(slug_a_apariciones)}")
    print(f"aparecen en las {total_actas} actas: {len(en_todas)}")
    print(f"aparecen solo en algunas ({len(parciales)} diputados):")
    for slug, c in sorted(parciales, key=lambda x: x[1]):
        fechas = slug_a_fechas[slug]
        primera = min(fechas, key=lambda fa: datetime.strptime(fa[0], "%d/%m/%Y"))
        ultima = max(fechas, key=lambda fa: datetime.strptime(fa[0], "%d/%m/%Y"))
        nombre = next(iter(slug_a_nombres[slug]))
        print(f"  - {slug} ({nombre}): {c}/{total_actas} actas | "
              f"primera: {primera[0]} (acta {primera[1]}) | última: {ultima[0]} (acta {ultima[1]})")

    print("\n=== 4. Ejemplos de formato de nombre (10) ===")
    for n in ejemplos_nombre[:10]:
        print(f"  {n!r}")

    # ------------------------------------------------------------------
    # 5-6: bloques
    # ------------------------------------------------------------------
    bloques_unicos = set()
    slug_a_bloques = defaultdict(set)
    slug_a_bloque_por_fecha = defaultdict(list)  # slug -> [(fecha, actaId, bloque)]

    for acta in actas:
        meta = acta["acta"]
        for persona in acta["roster"]:
            bloques_unicos.add(persona["bloque"])
            slug = persona["legislador_slug"]
            slug_a_bloques[slug].add(persona["bloque"])
            slug_a_bloque_por_fecha[slug].append((meta["fecha"], meta["acta_id"], persona["bloque"]))

    print(f"\n=== 5. Bloques únicos ({len(bloques_unicos)}) ===")
    for b in sorted(bloques_unicos):
        print(f"  - {b!r}")

    print("\n=== 6. Diputados con más de un bloque a lo largo de la ventana ===")
    con_pase = {s: b for s, b in slug_a_bloques.items() if len(b) > 1}
    print(f"total: {len(con_pase)}")
    for slug, bloques in con_pase.items():
        nombre = next(iter(slug_a_nombres[slug]))
        print(f"\n  - {slug} ({nombre}) -> bloques: {sorted(bloques)}")
        eventos = sorted(
            set(slug_a_bloque_por_fecha[slug]),
            key=lambda fab: datetime.strptime(fab[0], "%d/%m/%Y"),
        )
        bloque_anterior = None
        for fecha, acta_id, bloque in eventos:
            if bloque != bloque_anterior:
                print(f"      {fecha} (acta {acta_id}): {bloque}")
                bloque_anterior = bloque

    # ------------------------------------------------------------------
    # 7-8: votos y tamaño de roster
    # ------------------------------------------------------------------
    votos_unicos = Counter()
    for acta in actas:
        for persona in acta["roster"]:
            votos_unicos[persona["voto"]] += 1

    print(f"\n=== 7. Valores únicos del campo voto ===")
    for voto, n in votos_unicos.most_common():
        print(f"  {voto}: {n}")

    print(f"\n=== 8. Tamaño del roster por acta ===")
    tamanos = Counter()
    distintos = []
    for acta in actas:
        meta = acta["acta"]
        n = len(acta["roster"])
        tamanos[n] += 1
        if n != 257:
            distintos.append((meta["acta_id"], meta["fecha"], n))

    for tam, cant in sorted(tamanos.items()):
        print(f"  roster de {tam} personas: {cant} actas")
    if distintos:
        print("\n  actas con roster != 257:")
        for acta_id, fecha, n in distintos:
            print(f"    - acta {acta_id} ({fecha}): {n} personas")
    else:
        print("  todas las actas tienen roster de 257.")


if __name__ == "__main__":
    main()
