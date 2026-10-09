#!/usr/bin/env python3
"""Parseo de una Orden del Día (OD) de la Cámara de Diputados desde PDF.

Las OD de HCDN siguen una estructura regular: un dictamen de mayoría y
uno o más de minoría, cada uno con una lista de firmantes al final
(nombres separados por "–" o puntos), y a veces firmantes "en
disidencia" sobre el dictamen de mayoría.

El sistema PROPONE, el usuario CONFIRMA: este módulo nunca decide una
votación por sí solo. Separa cada firmante detectado en "matcheado",
"ambiguo" o "sin match" (vía matcheo_nombres.py) y marca cada sección
como de confianza "alta" o "baja" según qué tan regular fue el patrón
de encabezado/separador que la detectó — para que la UI (etapa
siguiente) pueda mostrar qué revisar antes de proyectar.

No toca el modelo ni la app: solo produce una ResultadoParseoOD que,
más adelante, se usará para construir un CargaOD (modelo/interfaz.py).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from modelo.matcheo_nombres import ResultadoMatcheo, matchear_nombres

TIPO_MAYORIA = "mayoria"
TIPO_MINORIA = "minoria"
TIPO_DISIDENCIA_PARCIAL = "disidencia_parcial"
TIPO_DISIDENCIA_TOTAL = "disidencia_total"

TIPOS = (TIPO_MAYORIA, TIPO_MINORIA, TIPO_DISIDENCIA_PARCIAL, TIPO_DISIDENCIA_TOTAL)

CONFIANZA_ALTA = "alta"
CONFIANZA_BAJA = "baja"

# Encabezados que abren una sección de dictamen. El grupo nombrado "tipo"
# dice a qué bucket cae, SALVO "disidencia_generica", que es ambigua y se
# resuelve según en qué dictamen esté anidada (ver _resolver_tipo_generico).
#
# Anclados a LÍNEA COMPLETA (^...$ con re.MULTILINE): las OD reales traen,
# antes del cuerpo, un índice tipo "I. Dictamen de mayoría.\nII. Dictamen
# de minoría." — sin anclar a línea completa, ese índice matchea como si
# fueran los encabezados reales. El encabezado real SIEMPRE está solo en
# su línea (el numeral romano va en la línea anterior).
_PATRON_ENCABEZADO = re.compile(
    r"""
    ^[ \t]*DICTAMEN\s+DE\s+(LA\s+)?MAYOR[IÍ]A[ \t]*\.?[ \t]*$                                  (?P<mayoria>)
    | ^[ \t]*DICTAMEN\s+DE\s+(LA\s+)?MINOR[IÍ]A(\s*N[º°o]?\s*\d+)?[ \t]*\.?[ \t]*$              (?P<minoria>)
    | ^[ \t]*EN\s+DISIDENCIA\s+PARCIAL[ \t]*:?[ \t]*$                                           (?P<disidencia_parcial>)
    | ^[ \t]*EN\s+DISIDENCIA\s+TOTAL[ \t]*:?[ \t]*$                                             (?P<disidencia_total>)
    | ^[ \t]*EN\s+DISIDENCIA[ \t]*:?[ \t]*$                                                     (?P<disidencia_generica>)
    """,
    re.VERBOSE | re.IGNORECASE | re.MULTILINE,
)

_PATRON_NUMERO_OD = re.compile(r"ORDEN\s+DEL\s+D[IÍ]A\s*N[º°o]?\s*(\d+)", re.IGNORECASE)

# El sumario/título oficial viene marcado con esta etiqueta y termina
# antes de la primera línea en blanco O antes del índice "I. Dictamen de
# ..." que sigue — en la práctica, HCDN no siempre deja línea en blanco
# entre el sumario y ese índice.
_PATRON_SUMARIO = re.compile(
    r"SUMARIO:\s*(.+?)(?=\n[ \t]*\n|\n[ \t]*[IVXLCDM]+\.[ \t]*\S)",
    re.IGNORECASE | re.DOTALL,
)

# Marca el cierre de la parte firmada de un dictamen: todo lo que viene
# después (el informe que fundamenta el dictamen) tiene su propia firma de
# un solo miembro informante, que no es parte de la lista de firmantes.
_PATRON_INFORME = re.compile(r"^[ \t]*INFORME[ \t]*$", re.MULTILINE | re.IGNORECASE)

# Frase fija que antecede a la firma de cada dictamen ("Sala de las
# Comisiones, 12 de agosto de 2026."). Es el ancla más confiable para
# aislar la lista de firmantes del resto del dictamen: a diferencia de un
# salto de línea en blanco (que pdfplumber no siempre conserva entre
# párrafos), esta frase es texto literal fijo del template de HCDN.
_PATRON_SALA_COMISIONES = re.compile(
    r"Sala de (la|las) Comisi[oó]n(es)?,[^\n]*?\.", re.IGNORECASE
)

# Nota al pie fija ("* Integra dos (2) comisiones.") que HCDN intercala
# EN MEDIO de la lista de firmantes, justo donde cae el borde de columna
# del firmante al que corresponde — no al final, así que no alcanza con
# recortarla del cierre del bloque. El asterisco sale a veces como un
# glifo roto ("*<>?") según cómo pdfplumber lo extraiga; por eso el patrón
# no fija qué precede a "Integra", solo que la línea contenga esa frase.
_PATRON_NOTA_AL_PIE_COMISIONES = re.compile(
    r"^[^\n]*Integra\s+dos\s*\(2\)\s*comisiones\.?[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)

# Fallback cuando el bloque de firmantes no tiene "–": separa por un punto
# seguido de mayúscula, pero solo si antes del punto hay 2+ letras — así
# "A. Gonzales." no se parte en "A" y "Gonzales" por la inicial.
_PATRON_FALLBACK_SEPARADOR = re.compile(
    r"(?<=[A-Za-zÁÉÍÓÚÑáéíóúñ]{2})\.\s+(?=[A-ZÁÉÍÓÚÑ])"
)


def _dedupe_bold_token(tok: str) -> str:
    """Deshace el artefacto de PDF de HCDN donde el texto en negrita queda
    con cada carácter duplicado (ej. "AAFFIIRRMMAATTIIVVOO" -> "AFIRMATIVO").
    Mismo hallazgo que parsers/acta_pdf_parser.py — las OD comparten template."""
    if len(tok) >= 2 and len(tok) % 2 == 0:
        mitad = tok[0::2]
        if tok == "".join(c * 2 for c in mitad):
            return mitad
    return tok


def _dedupe_bold_linea(linea: str) -> str:
    return " ".join(_dedupe_bold_token(t) for t in linea.split(" "))


@dataclass(frozen=True)
class SeccionFirmantes:
    """Una sección de dictamen/disidencia ya detectada, con sus firmantes
    separados pero TODAVÍA sin matchear contra la tabla maestra."""

    tipo: str
    encabezado: str         # línea que disparó la detección, para auditoría
    nombres_crudos: tuple   # strings tal como quedaron separados del bloque
    confianza: str          # CONFIANZA_ALTA | CONFIANZA_BAJA


@dataclass(frozen=True)
class ResultadoParseoOD:
    """Salida completa del parseo de una OD. `matcheo` tiene una
    ResultadoMatcheo por tipo (ya acumulando todas las secciones de ese
    tipo, por si hay más de un dictamen de minoría)."""

    numero_od: Optional[str]
    titulo: Optional[str]
    secciones: tuple        # tuple[SeccionFirmantes, ...]
    matcheo: dict            # {tipo: ResultadoMatcheo}

    @property
    def ids_por_tipo(self) -> dict:
        """{tipo: tuple[id_diputado, ...]} — listo para armar un CargaOD."""
        return {tipo: resultado.ids for tipo, resultado in self.matcheo.items()}

    @property
    def secciones_baja_confianza(self) -> tuple:
        return tuple(s for s in self.secciones if s.confianza == CONFIANZA_BAJA)

    @property
    def hay_problemas(self) -> bool:
        return bool(self.secciones_baja_confianza) or any(
            r.hay_problemas for r in self.matcheo.values()
        )


def _extraer_cabecera(texto: str) -> tuple:
    m_numero = _PATRON_NUMERO_OD.search(texto)
    numero_od = m_numero.group(1) if m_numero else None

    titulo = None
    m_sumario = _PATRON_SUMARIO.search(texto)
    if m_sumario:
        titulo = " ".join(m_sumario.group(1).split())
    return numero_od, titulo


def _separar_nombres(bloque: str) -> tuple:
    """Separa un bloque de firmantes en nombres individuales.

    Preferencia: separador "–" (en-dash), que es el que usan las OD reales.
    Si el bloque no tiene ningún "–", cae a separar por ". " seguido de
    mayúscula — heurística más débil, pensada para el caso "separados por
    puntos" que menciona la tarea. Solo se considera "riesgosa" (y el
    llamador debe marcar confianza baja) cuando esa heurística realmente
    partió el bloque en más de un nombre; si el bloque ya era un solo
    nombre, no hubo ninguna decisión ambigua que tomar.
    """
    bloque = " ".join(bloque.split())  # colapsa saltos de línea/espacios
    if "–" in bloque:
        piezas = bloque.split("–")
        hubo_split_heuristico = False
    else:
        piezas = _PATRON_FALLBACK_SEPARADOR.split(bloque)
        hubo_split_heuristico = len(piezas) > 1

    nombres = tuple(p.strip().rstrip(".").strip() for p in piezas)
    nombres = tuple(n for n in nombres if n)
    return nombres, hubo_split_heuristico


def _bloque_firmantes(span: str) -> str:
    """De todo el texto entre un encabezado de sección y el siguiente,
    aísla el fragmento que realmente son los firmantes.

    Todo lo anterior a la firma es el cuerpo del dictamen ("Honorable
    Cámara: ...", el articulado), que usa "–" como puntuación normal
    (hasta en cada "Art. Nº – ...") y arruinaría el separador de nombres
    si se incluyera. Dos anclas, en orden de preferencia:

      1. "Sala de las Comisiones, <fecha>." — frase fija del template de
         HCDN que antecede a la firma de CADA dictamen; todo lo que sigue
         hasta el INFORME son los firmantes. Más confiable que buscar un
         salto de línea en blanco, que pdfplumber no siempre conserva
         entre párrafos.
      2. Si no aparece (ej. un "En disidencia:" sin fecha propia), se usa
         todo el tramo hasta el INFORME tal cual.
    """
    m_informe = _PATRON_INFORME.search(span)
    if m_informe:
        span = span[: m_informe.start()]

    matches_sala = list(_PATRON_SALA_COMISIONES.finditer(span))
    if matches_sala:
        span = span[matches_sala[-1].end() :]

    span = _PATRON_NOTA_AL_PIE_COMISIONES.sub("", span)
    return span.strip()


def _resolver_tipo(nombre_grupo: str, tipo_dictamen_actual: Optional[str]) -> str:
    if nombre_grupo != "disidencia_generica":
        return nombre_grupo
    # "En disidencia" sin calificar: según el enunciado de la tarea, sobre
    # el dictamen de mayoría se entiende como disidencia parcial. Sobre un
    # dictamen de minoría, se entiende como ir más allá (disidencia total).
    if tipo_dictamen_actual == TIPO_MINORIA:
        return TIPO_DISIDENCIA_TOTAL
    return TIPO_DISIDENCIA_PARCIAL


def _detectar_secciones(texto: str) -> list:
    """Encuentra cada encabezado de sección y le asigna el bloque de texto
    entre ese encabezado y el siguiente (o el final del documento)."""
    matches = list(_PATRON_ENCABEZADO.finditer(texto))
    secciones = []
    tipo_dictamen_actual = None  # último de mayoria/minoria visto, para resolver "en disidencia" genérica

    for i, m in enumerate(matches):
        nombre_grupo = m.lastgroup
        tipo = _resolver_tipo(nombre_grupo, tipo_dictamen_actual)
        if nombre_grupo in (TIPO_MAYORIA, TIPO_MINORIA):
            tipo_dictamen_actual = nombre_grupo

        inicio_bloque = m.end()
        fin_bloque = matches[i + 1].start() if i + 1 < len(matches) else len(texto)
        bloque = _bloque_firmantes(texto[inicio_bloque:fin_bloque])

        nombres, hubo_split_heuristico = _separar_nombres(bloque)
        if not nombres:
            continue

        confianza = (
            CONFIANZA_BAJA if (hubo_split_heuristico or nombre_grupo == "disidencia_generica") else CONFIANZA_ALTA
        )
        secciones.append(
            SeccionFirmantes(
                tipo=tipo,
                encabezado=m.group(0).strip(),
                nombres_crudos=nombres,
                confianza=confianza,
            )
        )

    return secciones


def parsear_od_texto(texto: str, tabla_nombres: dict) -> ResultadoParseoOD:
    """Corazón del parseo, operando sobre texto ya extraído — separado de
    la lectura del PDF para poder testearlo sin depender de pdfplumber ni
    de tener un PDF real a mano."""
    texto = "\n".join(_dedupe_bold_linea(l) for l in texto.splitlines())
    numero_od, titulo = _extraer_cabecera(texto)
    secciones = _detectar_secciones(texto)

    matcheo = {}
    for tipo in TIPOS:
        nombres_del_tipo = [n for s in secciones if s.tipo == tipo for n in s.nombres_crudos]
        matcheo[tipo] = matchear_nombres(nombres_del_tipo, tabla_nombres)

    return ResultadoParseoOD(
        numero_od=numero_od,
        titulo=titulo,
        secciones=tuple(secciones),
        matcheo=matcheo,
    )


def _texto_columnas_pagina(pagina) -> str:
    """Texto de una página a dos columnas, reconstruido en orden de
    lectura: toda la columna izquierda de arriba a abajo, después toda la
    columna derecha.

    Las OD de HCDN son a dos columnas, y pdfplumber por default arma cada
    línea del texto mezclando ambas columnas a la misma altura (ordena por
    y y después por x sobre la página COMPLETA) — da un texto donde cada
    renglón salta de una columna a la otra. Cortar la página al medio y
    extraer cada mitad por separado evita eso, porque cada extract_text()
    ya ordena de forma independiente dentro de su propio ancho.

    El encabezado de cada página ("O.D. Nº ... CÁMARA DE DIPUTADOS...",
    centrado y de ancho completo) NO es de dos columnas, así que cortarlo
    al medio lo arruina — queda partido en fragmentos ("DOS DE LA
    NACIÓN", "CÁMARA DE DIPUT") que se cuelan en el resto del texto. Por
    eso se recorta esa franja superior ANTES de dividir en columnas (el
    número de OD de la página 1, que vive justo en esa franja, se lee
    aparte de la extracción sin cortar — ver parsear_od_pdf).
    """
    MARGEN_SUPERIOR = 55  # pt: alto del renglón de encabezado "O.D. Nº ..."
    ancho = pagina.width
    corte = ancho / 2
    _, arriba, _, abajo = pagina.bbox
    arriba = max(arriba, MARGEN_SUPERIOR)
    izquierda = pagina.crop((0, arriba, corte, abajo)).extract_text() or ""
    derecha = pagina.crop((corte, arriba, ancho, abajo)).extract_text() or ""
    return izquierda + "\n" + derecha


def parsear_od_pdf(path, tabla_nombres: dict) -> ResultadoParseoOD:
    """Extrae el texto de un PDF de OD (vía pdfplumber) y lo parsea.
    `tabla_nombres`: {id_diputado: nombre_canonico}, scopeado al universo
    vigente (en la app, los mismos 257 que usa matcheo_nombres).

    El N° de OD se busca en la extracción SIN cortar en columnas (va en un
    encabezado centrado de ancho completo, que el corte por columnas
    arruina) y se usa como fallback si, por lo que sea, no se encontró en
    el texto ya reconstruido por columnas.
    """
    import pdfplumber  # import local: la app nunca llama esta función

    with pdfplumber.open(Path(path)) as pdf:
        texto_crudo = pdf.pages[0].extract_text() or ""
        texto = "\n".join(_texto_columnas_pagina(pagina) for pagina in pdf.pages)

    resultado = parsear_od_texto(texto, tabla_nombres)
    if resultado.numero_od is None:
        m = _PATRON_NUMERO_OD.search(texto_crudo)
        if m:
            resultado = ResultadoParseoOD(
                numero_od=m.group(1),
                titulo=resultado.titulo,
                secciones=resultado.secciones,
                matcheo=resultado.matcheo,
            )
    return resultado


if __name__ == "__main__":
    import sys

    from modelo.datos_evidencia import RepositorioEvidencia

    if len(sys.argv) != 2:
        print("Uso: python -m modelo.parseo_od /ruta/a/orden_del_dia.pdf")
        sys.exit(1)

    evidencia = RepositorioEvidencia()
    tabla = {i: evidencia.nombre_de(i) for i in evidencia.universo_diputados()}
    resultado = parsear_od_pdf(sys.argv[1], tabla)

    print(f"N° de OD: {resultado.numero_od!r}")
    print(f"Título: {resultado.titulo!r}")
    for tipo in TIPOS:
        r = resultado.matcheo[tipo]
        secs = [s for s in resultado.secciones if s.tipo == tipo]
        print(f"\n=== {tipo} ({len(secs)} sección/es) ===")
        for s in secs:
            print(f"  encabezado: {s.encabezado!r} (confianza: {s.confianza})")
        print(f"  matcheados: {len(r.matcheados)}, sin_match: {r.sin_match}, ambiguos: {list(r.ambiguos)}")

    if resultado.hay_problemas:
        print("\n⚠️  Hay secciones de baja confianza o nombres sin resolver — revisar antes de proyectar.")
