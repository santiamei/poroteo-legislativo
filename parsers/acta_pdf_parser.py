#!/usr/bin/env python3
"""Parser de respaldo para actas de votación nominal (PDF de votaciones.hcdn.gob.ar).

Rol en el pipeline: este parser es un FALLBACK, no la vía principal para
obtener los votos. La vía principal es el CSV que genera el propio sitio
en el navegador (sin llamada de red) para cada acta. Este módulo sirve para:

  1. Extraer la metadata de cabecera del acta (período, sesión, acta,
     fecha, tipo de mayoría, resultado, presidente) — el CSV del sitio no
     trae nada de esto.
  2. Como último recurso para los votos, si en algún momento no se puede
     conseguir el CSV de un acta puntual pero sí su PDF.

Ver NOTES.md en este mismo directorio para una limitación de calidad de
datos encontrada al validar este parser contra el acta 5995 (correlativo
29, período 144): la cabecera puede contar un "presente sin votar" que no
aparece identificado por nombre en ningún lado de la tabla de detalle, así
que cabecera y detalle no siempre reconcilian 1 a 1 por persona.

Uso:
    python parsers/acta_pdf_parser.py /ruta/a/acta.pdf
"""

import re
import sys
from pathlib import Path

import pdfplumber

HEADER_LINES_TO_SCAN = 12


def _dedupe_bold_token(tok):
    """Deshace el artefacto de PDF donde el texto en negrita queda con
    cada carácter duplicado (ej. "AAFFIIRRMMAATTIIVVOO" -> "AFIRMATIVO").
    Los espacios no se duplican, así que se opera token por token."""
    if len(tok) >= 2 and len(tok) % 2 == 0:
        halved = tok[0::2]
        if tok == "".join(c * 2 for c in halved):
            return halved
    return tok


def _dedupe_bold_line(line):
    return " ".join(_dedupe_bold_token(t) for t in line.split(" "))


def extract_header_metadata(pdf):
    """Metadata de la primera página: período/sesión, acta, fecha, mayoría,
    resultado, presidente. Devuelve un dict; claves ausentes si no matchean."""
    text = pdf.pages[0].extract_text() or ""
    lines = [_dedupe_bold_line(l) for l in text.splitlines()]
    header_blob = "\n".join(lines[:HEADER_LINES_TO_SCAN])

    meta = {}

    m = re.search(r"^(.+?°\s*-\s*.+?Reunión)\s*$", header_blob, re.M)
    if m:
        meta["periodo_sesion_reunion"] = m.group(1).strip()

    for i, l in enumerate(lines):
        if l.startswith("Acta N"):
            meta["titulo"] = lines[i - 1].strip()
            break

    m = re.search(
        r"Acta N[ºo]\s*(\d+)\s+Ult\.Mod\.Ver\s*(\d+)\s+Fecha:\s*([\d/]+)\s+Hora:\s*([\d:]+)",
        header_blob,
    )
    if m:
        meta["acta_nro_correlativo"] = m.group(1)
        meta["version"] = m.group(2)
        meta["fecha"] = m.group(3)
        meta["hora"] = m.group(4)

    m = re.search(
        r"Base Mayoría:\s*(.+?)\s+Tipo Mayoría:\s*(.+?)\s+Miembros del Cuerpo:\s*(\d+)",
        header_blob,
    )
    if m:
        meta["base_mayoria"] = m.group(1).strip()
        meta["tipo_mayoria"] = m.group(2).strip()
        meta["miembros_cuerpo"] = int(m.group(3))

    m = re.search(r"Resultado de Votación:\s*(.+?)\s+Presidente:\s*(.+)$", header_blob, re.M)
    if m:
        meta["resultado"] = m.group(1).strip()
        meta["presidente"] = m.group(2).strip()

    m = re.search(r"Presentes\s+(\d+)\s+(\d+)\s+(\d+)", header_blob)
    if m:
        meta["presentes_votando"] = int(m.group(1))
        meta["presentes_sin_votar"] = int(m.group(2))
        meta["presentes_total"] = int(m.group(3))

    m = re.search(r"Ausentes\s+(\d+)", header_blob)
    if m:
        meta["ausentes_total"] = int(m.group(1))

    return meta


def extract_vote_rows(pdf):
    """Filas de la tabla nominal: (apellido_y_nombre, bloque, distrito, voto).

    Usa pdfplumber.extract_table() con la estrategia default (basada en
    líneas de grilla). Funciona bien porque este template de acta SÍ tiene
    ruling lines en el PDF, aunque no se vean a simple vista. Si HCDN
    cambia el template y deja de haber grilla, esto puede dejar de andar
    silenciosamente — otra razón para no depender de este parser como vía
    principal.
    """
    rows = []
    for page in pdf.pages:
        table = page.extract_table()
        if not table:
            continue
        for r in table:
            if len(r) != 4 or any(c is None for c in r):
                continue  # filas de metadata/spacer que caen en la misma grilla
            first = (r[0] or "").strip()
            if not first or _dedupe_bold_line(first).lower().startswith("apellido"):
                continue  # encabezado de columna repetido en cada página
            apellido_nombre, bloque, distrito, voto = (
                (c.replace("\n", " ").strip() if c else c) for c in r
            )
            rows.append(
                {
                    "apellido_nombre": apellido_nombre,
                    "bloque": bloque,
                    "distrito": distrito,
                    "voto": voto,
                }
            )
    return rows


def reconcile(metadata, vote_rows):
    """Compara los conteos de la cabecera contra lo efectivamente listado
    por nombre en el detalle. Ver NOTES.md: no siempre da 1 a 1."""
    conteo_por_voto = {}
    for row in vote_rows:
        conteo_por_voto[row["voto"]] = conteo_por_voto.get(row["voto"], 0) + 1

    esperado_total = metadata.get("miembros_cuerpo")
    listado_total = len(vote_rows)

    return {
        "conteo_por_voto_en_detalle": conteo_por_voto,
        "filas_listadas_por_nombre": listado_total,
        "miembros_del_cuerpo_segun_cabecera": esperado_total,
        "presentes_sin_votar_segun_cabecera": metadata.get("presentes_sin_votar"),
        "reconcilia_1_a_1": (
            esperado_total is not None and listado_total == esperado_total
        ),
    }


def parse_acta_pdf(path):
    with pdfplumber.open(path) as pdf:
        metadata = extract_header_metadata(pdf)
        vote_rows = extract_vote_rows(pdf)
    return {
        "metadata": metadata,
        "votos": vote_rows,
        "reconciliacion": reconcile(metadata, vote_rows),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python parsers/acta_pdf_parser.py /ruta/a/acta.pdf")
        sys.exit(1)

    result = parse_acta_pdf(Path(sys.argv[1]))

    print("=== metadata ===")
    for k, v in result["metadata"].items():
        print(f"{k}: {v!r}")

    print(f"\n=== votos: {len(result['votos'])} filas ===")
    for row in result["votos"][:3]:
        print(row)
    print("...")
    for row in result["votos"][-3:]:
        print(row)

    print("\n=== reconciliación cabecera vs. detalle ===")
    for k, v in result["reconciliacion"].items():
        print(f"{k}: {v!r}")
