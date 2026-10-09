#!/usr/bin/env python3
"""Capa visual de la app (Etapa 4): escala de color de voto, color/orden
de bloques, comentario en lenguaje claro por diputado, y el armado del
JSON que consume plantilla_resultado.html (el hemiciclo ahora lo dibuja
esa plantilla en JS, no Python — ver construir_datos_resultado). NO toca
el modelo ni la lógica de selección de tema — solo los lee y los traduce
a algo visual.

Separado de app.py para que el archivo de la UI no se llene de lógica de
armado de datos; nada de acá importa pdfplumber, ModeloPromedios ni
RepositorioEvidencia por su nombre concreto (solo usa la interfaz que
expone: bloque_actual_de, cohesion_de_bloque, nombre_de, etc.).
"""

from collections import Counter
from pathlib import Path
from typing import Optional

import yaml

BASE_DIR = Path(__file__).parent
COLORES_BLOQUES_PATH = BASE_DIR / "colores_bloques.yaml"
ESCALA_VOTO_PATH = BASE_DIR / "escala_voto.yaml"

MAYORIA_ABSOLUTA = 129  # mitad + 1 de 257 bancas


def cargar_colores_bloques(path=COLORES_BLOQUES_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def cargar_escala_voto(path=ESCALA_VOTO_PATH) -> list:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    categorias = data.get("categorias", [])
    return sorted(categorias, key=lambda c: -c["minimo"])


def color_de_bloque(bloque: str, colores_bloques: dict) -> str:
    info = colores_bloques.get(bloque, colores_bloques.get("_default", {}))
    return info.get("color", "#9E9E9E")


def orden_de_bloque(bloque: str, colores_bloques: dict) -> float:
    info = colores_bloques.get(bloque, colores_bloques.get("_default", {}))
    return info.get("orden", 11)


def categoria_voto(probabilidad: float, escala_voto: list) -> dict:
    """La primera categoría (de mayor a menor umbral) cuyo mínimo alcanza
    la probabilidad. escala_voto ya viene ordenada por cargar_escala_voto."""
    for cat in escala_voto:
        if probabilidad >= cat["minimo"]:
            return cat
    return escala_voto[-1]  # red de seguridad: no debería pasar si minimo=0.0 está presente


def comentario_para(id_diputado: str, prediccion, evidencia, od=None) -> str:
    """Una frase corta en lenguaje claro de POR QUÉ el modelo dice lo que
    dice, derivada de datos reales que el modelo ya devuelve
    (fuente_dominante, y si firmó la OD cargada) — nunca inventada."""
    if od is not None:
        if id_diputado in od.mayoria:
            return "Firmó el dictamen de mayoría: su voto queda anclado directamente a esa firma."
        if id_diputado in od.minoria:
            return "Firmó el dictamen de minoría: su voto queda anclado directamente a esa firma."
        if id_diputado in od.disidencia_parcial:
            return "Firmó en disidencia parcial: acompaña en general, pero marcando diferencias."
        if id_diputado in od.disidencia_total:
            return "Firmó en disidencia total: se espera que rechace el proyecto."

    bloque = evidencia.bloque_actual_de(id_diputado)
    cohesion = evidencia.cohesion_de_bloque(bloque)
    fuente = prediccion.fuente_dominante

    if fuente == "propagado_od":
        return f"No firmó la OD, pero el modelo ajusta su voto por la señal de quienes sí firmaron en {bloque}."
    if fuente == "individual":
        return "Tiene historial propio suficiente: la proyección se apoya sobre todo en su propio comportamiento de voto."
    if fuente == "subgrupo":
        if cohesion is not None and cohesion >= 0.8:
            return f"Poca historia propia todavía: se estima por cómo vota su subgrupo dentro de {bloque}, que es disciplinado."
        return f"Poca historia propia todavía: se estima por cómo vota su subgrupo dentro de {bloque}."
    if fuente == "bloque":
        if cohesion is not None and cohesion >= 0.85:
            return f"Poca historia propia: se estima directamente por {bloque}, que vota muy parejo."
        if cohesion is not None and cohesion < 0.5:
            return f"Poca historia propia: se estima por {bloque}, pero ese bloque se divide seguido — tomalo con pinzas."
        return f"Poca historia propia todavía: se estima directamente por el comportamiento de {bloque}."
    if fuente == "ancla_od":
        return "Ancló su voto por firmar la OD cargada."
    return "Estimado a partir de su historial de votación."


# ---------------------------------------------------------------------------
# JSON para plantilla_resultado.html
# ---------------------------------------------------------------------------


def construir_datos_resultado(resultado, evidencia, resultado_parseo, colores_bloques, escala_voto, od_actual) -> dict:
    """Arma el dict que plantilla_resultado.html espera como `DATA`: cada
    diputado lleva ya resuelto color_categoria, color_bloque y orden (el
    hemiciclo y el ordenamiento "por bloque" los calcula el JS de la
    plantilla a partir de estos campos, no hace falta mandarle nada más).
    """
    diputados = []
    for id_diputado, pred in resultado.predicciones.items():
        bloque = evidencia.bloque_actual_de(id_diputado)
        cat = categoria_voto(pred.probabilidad_afirmativo, escala_voto)
        diputados.append(
            {
                "id_diputado": id_diputado,
                "nombre": evidencia.nombre_de(id_diputado),
                "bloque": bloque,
                "probabilidad_afirmativo": pred.probabilidad_afirmativo,
                "categoria_voto": cat["nombre"],
                "color_categoria": cat["color"],
                "comentario": comentario_para(id_diputado, pred, evidencia, od_actual),
                "color_bloque": color_de_bloque(bloque, colores_bloques),
                "orden": orden_de_bloque(bloque, colores_bloques),
            }
        )
    diputados.sort(key=lambda d: -d["probabilidad_afirmativo"])

    totales_por_categoria = Counter(d["categoria_voto"] for d in diputados)
    for cat in escala_voto:
        totales_por_categoria.setdefault(cat["nombre"], 0)

    pt = resultado.proyeccion_total
    colores_bloque_planos = {
        bloque: info.get("color", "#9E9E9E") for bloque, info in colores_bloques.items() if bloque != "_default"
    }

    return {
        "od": {
            "numero": resultado_parseo.numero_od,
            "titulo": resultado_parseo.titulo,
        },
        "resumen": {
            "afirmativos_esperados": pt.afirmativos_esperados,
            "negativos_esperados": pt.negativos_esperados,
            "rango_afirmativos": {"bajo": pt.rango_afirmativos[0], "alto": pt.rango_afirmativos[1]},
            "mayoria_absoluta": MAYORIA_ABSOLUTA,
            "supera_mayoria": pt.rango_afirmativos[0] >= MAYORIA_ABSOLUTA,
            "n_diputados": pt.n_miembros,
            "totales_por_categoria": dict(totales_por_categoria),
        },
        "diputados": diputados,
        "colores_bloque": colores_bloque_planos,
    }
