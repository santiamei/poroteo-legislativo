"""Tests de parseo_od.py.

La mayoría operan sobre texto ya "extraído" (parsear_od_texto), para
testear el parseo sin depender de tener un PDF de verdad a mano. Pero
parsear_od_pdf() SÍ tiene lógica propia que vale la pena testear aparte
(_texto_columnas_pagina): las OD de HCDN son a dos columnas, y pdfplumber
por default mezcla ambas columnas línea por línea — hay que cortar cada
página en dos antes de extraer texto. Eso se valida al final de este
archivo contra el PDF real de la OD 209 (modelo/fixtures/od_144_209.pdf).

Usa la tabla real de nombres (vía RepositorioEvidencia), igual que
test_matcheo_nombres.py, para que los casos de matcheo ambiguo/sin
match sean los mismos ya validados contra la OD 209 real.
"""

from pathlib import Path

import pytest

from modelo.datos_evidencia import RepositorioEvidencia
from modelo.parseo_od import (
    CONFIANZA_ALTA,
    CONFIANZA_BAJA,
    TIPO_DISIDENCIA_PARCIAL,
    TIPO_DISIDENCIA_TOTAL,
    TIPO_MAYORIA,
    TIPO_MINORIA,
    parsear_od_pdf,
    parsear_od_texto,
)

_FIXTURE_OD_209 = Path(__file__).parent / "fixtures" / "od_144_209.pdf"


@pytest.fixture(scope="module")
def tabla_nombres():
    evidencia = RepositorioEvidencia()
    return {i: evidencia.nombre_de(i) for i in evidencia.universo_diputados()}


# ---------------------------------------------------------------------------
# cabecera: número de OD y título
# ---------------------------------------------------------------------------


def test_extrae_numero_y_titulo():
    # estructura real de HCDN: "SUMARIO:" + texto hasta la primera línea en
    # blanco, luego el índice "I. Dictamen de mayoría." (que NO debe
    # detectarse como el encabezado real del dictamen).
    texto = """
ORDEN DEL DÍA Nº 209

SUMARIO: Modificación del impuesto a las ganancias.

I. Dictamen de mayoría.

I
Dictamen de la mayoría

Honorable Cámara:

Gisela Scaglia. – Nicolás del Caño.
"""
    resultado = parsear_od_texto(texto, {})
    assert resultado.numero_od == "209"
    assert resultado.titulo == "Modificación del impuesto a las ganancias."


def test_sin_numero_de_od_no_rompe():
    resultado = parsear_od_texto("texto sin cabecera reconocible", {})
    assert resultado.numero_od is None
    assert resultado.titulo is None


# ---------------------------------------------------------------------------
# detección de secciones y separación de firmantes
# ---------------------------------------------------------------------------


def test_mayoria_y_minoria_simple(tabla_nombres):
    texto = """
Dictamen de la mayoría

Gisela Scaglia. – Nicolás del Caño. – Herrera Ahuad.

Dictamen de minoría

A. Gonzales.
"""
    resultado = parsear_od_texto(texto, tabla_nombres)

    tipos = {s.tipo for s in resultado.secciones}
    assert tipos == {TIPO_MAYORIA, TIPO_MINORIA}

    sec_mayoria = next(s for s in resultado.secciones if s.tipo == TIPO_MAYORIA)
    assert sec_mayoria.confianza == CONFIANZA_ALTA
    assert sec_mayoria.nombres_crudos == ("Gisela Scaglia", "Nicolás del Caño", "Herrera Ahuad")

    assert resultado.matcheo[TIPO_MAYORIA].matcheados == {
        "Gisela Scaglia": "scaglia-gisela",
        "Nicolás del Caño": "del-cano-nicolas",
        "Herrera Ahuad": "herrera-ahuad-oscar-a",
    }
    assert resultado.matcheo[TIPO_MINORIA].matcheados == {"A. Gonzales": "gonzales-alfredo"}
    assert resultado.ids_por_tipo[TIPO_MAYORIA] == (
        "scaglia-gisela",
        "del-cano-nicolas",
        "herrera-ahuad-oscar-a",
    )


def test_disidencia_parcial_sobre_mayoria(tabla_nombres):
    texto = """
Dictamen de la mayoría

Gisela Scaglia. – Herrera Ahuad.

En disidencia parcial:

Nicolás del Caño.
"""
    resultado = parsear_od_texto(texto, tabla_nombres)

    sec_disid = next(s for s in resultado.secciones if s.tipo == TIPO_DISIDENCIA_PARCIAL)
    assert sec_disid.confianza == CONFIANZA_ALTA
    assert sec_disid.nombres_crudos == ("Nicolás del Caño",)
    assert resultado.matcheo[TIPO_DISIDENCIA_PARCIAL].matcheados == {
        "Nicolás del Caño": "del-cano-nicolas"
    }
    # del Caño no debe quedar también contado como firmante pleno de mayoría
    assert "del-cano-nicolas" not in resultado.ids_por_tipo[TIPO_MAYORIA]


def test_disidencia_generica_sobre_mayoria_resuelve_a_parcial_y_marca_baja_confianza(tabla_nombres):
    texto = """
Dictamen de la mayoría

Gisela Scaglia.

En disidencia:

Nicolás del Caño.
"""
    resultado = parsear_od_texto(texto, tabla_nombres)
    sec_disid = next(s for s in resultado.secciones if "Caño" in s.nombres_crudos[0])
    assert sec_disid.tipo == TIPO_DISIDENCIA_PARCIAL
    assert sec_disid.confianza == CONFIANZA_BAJA


def test_disidencia_generica_sobre_minoria_resuelve_a_total(tabla_nombres):
    texto = """
Dictamen de minoría

A. Gonzales.

En disidencia:

Herrera Ahuad.
"""
    resultado = parsear_od_texto(texto, tabla_nombres)
    sec_disid = next(s for s in resultado.secciones if "Ahuad" in s.nombres_crudos[0])
    assert sec_disid.tipo == TIPO_DISIDENCIA_TOTAL
    assert sec_disid.confianza == CONFIANZA_BAJA


def test_dos_dictamenes_de_minoria_se_acumulan_en_el_mismo_tipo(tabla_nombres):
    texto = """
Dictamen de minoría N° 1

A. Gonzales.

Dictamen de minoría N° 2

Herrera Ahuad.
"""
    resultado = parsear_od_texto(texto, tabla_nombres)
    secs_minoria = [s for s in resultado.secciones if s.tipo == TIPO_MINORIA]
    assert len(secs_minoria) == 2
    assert resultado.ids_por_tipo[TIPO_MINORIA] == ("gonzales-alfredo", "herrera-ahuad-oscar-a")


def test_separador_por_puntos_cae_a_fallback_de_baja_confianza(tabla_nombres):
    texto = """
Dictamen de la mayoría

Gisela Scaglia. Herrera Ahuad.
"""
    resultado = parsear_od_texto(texto, tabla_nombres)
    sec = resultado.secciones[0]
    assert sec.confianza == CONFIANZA_BAJA
    assert sec.nombres_crudos == ("Gisela Scaglia", "Herrera Ahuad")


# ---------------------------------------------------------------------------
# matcheo problemático se propaga sin forzar nada
# ---------------------------------------------------------------------------


def test_firmante_ambiguo_queda_listado(tabla_nombres):
    texto = """
Dictamen de la mayoría

Montenegro.
"""
    resultado = parsear_od_texto(texto, tabla_nombres)
    r = resultado.matcheo[TIPO_MAYORIA]
    assert "Montenegro" in r.ambiguos
    assert resultado.hay_problemas


def test_firmante_sin_match_queda_listado(tabla_nombres):
    texto = """
Dictamen de la mayoría

Pitrola.
"""
    resultado = parsear_od_texto(texto, tabla_nombres)
    assert resultado.matcheo[TIPO_MAYORIA].sin_match == ["Pitrola"]
    assert resultado.hay_problemas


def test_sin_secciones_hay_problemas_es_falso_si_no_hay_nada_que_revisar(tabla_nombres):
    resultado = parsear_od_texto("texto sin ningún encabezado reconocible", tabla_nombres)
    assert resultado.secciones == ()
    assert not resultado.hay_problemas


# ---------------------------------------------------------------------------
# artefacto de negrita duplicada (mismo hallazgo que acta_pdf_parser.py)
# ---------------------------------------------------------------------------


def test_dedupe_negrita_en_encabezado(tabla_nombres):
    # el encabezado en negrita sale con cada carácter duplicado, tal como
    # lo produce el template de HCDN (ver parsers/NOTES.md).
    texto = "DDIICCTTAAMMEENN DDEE LLAA MMAAYYOORRÍÍAA\n\nGisela Scaglia."
    resultado = parsear_od_texto(texto, tabla_nombres)
    assert len(resultado.secciones) == 1
    assert resultado.secciones[0].tipo == TIPO_MAYORIA


# ---------------------------------------------------------------------------
# regresión contra la estructura real de la OD 209 (Ganancias, 144-209)
# ---------------------------------------------------------------------------
#
# Extracto reconstruido del PDF real que reproduce sus particularidades,
# cada una de las cuales rompió una versión anterior de este parser:
#   - el SUMARIO no tiene línea en blanco antes del índice "I. Dictamen...".
#   - ese índice ("I. Dictamen de mayoría.\nII. Dictamen de minoría.", etc.)
#     NO debe detectarse como encabezado real (el real está solo en su
#     línea, con el numeral romano en la línea anterior).
#   - el cuerpo del dictamen (el "Honorable Cámara:" + articulado) usa "–"
#     como puntuación normal, y por eso NO puede incluirse al separar los
#     firmantes por "–".
#   - cada dictamen cierra con un INFORME firmado por un solo miembro
#     informante, que NO es un firmante del dictamen y no debe colarse en
#     la lista.


_OD_209_EXTRACTO = """
CÁMARA DE DIPUTADOS DE LA NACIÓN 1
ORDEN DEL DÍA Nº 209

COMISIONES DE PRESUPUESTO Y HACIENDA
Y DE LEGISLACIÓN PENAL

SUMARIO: Leyes 11.683 y 27.799 relativas a la
modalidad simplificada de declaración jurada
del Impuesto a las Ganancias. Modificación. (6-P.E.-2026.)
I. Dictamen de mayoría.
II. Dictamen de minoría.

I
Dictamen de mayoría

Honorable Cámara:

Las Comisiones han considerado el proyecto –incluidas
las retenciones, percepciones, pagos a cuenta y anticipos–
y aconsejan su aprobación.

Sala de las Comisiones, 12 de agosto de 2026.

María G. Flores. – Luis Petri. – Juan P. Montenegro.

En disidencia:

Gisela Scaglia.

INFORME

Honorable Cámara:

Las Comisiones han considerado el proyecto y, por las
razones que se exponen, aconsejan su aprobación.

Bertie Benegas Lynch.

II
Dictamen de minoría

Honorable Cámara:

Las Comisiones han considerado el proyecto y, por las
razones que se exponen, aconsejan su rechazo.

Sala de las Comisiones, 12 de agosto de 2026.

Nicolás del Caño.

INFORME

Honorable Cámara:

Las Comisiones han considerado el proyecto y, por las
razones que se exponen, aconsejan su rechazo.

Nicolás del Caño.

ANTECEDENTE

El expediente podrá consultarse en el sitio web.
"""


def test_regresion_od_209_indice_no_se_detecta_como_encabezado(tabla_nombres):
    resultado = parsear_od_texto(_OD_209_EXTRACTO, tabla_nombres)
    # el índice tiene "I. Dictamen de mayoría." y "II. Dictamen de
    # minoría." -- si se detectaran como encabezados, habría 2 secciones
    # de cada tipo en vez de 1.
    assert sum(1 for s in resultado.secciones if s.tipo == TIPO_MAYORIA) == 1
    assert sum(1 for s in resultado.secciones if s.tipo == TIPO_MINORIA) == 1


def test_regresion_od_209_titulo_no_incluye_el_indice(tabla_nombres):
    resultado = parsear_od_texto(_OD_209_EXTRACTO, tabla_nombres)
    assert resultado.numero_od == "209"
    assert "Dictamen de mayoría" not in resultado.titulo
    assert resultado.titulo.startswith("Leyes 11.683 y 27.799")
    assert resultado.titulo.endswith("(6-P.E.-2026.)")


def test_regresion_od_209_cuerpo_con_guion_no_contamina_firmantes(tabla_nombres):
    resultado = parsear_od_texto(_OD_209_EXTRACTO, tabla_nombres)
    sec_mayoria = next(s for s in resultado.secciones if s.tipo == TIPO_MAYORIA)
    assert sec_mayoria.nombres_crudos == ("María G. Flores", "Luis Petri", "Juan P. Montenegro")


def test_regresion_od_209_informe_no_se_cuela_en_firmantes(tabla_nombres):
    resultado = parsear_od_texto(_OD_209_EXTRACTO, tabla_nombres)
    sec_minoria = next(s for s in resultado.secciones if s.tipo == TIPO_MINORIA)
    assert sec_minoria.nombres_crudos == ("Nicolás del Caño",)
    # "Bertie Benegas Lynch" y el segundo "Nicolás del Caño" son firmas de
    # INFORME, no de dictamen -- no deben aparecer como firmantes.
    assert resultado.matcheo[TIPO_MAYORIA].sin_match == []
    assert resultado.matcheo[TIPO_MAYORIA].matcheados["María G. Flores"] == "flores-maria-gabriela"


def test_regresion_od_209_caso_de_control_completo(tabla_nombres):
    """1 mayoría + 1 minoría + Scaglia en disidencia parcial — el caso de
    control real (la versión completa de la OD tiene 3 minorías). Con el
    fix de inicial de segundo nombre, "María G. Flores" y "Juan P.
    Montenegro" matchean también (antes quedaban sin_match)."""
    resultado = parsear_od_texto(_OD_209_EXTRACTO, tabla_nombres)
    assert resultado.ids_por_tipo[TIPO_MAYORIA] == (
        "flores-maria-gabriela",
        "petri-luis",
        "montenegro-juan-pablo",
    )
    assert resultado.ids_por_tipo[TIPO_MINORIA] == ("del-cano-nicolas",)
    assert resultado.ids_por_tipo[TIPO_DISIDENCIA_PARCIAL] == ("scaglia-gisela",)
    assert resultado.ids_por_tipo[TIPO_DISIDENCIA_TOTAL] == ()


# ---------------------------------------------------------------------------
# PDF real de la OD 209 (144-209, Ganancias) — fija el resultado correcto
# tras resolver el mezclado de columnas de pdfplumber.
# ---------------------------------------------------------------------------

pytestmark_pdf_real = pytest.mark.skipif(
    not _FIXTURE_OD_209.exists(), reason="falta modelo/fixtures/od_144_209.pdf"
)


@pytest.fixture(scope="module")
def resultado_od_209_real(tabla_nombres):
    pytest.importorskip("pdfplumber")
    if not _FIXTURE_OD_209.exists():
        pytest.skip("falta modelo/fixtures/od_144_209.pdf")
    return parsear_od_pdf(_FIXTURE_OD_209, tabla_nombres)


@pytestmark_pdf_real
def test_pdf_real_od_209_cabecera(resultado_od_209_real):
    assert resultado_od_209_real.numero_od == "209"
    assert resultado_od_209_real.titulo == (
        "Leyes 11.683 y 27.799 relativas a la modalidad simplificada de "
        "declaración jurada del Impuesto a las Ganancias y en materia de "
        "prescripción tributaria, y 25.191 referente al Régimen "
        "Sancionatorio. Modificación. (6-P.E.-2026.)"
    )


@pytestmark_pdf_real
def test_pdf_real_od_209_estructura(resultado_od_209_real):
    # 1 dictamen de mayoría + 3 de minoría + Scaglia en disidencia parcial,
    # en el orden real del documento: la disidencia va pegada a la mayoría
    # (aparece antes de los dictámenes de minoría).
    assert [s.tipo for s in resultado_od_209_real.secciones] == [
        TIPO_MAYORIA,
        TIPO_DISIDENCIA_PARCIAL,
        TIPO_MINORIA,
        TIPO_MINORIA,
        TIPO_MINORIA,
    ]


@pytestmark_pdf_real
def test_pdf_real_od_209_las_70_firmas_matchean_sin_problemas(resultado_od_209_real):
    r = resultado_od_209_real
    assert len(r.matcheo[TIPO_MAYORIA].matcheados) == 39
    assert len(r.matcheo[TIPO_MINORIA].matcheados) == 30
    assert len(r.matcheo[TIPO_DISIDENCIA_PARCIAL].matcheados) == 1
    assert len(r.matcheo[TIPO_DISIDENCIA_TOTAL].matcheados) == 0
    for tipo in (TIPO_MAYORIA, TIPO_MINORIA, TIPO_DISIDENCIA_PARCIAL, TIPO_DISIDENCIA_TOTAL):
        assert r.matcheo[tipo].sin_match == []
        assert r.matcheo[tipo].ambiguos == {}


@pytestmark_pdf_real
def test_pdf_real_od_209_caso_de_control(resultado_od_209_real):
    # ids puntuales mencionados como caso de control en la validación
    # manual contra esta OD (Petri y Bornoroni en mayoría, Kirchner y
    # Moreau en minoría, Scaglia en disidencia, Montenegro ya no ambiguo
    # porque "Juan P." alcanza para desambiguar entre los dos Montenegro).
    r = resultado_od_209_real
    assert "petri-luis" in r.ids_por_tipo[TIPO_MAYORIA]
    assert "montenegro-juan-pablo" in r.ids_por_tipo[TIPO_MAYORIA]
    assert "del-cano-nicolas" in r.ids_por_tipo[TIPO_MINORIA]
    assert "castagneto-carlos-daniel" in r.ids_por_tipo[TIPO_MINORIA]
    assert r.ids_por_tipo[TIPO_DISIDENCIA_PARCIAL] == ("scaglia-gisela",)
    # único punto marcado como de baja confianza: el "En disidencia:" sin
    # calificar se resuelve por contexto, no por texto explícito — sigue
    # siendo correcto, pero amerita que la UI lo señale para revisión.
    assert [s.tipo for s in r.secciones_baja_confianza] == [TIPO_DISIDENCIA_PARCIAL]
