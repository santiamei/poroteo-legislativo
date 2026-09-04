#!/usr/bin/env python3
"""Caracteriza los despegues de las 13 actas disputadas por eje temático
(mapa asignado a mano). Trabaja sobre data/processed/votos_consolidado.csv.

No interpreta políticamente — reporta votos y patrones crudos.

Uso:
    python ingesta/analizar_despegues_ejes.py
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path

VOTOS_PATH = Path(__file__).parent.parent / "data" / "processed" / "votos_consolidado.csv"

EJE_POR_ACTA = {
    "5822": "Económico/fiscal", "5838": "Económico/fiscal", "5956": "Económico/fiscal",
    "5974": "Económico/fiscal", "5971": "Económico/fiscal", "5955": "Económico/fiscal",
    "5853": "Laboral",
    "5902": "Ambiental/regulatorio", "5919": "Ambiental/regulatorio",
    "5847": "Social/derechos",
    "5931": "Federal/servicios",
    "5849": "Comercio exterior", "5981": "Comercio exterior",
}
ACTAS_DISPUTADAS = set(EJE_POR_ACTA)

FOCO_PU = {
    "capozzi-sergio-eduardo": "CAPOZZI",
    "nunez-jose": "NUÑEZ",
    "rizzotti-jorge": "RIZZOTTI",
    "scaglia-gisela": "SCAGLIA",
}

ORDEN_EJES = [
    "Económico/fiscal", "Laboral", "Ambiental/regulatorio",
    "Social/derechos", "Federal/servicios", "Comercio exterior",
]


def cargar_filas():
    with open(VOTOS_PATH, encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row["acta_id"] in ACTAS_DISPUTADAS]


def parte_1_foco_pu(filas):
    print("=" * 100)
    print("1) LOS 4 DE PROVINCIAS UNIDAS — voto acta por acta, agrupado por eje")
    print("=" * 100)

    votos = defaultdict(dict)  # id -> {acta_id: voto}  (todas las filas, incl. AUSENTE)
    for row in filas:
        if row["id_diputado"] in FOCO_PU:
            votos[row["id_diputado"]][row["acta_id"]] = row["voto"]

    for id_, apodo in FOCO_PU.items():
        votos_validos = sum(1 for v in votos[id_].values() if v in {"AFIRMATIVO", "NEGATIVO", "ABSTENCION"})
        nota = "  <-- MENOR COBERTURA" if id_ == "rizzotti-jorge" else ""
        print(f"\n--- {apodo} ({id_}) | posiciones válidas: {votos_validos}/13 (resto AUSENTE){nota} ---")
        for eje in ORDEN_EJES:
            actas_del_eje = [a for a, e in EJE_POR_ACTA.items() if e == eje]
            linea = []
            for acta_id in actas_del_eje:
                voto = votos[id_].get(acta_id, "SIN DATO")
                linea.append(f"{acta_id}={voto}")
            print(f"    {eje:<24} {' | '.join(linea)}")


def nucleo_por_eje(filas, bloque):
    print(f"\n--- núcleo {bloque} ---")
    por_eje = defaultdict(Counter)
    for row in filas:
        if row["bloque_canonico_en_esa_fecha"] != bloque:
            continue
        por_eje[EJE_POR_ACTA[row["acta_id"]]][row["voto"]] += 1

    for eje in ORDEN_EJES:
        c = por_eje[eje]
        total = sum(c.values())
        if total == 0:
            continue
        partes = ", ".join(f"{v}:{n} ({100*n/total:.0f}%)" for v, n in c.most_common())
        print(f"    {eje:<24} n={total:<5} {partes}")


def parte_2_nucleos(filas):
    print("\n" + "=" * 100)
    print("2) LÍNEA DE REFERENCIA — La Libertad Avanza vs. Unión por la Patria, por eje")
    print("=" * 100)
    nucleo_por_eje(filas, "La Libertad Avanza")
    nucleo_por_eje(filas, "Unión por la Patria")


def parte_3_disidencias_uxp(filas):
    print("\n" + "=" * 100)
    print("3) DISIDENCIAS DE UxP — quién se despega de la posición mayoritaria del bloque, acta por acta")
    print("=" * 100)

    votos_uxp_por_acta = defaultdict(list)  # acta_id -> [(id, nombre, voto)]
    for row in filas:
        if row["bloque_canonico_en_esa_fecha"] == "Unión por la Patria" and row["voto"] in {"AFIRMATIVO", "NEGATIVO", "ABSTENCION"}:
            votos_uxp_por_acta[row["acta_id"]].append((row["id_diputado"], row["nombre_canonico"], row["voto"]))

    despegues_por_diputado = defaultdict(list)  # id -> [(acta_id, eje, voto, mayoria)]

    for acta_id in sorted(ACTAS_DISPUTADAS, key=lambda a: int(a)):
        miembros = votos_uxp_por_acta[acta_id]
        conteo = Counter(v for _, _, v in miembros)
        mayoria, n_mayoria = conteo.most_common(1)[0]
        disidentes = [(id_, nombre, voto) for id_, nombre, voto in miembros if voto != mayoria]
        print(f"\nacta {acta_id} ({EJE_POR_ACTA[acta_id]}) — mayoría UxP: {mayoria} "
              f"({n_mayoria}/{len(miembros)}) — {len(disidentes)} disidentes")
        for id_, nombre, voto in disidentes:
            print(f"    {nombre:<35} votó {voto}")
            despegues_por_diputado[id_].append((acta_id, EJE_POR_ACTA[acta_id], voto, mayoria))

    print("\n--- diputados de UxP con MÁS DE UN despegue ---")
    reincidentes = {id_: d for id_, d in despegues_por_diputado.items() if len(d) > 1}
    if not reincidentes:
        print("    ninguno — cada disidencia fue de una persona distinta.")
    else:
        nombres = {row["id_diputado"]: row["nombre_canonico"] for row in filas}
        for id_, d in sorted(reincidentes.items(), key=lambda kv: -len(kv[1])):
            print(f"\n    {nombres[id_]} — {len(d)} despegues:")
            for acta_id, eje, voto, mayoria in d:
                print(f"        acta {acta_id} ({eje}): votó {voto}, mayoría del bloque era {mayoria}")

    ejes_de_despegue = Counter(eje for d in despegues_por_diputado.values() for _, eje, _, _ in d)
    print("\n--- despegues de UxP por eje (total, contando repeticiones) ---")
    for eje in ORDEN_EJES:
        if ejes_de_despegue[eje]:
            print(f"    {eje:<24} {ejes_de_despegue[eje]}")


def parte_4_abstenciones_fit(filas):
    print("\n" + "=" * 100)
    print("4) ABSTENCIONES DEL FIT (PTS, Partido Obrero) — por eje/acta")
    print("=" * 100)

    bloques_fit = {
        "Frente de Izquierda y de los Trabajadores - Unidad (PTS)",
        "Frente de Izquierda y de los Trabajadores - Unidad (Partido Obrero)",
    }

    votos_fit = [row for row in filas if row["bloque_canonico_en_esa_fecha"] in bloques_fit]
    por_persona = defaultdict(dict)
    for row in votos_fit:
        por_persona[(row["nombre_canonico"], row["bloque_canonico_en_esa_fecha"])][row["acta_id"]] = row["voto"]

    for (nombre, bloque), votos in sorted(por_persona.items()):
        print(f"\n--- {nombre} [{bloque.split('(')[-1][:-1]}] ---")
        abstenciones = []
        for eje in ORDEN_EJES:
            actas_del_eje = [a for a, e in EJE_POR_ACTA.items() if e == eje]
            linea = []
            for acta_id in actas_del_eje:
                voto = votos.get(acta_id, "SIN DATO")
                linea.append(f"{acta_id}={voto}")
                if voto == "ABSTENCION":
                    abstenciones.append((acta_id, eje))
            print(f"    {eje:<24} {' | '.join(linea)}")
        if abstenciones:
            print(f"    >> abstenciones: {abstenciones}")


def main():
    filas = cargar_filas()
    parte_1_foco_pu(filas)
    parte_2_nucleos(filas)
    parte_3_disidencias_uxp(filas)
    parte_4_abstenciones_fit(filas)


if __name__ == "__main__":
    main()
