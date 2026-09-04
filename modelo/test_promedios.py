"""Tests del modelo de poroteo v1 (ModeloPromedios) y de la separación
interfaz/implementación.

Usa RepositorioEvidencia real (datos ya construidos en pasos anteriores)
en vez de mockear — es más una prueba de integración sobre datos
conocidos que una prueba unitaria pura, a propósito: lo que más importa
acá es que los números tengan sentido contra lo que ya sabemos del
dataset (LLA/UxP disciplinados, Provincias Unidas volátil, etc.).
"""

import pytest

from modelo.datos_evidencia import RepositorioEvidencia, TasaEvidencia
from modelo.interfaz import CargaOD, ModeloPoroteo, Votacion
from modelo.poroteo import armar_resultado
from modelo.promedios import ModeloPromedios


@pytest.fixture(scope="module")
def evidencia():
    return RepositorioEvidencia()


@pytest.fixture(scope="module")
def modelo(evidencia):
    return ModeloPromedios(evidencia)


# ---------------------------------------------------------------------------
# separación interfaz/implementación
# ---------------------------------------------------------------------------


def test_modelo_poroteo_es_abstracta():
    with pytest.raises(TypeError):
        ModeloPoroteo()


def test_poroteo_no_importa_modelo_promedios():
    import modelo.poroteo as p
    assert "ModeloPromedios" not in dir(p)


def test_modelo_promedios_implementa_la_interfaz(modelo):
    assert isinstance(modelo, ModeloPoroteo)


# ---------------------------------------------------------------------------
# shrinkage
# ---------------------------------------------------------------------------


def test_shrink_matematica_basica():
    tasa = TasaEvidencia(probabilidad_afirmativo=0.8, n=10)
    resultado = ModeloPromedios._shrink(tasa, hacia=0.5, k=10)
    # (10*0.8 + 10*0.5) / 20 = 0.65
    assert resultado == pytest.approx(0.65)


def test_shrink_sin_evidencia_propia_da_el_valor_hacia():
    tasa = TasaEvidencia(probabilidad_afirmativo=0.99, n=0)  # p irrelevante con n=0
    resultado = ModeloPromedios._shrink(tasa, hacia=0.3, k=10)
    assert resultado == pytest.approx(0.3)


def test_shrink_con_mucha_evidencia_propia_domina():
    tasa = TasaEvidencia(probabilidad_afirmativo=0.9, n=10_000)
    resultado = ModeloPromedios._shrink(tasa, hacia=0.1, k=5)
    assert resultado == pytest.approx(0.9, abs=0.01)


# ---------------------------------------------------------------------------
# comportamiento esperado sobre datos reales
# ---------------------------------------------------------------------------


def test_lla_alta_probabilidad_uxp_baja(modelo, evidencia):
    votacion = Votacion(titulo="prueba", eje="Económico/fiscal")
    predicciones = modelo.predecir(votacion)

    ids_lla = [i for i in evidencia.universo_diputados() if evidencia.bloque_actual_de(i) == "La Libertad Avanza"]
    ids_uxp = [i for i in evidencia.universo_diputados() if evidencia.bloque_actual_de(i) == "Unión por la Patria"]

    prom_lla = sum(predicciones[i].probabilidad_afirmativo for i in ids_lla) / len(ids_lla)
    prom_uxp = sum(predicciones[i].probabilidad_afirmativo for i in ids_uxp) / len(ids_uxp)

    assert prom_lla > 0.9
    assert prom_uxp < 0.1


def test_novato_sin_subgrupo_usa_bloque(modelo, evidencia):
    # giordano-juan-carlos fue excluido del clustering (baja cobertura) ->
    # no debería tener subgrupo asignado, y la fuente dominante de su
    # predicción no puede ser "subgrupo".
    assert evidencia.subgrupo_de("giordano-juan-carlos") is None
    votacion = Votacion(titulo="prueba", eje="Económico/fiscal")
    pred = modelo.predecir(votacion)["giordano-juan-carlos"]
    assert pred.fuente_dominante in {"bloque", "individual"}


def test_provincias_unidas_tiene_mas_incertidumbre_que_lla(modelo, evidencia):
    votacion = Votacion(titulo="prueba", eje="Económico/fiscal")
    predicciones = modelo.predecir(votacion)

    ids_pu = [i for i in evidencia.universo_diputados() if evidencia.bloque_actual_de(i) == "Provincias Unidas"]
    ids_lla = [i for i in evidencia.universo_diputados() if evidencia.bloque_actual_de(i) == "La Libertad Avanza"]

    ancho_prom_pu = sum(predicciones[i].ancho_banda for i in ids_pu) / len(ids_pu)
    ancho_prom_lla = sum(predicciones[i].ancho_banda for i in ids_lla) / len(ids_lla)

    assert ancho_prom_pu > ancho_prom_lla


# ---------------------------------------------------------------------------
# modo con OD
# ---------------------------------------------------------------------------


def test_od_ancla_firmantes_al_valor_exacto(modelo):
    od = CargaOD(numero="1", titulo="prueba OD", mayoria=("petri-luis",), minoria=("kirchner-maximo-carlos",))
    votacion = Votacion(titulo=od.titulo, eje="Económico/fiscal", od=od)
    predicciones = modelo.predecir(votacion)

    assert predicciones["petri-luis"].probabilidad_afirmativo == modelo.ancla_mayoria
    assert predicciones["petri-luis"].fuente_dominante == "ancla_od"
    assert predicciones["kirchner-maximo-carlos"].probabilidad_afirmativo == modelo.ancla_minoria


def test_od_propaga_al_resto_del_bloque(modelo, evidencia):
    # sin firmantes de Provincias Unidas: los no-firmantes de PU no deberían
    # marcarse como propagados.
    od_sin_pu = CargaOD(numero="2", titulo="prueba sin PU", mayoria=("petri-luis",))
    votacion_sin_pu = Votacion(titulo=od_sin_pu.titulo, eje="Económico/fiscal", od=od_sin_pu)
    pred_sin_pu = modelo.predecir(votacion_sin_pu)
    assert pred_sin_pu["schiaretti-juan"].fuente_dominante != "propagado_od"

    # con un firmante de Provincias Unidas: sus compañeros de bloque sí
    # deberían quedar marcados como propagados.
    od_con_pu = CargaOD(numero="3", titulo="prueba con PU", disidencia_parcial=("schiaretti-juan",))
    votacion_con_pu = Votacion(titulo=od_con_pu.titulo, eje="Económico/fiscal", od=od_con_pu)
    pred_con_pu = modelo.predecir(votacion_con_pu)
    assert pred_con_pu["capozzi-sergio-eduardo"].fuente_dominante == "propagado_od"


def test_armar_resultado_produce_desglose_y_ranking(modelo, evidencia):
    votacion = Votacion(titulo="prueba", eje="Comercio exterior")
    resultado = armar_resultado(modelo, votacion, evidencia)

    assert resultado.proyeccion_total.n_miembros == len(evidencia.universo_diputados())
    assert "La Libertad Avanza" in resultado.desglose_por_bloque
    # el ranking debe estar ordenado de banda más ancha a más angosta
    anchos = [p.ancho_banda for p in resultado.ranking_incertidumbre]
    assert anchos == sorted(anchos, reverse=True)
