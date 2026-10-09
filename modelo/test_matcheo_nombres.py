"""Tests de matcheo_nombres.py.

Usa la tabla real de nombres (vía RepositorioEvidencia) para los casos
concretos ya vistos en la validación contra la OD 209 — Montenegro
ambiguo, Scaglia/del Caño en formato "Nombre Apellido", etc. — en vez de
mockear, siguiendo el mismo criterio que test_promedios.py.
"""

import pytest

from modelo.datos_evidencia import RepositorioEvidencia
from modelo.matcheo_nombres import matchear_nombres


@pytest.fixture(scope="module")
def tabla_nombres():
    evidencia = RepositorioEvidencia()
    return {i: evidencia.nombre_de(i) for i in evidencia.universo_diputados()}


# ---------------------------------------------------------------------------
# casos sintéticos simples
# ---------------------------------------------------------------------------


def test_apellido_unico_matchea():
    tabla = {"a1": "PEREZ, JUAN", "a2": "GOMEZ, ANA"}
    resultado = matchear_nombres(["Perez"], tabla)
    assert resultado.matcheados == {"Perez": "a1"}
    assert not resultado.hay_problemas


def test_sin_match_no_se_fuerza():
    tabla = {"a1": "PEREZ, JUAN"}
    resultado = matchear_nombres(["Rodriguez"], tabla)
    assert resultado.sin_match == ["Rodriguez"]
    assert resultado.matcheados == {}


def test_ambiguo_queda_listado_no_forzado():
    tabla = {"a1": "PEREZ, JUAN", "a2": "PEREZ, MARIA"}
    resultado = matchear_nombres(["Perez"], tabla)
    assert "Perez" in resultado.ambiguos
    assert {c.id_diputado for c in resultado.ambiguos["Perez"]} == {"a1", "a2"}
    assert resultado.matcheados == {}


def test_inicial_desambigua():
    tabla = {"a1": "PEREZ, JUAN", "a2": "PEREZ, MARIA"}
    resultado = matchear_nombres(["M. Perez"], tabla)
    assert resultado.matcheados == {"M. Perez": "a2"}


def test_lineas_vacias_se_ignoran():
    tabla = {"a1": "PEREZ, JUAN"}
    resultado = matchear_nombres(["", "  ", "Perez"], tabla)
    assert resultado.matcheados == {"Perez": "a1"}
    assert not resultado.sin_match and not resultado.ambiguos


def test_acentos_no_importan():
    tabla = {"a1": "GUTIERREZ, RAMIRO"}
    resultado = matchear_nombres(["Gutiérrez"], tabla)
    assert resultado.matcheados == {"Gutiérrez": "a1"}


# ---------------------------------------------------------------------------
# casos reales, de la validación contra la OD 209
# ---------------------------------------------------------------------------


def test_nombre_apellido_orden_invertido_real(tabla_nombres):
    # "Gisela Scaglia" en vez de "Scaglia, Gisela"
    resultado = matchear_nombres(["Gisela Scaglia"], tabla_nombres)
    assert resultado.matcheados["Gisela Scaglia"] == "scaglia-gisela"


def test_apellido_compuesto_orden_invertido_real(tabla_nombres):
    resultado = matchear_nombres(["Nicolás del Caño"], tabla_nombres)
    assert resultado.matcheados["Nicolás del Caño"] == "del-cano-nicolas"


def test_montenegro_ambiguo_real(tabla_nombres):
    resultado = matchear_nombres(["Montenegro"], tabla_nombres)
    assert "Montenegro" in resultado.ambiguos
    ids = {c.id_diputado for c in resultado.ambiguos["Montenegro"]}
    assert ids == {"montenegro-guillermo-tristan", "montenegro-juan-pablo"}


def test_inicial_mas_apellido_real(tabla_nombres):
    resultado = matchear_nombres(["A. Gonzales"], tabla_nombres)
    assert resultado.matcheados["A. Gonzales"] == "gonzales-alfredo"


def test_apellido_compuesto_real(tabla_nombres):
    resultado = matchear_nombres(["Herrera Ahuad"], tabla_nombres)
    assert resultado.matcheados["Herrera Ahuad"] == "herrera-ahuad-oscar-a"


def test_persona_fuera_del_universo_no_matchea(tabla_nombres):
    # Pitrola ya no está en banca (reemplazado por Giordano) -> no debe
    # estar en una tabla scopeada al universo actual.
    assert "pitrola-nestor" not in tabla_nombres
    resultado = matchear_nombres(["Pitrola"], tabla_nombres)
    assert resultado.sin_match == ["Pitrola"]


# ---------------------------------------------------------------------------
# inicial de segundo nombre (bug real, hallado al parsear firmantes de la
# OD 209: "María G. Flores", "Carlos D. Castagneto", etc. no matcheaban
# porque el token suelto de una sola letra -la "G", la "D"- no forma parte
# del nombre canónico completo y rompía el match por subconjunto)
# ---------------------------------------------------------------------------


def test_inicial_de_segundo_nombre_real(tabla_nombres):
    resultado = matchear_nombres(["María G. Flores"], tabla_nombres)
    assert resultado.matcheados["María G. Flores"] == "flores-maria-gabriela"


def test_inicial_de_segundo_nombre_castagneto_real(tabla_nombres):
    resultado = matchear_nombres(["Carlos D. Castagneto"], tabla_nombres)
    assert resultado.matcheados["Carlos D. Castagneto"] == "castagneto-carlos-daniel"


def test_inicial_de_segundo_nombre_ianni_real(tabla_nombres):
    resultado = matchear_nombres(["Ana M. Ianni"], tabla_nombres)
    assert resultado.matcheados["Ana M. Ianni"] == "ianni-ana-maria"


def test_inicial_de_segundo_nombre_rossi_real(tabla_nombres):
    resultado = matchear_nombres(["Agustín O. Rossi"], tabla_nombres)
    assert resultado.matcheados["Agustín O. Rossi"] == "rossi-agustin-oscar"


def test_inicial_de_segundo_nombre_yedlin_real(tabla_nombres):
    resultado = matchear_nombres(["Pablo R. Yedlin"], tabla_nombres)
    assert resultado.matcheados["Pablo R. Yedlin"] == "yedlin-pablo-raul"


def test_inicial_de_segundo_nombre_desambigua_montenegro_real(tabla_nombres):
    # a diferencia de "Montenegro" a secas (ambiguo, ver test de arriba),
    # el nombre de pila "Juan" ya alcanza para desambiguar -- la inicial
    # de en medio ("P.") se descarta pero no hace falta para este caso.
    resultado = matchear_nombres(["Juan P. Montenegro"], tabla_nombres)
    assert resultado.matcheados["Juan P. Montenegro"] == "montenegro-juan-pablo"


def test_solo_iniciales_sin_apellido_no_matchea(tabla_nombres):
    # si tras descartar los tokens de una sola letra no queda nada, no hay
    # nada por lo cual buscar -- no debe reventar ni matchear cualquier cosa.
    resultado = matchear_nombres(["A. B."], tabla_nombres)
    assert resultado.sin_match == ["A. B."]
