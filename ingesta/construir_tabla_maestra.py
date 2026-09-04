#!/usr/bin/env python3
"""Construye la tabla maestra de diputados a partir de data/raw/datacp/,
resolviendo las inconsistencias de identidad encontradas en el
reconocimiento (legislador_slug ausente en algunas filas, banca vacante,
mismo diputado con nombre truncado antes de tener slug).

Reglas de resolución aplicadas (confirmadas manualmente, no inferidas
automáticamente — ver docstrings de cada función):

  1. BANCA VACANTE (Córdoba, 17-18/12/2025): las filas con nombre "," son
     un asiento vacante (Schiaretti no asumió el 10/12 por salud), no una
     persona. Se EXCLUYEN de la tabla maestra y de cualquier conteo de
     personas/votos.
  2. MERGE Herrera: "HERRERA, OSCAR" (sin slug) y "HERRERA AHUAD, OSCAR A."
     (slug herrera-ahuad-oscar-a) son la misma persona — se unifican bajo
     ese slug.
  3. Pitrola/Giordano y Ravier/Matzkin son personas DISTINTAS (confirmado),
     no se mergean aunque los conteos de apariciones sean complementarios.
  4. Diputados reales que Data CP nunca les asignó slug (Pitrola, Ravier)
     reciben un id local generado por este script (NO es un slug de Data
     CP) para poder tener una fila estable en la tabla maestra. Queda
     marcado explícitamente en el campo "slug_real".

Esto sigue siendo reconocimiento/resolución de identidad — no es todavía
el esquema normalizado de votaciones.

Uso:
    python ingesta/construir_tabla_maestra.py
"""

import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "datacp"
OUTPUT_PATH = Path(__file__).parent / "tabla_maestra_diputados.json"

NOMBRE_BANCA_VACANTE = ","

# HERRERA, OSCAR (sin slug) es la misma persona que herrera-ahuad-oscar-a,
# solo que Data CP le truncaba el apellido antes de vincularlo a un slug.
MERGES_CONFIRMADOS = {
    "HERRERA, OSCAR": "herrera-ahuad-oscar-a",
}


def slugify_local(nombre):
    """Genera un id local con la misma pinta que los slugs de Data CP
    (apellido-nombre1-nombre2, sin acentos) para diputados que Data CP
    nunca vinculó a un slug real. NO es un slug de Data CP."""
    apellido, _, resto = nombre.partition(",")
    tokens = [apellido.strip()] + resto.split()
    texto = "-".join(tokens).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9\-]", "", texto)
    return texto


def resolver_identidad(persona):
    """Devuelve (id_resuelto, es_slug_real_de_datacp) para una fila del
    roster, o None si la fila es una banca vacante a excluir."""
    nombre = persona["nombre"]
    if nombre == NOMBRE_BANCA_VACANTE:
        return None

    if nombre in MERGES_CONFIRMADOS:
        return MERGES_CONFIRMADOS[nombre], True  # el slug destino sí es real

    if persona["legislador_slug"] is not None:
        return persona["legislador_slug"], True

    return slugify_local(nombre), False


def cargar_actas():
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(RAW_DIR.glob("acta_diputados_*.json"))
    ]


def construir(actas):
    personas = defaultdict(lambda: {
        "nombres_vistos": set(),
        "bloques_vistos": set(),
        "provincias_vistas": set(),
        "fechas": [],  # [(fecha, actaId)]
        "slug_real": None,
    })
    banca_vacante = []

    for acta in actas:
        meta = acta["acta"]
        for persona in acta["roster"]:
            resuelto = resolver_identidad(persona)
            if resuelto is None:
                banca_vacante.append({
                    "actaId": meta["acta_id"],
                    "fecha": meta["fecha"],
                    "provincia": persona["provincia"],
                })
                continue

            id_resuelto, es_slug_real = resuelto
            registro = personas[id_resuelto]
            registro["nombres_vistos"].add(persona["nombre"])
            registro["bloques_vistos"].add(persona["bloque"])
            registro["provincias_vistas"].add(persona["provincia"])
            registro["fechas"].append((meta["fecha"], meta["acta_id"]))
            registro["slug_real"] = id_resuelto if es_slug_real else None

    tabla = []
    for id_resuelto, datos in personas.items():
        fechas_dt = [datetime.strptime(f, "%d/%m/%Y") for f, _ in datos["fechas"]]
        # nombre canónico: el más largo (el más completo suele ser el más reciente)
        nombre_canonico = max(datos["nombres_vistos"], key=len)
        tabla.append({
            "id": id_resuelto,
            "slug_real_datacp": datos["slug_real"],
            "nombre_canonico": nombre_canonico,
            "nombres_variantes": sorted(datos["nombres_vistos"]),
            "provincia": sorted(datos["provincias_vistas"]),
            "bloques": sorted(datos["bloques_vistos"]),
            "apariciones": len(datos["fechas"]),
            "primera_fecha": min(fechas_dt).strftime("%d/%m/%Y"),
            "ultima_fecha": max(fechas_dt).strftime("%d/%m/%Y"),
        })

    tabla.sort(key=lambda p: p["nombre_canonico"])
    return tabla, banca_vacante


def main():
    actas = cargar_actas()
    tabla, banca_vacante = construir(actas)

    OUTPUT_PATH.write_text(json.dumps(tabla, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Actas procesadas: {len(actas)}")
    print(f"\nFilas marcadas como BANCA VACANTE y excluidas: {len(banca_vacante)}")
    for fila in banca_vacante:
        print(f"  acta {fila['actaId']} ({fila['fecha']}) — provincia {fila['provincia']}")

    schiaretti = next(p for p in tabla if p["id"] == "schiaretti-juan")
    print(f"\nSCHIARETTI (schiaretti-juan) — titular real desde: {schiaretti['primera_fecha']}")
    print(f"  apariciones: {schiaretti['apariciones']}/{len(actas)}")
    print(f"  nombres vistos: {schiaretti['nombres_variantes']}")

    herrera = next(p for p in tabla if p["id"] == "herrera-ahuad-oscar-a")
    print(f"\nHERRERA (herrera-ahuad-oscar-a) tras el merge:")
    print(f"  apariciones: {herrera['apariciones']}/{len(actas)}")
    print(f"  nombres vistos: {herrera['nombres_variantes']}")

    sin_slug_real = [p for p in tabla if p["slug_real_datacp"] is None]
    print(f"\nPersonas SIN slug real de Data CP (id generado localmente): {len(sin_slug_real)}")
    for p in sin_slug_real:
        print(f"  - {p['id']} ({p['nombre_canonico']}) | apariciones: {p['apariciones']}/{len(actas)} "
              f"| {p['primera_fecha']} -> {p['ultima_fecha']}")

    print(f"\nTOTAL personas físicas en la tabla maestra: {len(tabla)}")
    print(f"Guardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
