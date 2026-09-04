#!/usr/bin/env python3
"""Normaliza los bloques políticos y arma el mapeo temporal diputado-bloque.

Reutiliza la resolución de identidad de construir_tabla_maestra.py (banca
vacante excluida, Herrera mergeado) y aplica el mapeo de
bloques_normalizacion.yaml para agrupar variantes de escritura del mismo
bloque bajo una etiqueta canónica.

Para cada diputado (id estable), arma una lista de períodos:
    [{bloque_canonico, desde_fecha, desde_actaId, hasta_fecha, hasta_actaId}, ...]
soportando más de un bloque en el tiempo. Reporta los pases reales (más
de un período) SEPARANDO los que son variante de escritura (ya
absorbidos por la normalización) de los que son cambios genuinos.

No arma todavía la tabla de votos consolidada ni la matriz.

Uso:
    python ingesta/construir_mapeo_bloques.py
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

from construir_tabla_maestra import cargar_actas, resolver_identidad

BLOQUES_YAML_PATH = Path(__file__).parent / "bloques_normalizacion.yaml"
OUTPUT_PATH = Path(__file__).parent / "mapeo_bloques_diputados.json"


def cargar_normalizacion():
    return yaml.safe_load(BLOQUES_YAML_PATH.read_text(encoding="utf-8"))


def normalizar_bloque(bloque_crudo, mapeo):
    if bloque_crudo not in mapeo:
        raise KeyError(
            f"Bloque crudo sin mapear en bloques_normalizacion.yaml: {bloque_crudo!r}"
        )
    return mapeo[bloque_crudo]


GENERICO_FIT = "Frente de Izquierda y de los Trabajadores - Unidad (sin desagregar)"


def backfill_generico_fit(eventos):
    """El bloque genérico del FIT es dato incompleto al arranque de la
    ventana, no un bloque real (decidido — ver bloques_normalizacion.yaml).
    Si la primera etapa de alguien es este bucket genérico y más adelante
    aparece una etiqueta específica, se asume que ya pertenecía a esa
    desde el día 1 (mismo criterio que el merge de identidad de Herrera)."""
    if not eventos or eventos[0][2] != GENERICO_FIT:
        return eventos
    especificas = [b for _, _, b in eventos if b != GENERICO_FIT]
    if not especificas:
        return eventos  # nadie tiene SOLO la etiqueta genérica en los datos actuales
    etiqueta_real = especificas[0]
    return [(f, a, etiqueta_real if b == GENERICO_FIT else b) for f, a, b in eventos]


def construir_mapeo(actas, mapeo_bloques):
    eventos_por_persona = defaultdict(list)  # id -> [(fecha, actaId, bloque_canonico)]

    for acta in actas:
        meta = acta["acta"]
        for persona in acta["roster"]:
            resuelto = resolver_identidad(persona)
            if resuelto is None:
                continue  # banca vacante
            id_resuelto, _ = resuelto
            bloque_canonico = normalizar_bloque(persona["bloque"], mapeo_bloques)
            eventos_por_persona[id_resuelto].append((meta["fecha"], meta["acta_id"], bloque_canonico))

    mapeo_temporal = {}
    for id_persona, eventos in eventos_por_persona.items():
        eventos = sorted(
            set(eventos), key=lambda e: (datetime.strptime(e[0], "%d/%m/%Y"), e[1])
        )
        eventos = backfill_generico_fit(eventos)
        periodos = []
        for fecha, acta_id, bloque in eventos:
            if periodos and periodos[-1]["bloque_canonico"] == bloque:
                periodos[-1]["hasta_fecha"] = fecha
                periodos[-1]["hasta_actaId"] = acta_id
            else:
                periodos.append({
                    "bloque_canonico": bloque,
                    "desde_fecha": fecha,
                    "desde_actaId": acta_id,
                    "hasta_fecha": fecha,
                    "hasta_actaId": acta_id,
                })
        mapeo_temporal[id_persona] = periodos

    return mapeo_temporal


def main():
    actas = cargar_actas()
    mapeo_bloques = cargar_normalizacion()
    mapeo_temporal = construir_mapeo(actas, mapeo_bloques)

    OUTPUT_PATH.write_text(
        json.dumps(mapeo_temporal, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    pases_reales = {
        id_persona: periodos
        for id_persona, periodos in mapeo_temporal.items()
        if len(periodos) > 1
    }

    print(f"Personas con mapeo de bloque: {len(mapeo_temporal)}")
    print(f"Personas con más de un bloque canónico en la ventana: {len(pases_reales)}")
    print("\n=== pases reales (después de normalizar variantes de escritura) ===")
    for id_persona, periodos in sorted(pases_reales.items()):
        print(f"\n{id_persona}:")
        for p in periodos:
            print(f"  {p['desde_fecha']} (acta {p['desde_actaId']}) -> "
                  f"{p['hasta_fecha']} (acta {p['hasta_actaId']}): {p['bloque_canonico']}")

    print(f"\nGuardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
