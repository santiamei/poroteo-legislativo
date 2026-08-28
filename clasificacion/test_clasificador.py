"""Tests del clasificador de títulos de votación.

Los casos de FONDO_GENERAL son títulos reales verificados de actas de
2026. El resto de los casos (PROCEDIMIENTO, FONDO_PARTICULAR, REVISAR) son
PROVISORIOS: sirven para fijar el comportamiento esperado del código
mientras no tenemos un corpus real contra el cual validar los patrones de
patrones.yaml. Cuando aparezcan títulos reales de esas categorías, estos
casos provisorios deberían reemplazarse o complementarse con ellos.
"""

import pytest

from clasificacion.clasificador import REVISAR, clasificar_votacion, normalizar


# ---------------------------------------------------------------------------
# normalizar()
# ---------------------------------------------------------------------------


def test_normalizar_mayusculas():
    assert normalizar("votación en general") == "VOTACION EN GENERAL"


def test_normalizar_saca_acentos():
    assert normalizar("CÁMARA FEDERAL DE TUCUMÁN") == "CAMARA FEDERAL DE TUCUMAN"


def test_normalizar_colapsa_espacios_multiples():
    assert normalizar("EN   GRAL     Y  PART") == "EN GRAL Y PART"


def test_normalizar_unifica_puntos():
    # "EN G. Y P." y "EN G Y P" deben normalizar al mismo texto.
    assert normalizar("VOT. EN G. Y P.") == normalizar("VOT EN G Y P")


def test_normalizar_titulo_vacio():
    assert normalizar("") == ""
    assert normalizar(None) == ""


# ---------------------------------------------------------------------------
# FONDO_GENERAL — títulos reales, verificados de actas de 2026
# ---------------------------------------------------------------------------

TITULOS_FONDO_GENERAL_REALES = [
    'O.D. 207 - "LEY JOAQUÍN", OBLIGATORIEDAD DE MEDIDAS DE SEGURIDAD EN EL '
    "DEPORTE Y ACTIVIDADES RECREATIVAS. ESTABLECIMIENTO. VOT. EN GRAL. Y PART.",
    'O.D. 270 - RITUAL, CELEB.Y PEREGR. DEL "CAMINO DE BROCHERO". DECL. COMO '
    "PARTE INTEGR. DEL PATRIMONIO INMMATERIAL DE LA REP. ARG. VOT EN G. Y P.",
    "O.D. 263 - CÁMARA FEDERAL DE APELACIONES DE TUCUMÁN. REORGANIZACIÓN. "
    "VOT. EN GRAL. Y PART.",
]


@pytest.mark.parametrize("titulo", TITULOS_FONDO_GENERAL_REALES)
def test_fondo_general_titulos_reales(titulo):
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "FONDO_GENERAL"
    assert resultado.patron_matcheado is not None


def test_fondo_general_reporta_patron_mas_especifico():
    # Cuando el título trae la forma completa "EN GRAL Y PART", el patrón
    # auditado debe ser ese, no el genérico "EN GRAL".
    resultado = clasificar_votacion(TITULOS_FONDO_GENERAL_REALES[0])
    assert "GRAL Y PART" in resultado.patron_matcheado


def test_fondo_general_forma_abreviada_en_g_y_p():
    # El segundo título real usa la abreviatura "EN G. Y P." en vez de
    # "EN GRAL Y PART" — confirma que el patrón abreviado también matchea.
    resultado = clasificar_votacion(TITULOS_FONDO_GENERAL_REALES[1])
    assert resultado.categoria == "FONDO_GENERAL"
    assert "G Y P" in resultado.patron_matcheado


# ---------------------------------------------------------------------------
# PROCEDIMIENTO — casos PROVISORIOS (a validar contra títulos reales)
# ---------------------------------------------------------------------------

TITULOS_PROCEDIMIENTO_PROVISORIOS = [
    # el caso de apartamiento del reglamento tiene sus propios tests más
    # abajo, porque además valida la etiqueta APARTAMIENTO.
    ("MOCION PARA TRATAR SOBRE TABLAS EL EXPEDIENTE 123", "SOBRE TABLAS"),
    ("CUARTO INTERMEDIO SOLICITADO POR EL BLOQUE X", "CUARTO INTERMEDIO"),
    ("PRORROGA DE LA SESION HASTA LAS 22 HORAS", "PRORROGA"),
    ("CUESTION DE PRIVILEGIO PLANTEADA POR EL DIPUTADO X", "CUESTION DE PRIVILEGIO"),
    ("RECONSIDERACION DEL EXPEDIENTE 456", "RECONSIDERACION"),
    ("JURAMENTO DE LOS DIPUTADOS ELECTOS", "JURAMENTO"),
]


@pytest.mark.parametrize("titulo,patron_esperado_substr", TITULOS_PROCEDIMIENTO_PROVISORIOS)
def test_procedimiento_provisorio(titulo, patron_esperado_substr):
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "PROCEDIMIENTO"
    assert patron_esperado_substr in resultado.patron_matcheado


# ---------------------------------------------------------------------------
# Etiqueta APARTAMIENTO dentro de PROCEDIMIENTO — casos PROVISORIOS
# ---------------------------------------------------------------------------

TITULOS_APARTAMIENTO_PROVISORIOS = [
    "MOCION DE APARTAMIENTO DEL REGLAMENTO PARA TRATAR EL EXPEDIENTE 789",
    "APARTAMIENTO PARA TRATAR SOBRE TABLAS EL PROYECTO X",
    "MOCION PARA APARTARSE DEL REGLAMENTO Y TRATAR EL TEMA Y",
]


@pytest.mark.parametrize("titulo", TITULOS_APARTAMIENTO_PROVISORIOS)
def test_apartamiento_sigue_siendo_procedimiento_con_etiqueta(titulo):
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "PROCEDIMIENTO"  # sigue siendo procedimiento, no una categoría nueva
    assert resultado.etiqueta == "APARTAMIENTO"


def test_apartamiento_titulo_real_con_nombre_de_diputado():
    # Título real: estas mociones no traen el tema de fondo, solo quién la
    # solicita — confirma por sí solo que es procedimiento, no fondo.
    titulo = "APARTAMIENTO DE REGLAMENTO SOLICITADO POR EL DIP. MASSOT, NICOLÁS."
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "PROCEDIMIENTO"
    assert resultado.etiqueta == "APARTAMIENTO"


@pytest.mark.parametrize(
    "conector",
    ["DE", "DEL", ""],
    ids=["conector_de", "conector_del", "conector_nada"],
)
def test_apartamiento_patron_flexible_conectores(conector):
    titulo = f"APARTAMIENTO {conector} REGLAMENTO".replace("  ", " ").strip()
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "PROCEDIMIENTO"
    assert resultado.etiqueta == "APARTAMIENTO"
    assert "REGLAMENTO" in resultado.patron_matcheado  # matcheó el patrón flexible, no el fallback bare


def test_procedimiento_sin_apartamiento_no_trae_etiqueta():
    # Otros trámites de procedimiento no deben traer etiqueta APARTAMIENTO.
    resultado = clasificar_votacion("CUARTO INTERMEDIO SOLICITADO POR EL BLOQUE X")
    assert resultado.categoria == "PROCEDIMIENTO"
    assert resultado.etiqueta is None


def test_fondo_general_no_trae_etiqueta():
    resultado = clasificar_votacion(TITULOS_FONDO_GENERAL_REALES[0])
    assert resultado.etiqueta is None


# ---------------------------------------------------------------------------
# FONDO_PARTICULAR — casos PROVISORIOS
# ---------------------------------------------------------------------------


def test_fondo_particular_provisorio_marcador_en_part():
    titulo = "O.D. 100 - LEY X. MODIFICACION DEL ARTICULO 5. VOT. EN PART."
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "FONDO_PARTICULAR"


def test_fondo_particular_provisorio_articulo_mas_numero():
    # Sin marcador "EN PART" explícito, solo "ART. <numero>".
    titulo = "O.D. 101 - LEY Y. SUSTITUYASE EL ART. 8 POR EL SIGUIENTE TEXTO"
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "FONDO_PARTICULAR"
    assert "ART" in resultado.patron_matcheado


def test_fondo_particular_provisorio_capitulo():
    titulo = "O.D. 103 - LEY W. SUSTITUYASE EL CAPITULO III DEL TITULO II"
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "FONDO_PARTICULAR"
    assert "CAPITULO" in resultado.patron_matcheado


def test_fondo_particular_provisorio_palabra_articulo_sin_general():
    titulo = "O.D. 102 - MODIFICACION DEL ARTICULO 12 DE LA LEY Z"
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "FONDO_PARTICULAR"


# ---------------------------------------------------------------------------
# REVISAR — casos PROVISORIOS
# ---------------------------------------------------------------------------


def test_revisar_provisorio_sin_marcadores():
    titulo = "O.D. 50 - INFORME ANUAL DE LA AUDITORIA GENERAL DE LA NACION"
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == REVISAR
    assert resultado.patron_matcheado is None


def test_revisar_titulo_vacio():
    resultado = clasificar_votacion("")
    assert resultado.categoria == REVISAR


# ---------------------------------------------------------------------------
# Regla explícita: "insistencia" NO es PROCEDIMIENTO
# ---------------------------------------------------------------------------


def test_insistencia_sola_no_es_procedimiento():
    # Sin ningún otro marcador, "insistencia" no debe caer en PROCEDIMIENTO.
    # (Cae en REVISAR porque tampoco trae marcador de general/particular.)
    titulo = "INSISTENCIA EN LA SANCION DEL PROYECTO DE LEY SOBRE TEMA X"
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria != "PROCEDIMIENTO"


def test_insistencia_con_marcador_de_general_es_fondo_general():
    # La insistencia es una votación de fondo aunque requiera dos tercios:
    # si trae marcador de general, debe clasificar FONDO_GENERAL.
    titulo = (
        "O.D. 30 - INSISTENCIA EN LA SANCION ANTERIOR DEL PROYECTO DE LEY. "
        "VOT. EN GRAL. Y PART."
    )
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "FONDO_GENERAL"


# ---------------------------------------------------------------------------
# Orden de prioridad
# ---------------------------------------------------------------------------


def test_procedimiento_tiene_prioridad_sobre_fondo():
    # Si un título trae marcador de procedimiento Y de fondo general a la
    # vez, debe ganar PROCEDIMIENTO (mayor prioridad).
    titulo = "CUARTO INTERMEDIO SOLICITADO ANTES DE LA VOTACION EN GRAL Y PART"
    resultado = clasificar_votacion(titulo)
    assert resultado.categoria == "PROCEDIMIENTO"


def test_fondo_general_tiene_prioridad_sobre_fondo_particular():
    # Un título con marcador de general Y de particular a la vez (caso
    # típico real: "VOT. EN GRAL. Y PART.") debe clasificar FONDO_GENERAL,
    # no FONDO_PARTICULAR.
    resultado = clasificar_votacion(TITULOS_FONDO_GENERAL_REALES[0])
    assert resultado.categoria == "FONDO_GENERAL"
