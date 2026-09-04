#!/usr/bin/env python3
"""Orquestador del poroteo: arma la salida agregada a partir de las
predicciones de UN modelo (cualquiera que cumpla ModeloPoroteo).

Punto de prueba de la separación interfaz/implementación pedida: este
módulo importa ModeloPoroteo (la interfaz) y RepositorioEvidencia (datos),
pero NUNCA ModeloPromedios ni ninguna implementación concreta. Cambiar de
motor es instanciar otra clase antes de llamar a armar_resultado() — este
archivo no cambia.
"""

from dataclasses import dataclass
from typing import Optional

from .datos_evidencia import RepositorioEvidencia
from .interfaz import ModeloPoroteo, PrediccionLegislador, Votacion


@dataclass(frozen=True)
class ProyeccionConteo:
    afirmativos_esperados: float
    negativos_esperados: float
    rango_afirmativos: tuple  # (low, high)
    n_miembros: int


@dataclass(frozen=True)
class ResultadoPoroteo:
    votacion: Votacion
    predicciones: dict                       # id_diputado -> PrediccionLegislador
    proyeccion_total: ProyeccionConteo
    desglose_por_bloque: dict                # bloque -> ProyeccionConteo
    ranking_incertidumbre: list              # PrediccionLegislador, de banda más ancha a más angosta


def _proyeccion_de(predicciones) -> ProyeccionConteo:
    afirmativos = sum(p.probabilidad_afirmativo for p in predicciones)
    negativos = len(predicciones) - afirmativos
    low = sum(p.banda_confianza[0] for p in predicciones)
    high = sum(p.banda_confianza[1] for p in predicciones)
    return ProyeccionConteo(
        afirmativos_esperados=round(afirmativos, 1),
        negativos_esperados=round(negativos, 1),
        rango_afirmativos=(round(low, 1), round(high, 1)),
        n_miembros=len(predicciones),
    )


def armar_resultado(
    modelo: ModeloPoroteo, votacion: Votacion, evidencia: RepositorioEvidencia
) -> ResultadoPoroteo:
    """Le pide las predicciones al `modelo` (la interfaz — no sabe ni le
    importa cuál implementación es) y arma la salida agregada."""
    predicciones = modelo.predecir(votacion)

    proyeccion_total = _proyeccion_de(list(predicciones.values()))

    por_bloque_ids = {}
    for id_, pred in predicciones.items():
        bloque = evidencia.bloque_actual_de(id_)
        por_bloque_ids.setdefault(bloque, []).append(pred)
    desglose_por_bloque = {
        bloque: _proyeccion_de(preds) for bloque, preds in por_bloque_ids.items()
    }

    ranking_incertidumbre = sorted(
        predicciones.values(), key=lambda p: p.ancho_banda, reverse=True
    )

    return ResultadoPoroteo(
        votacion=votacion,
        predicciones=predicciones,
        proyeccion_total=proyeccion_total,
        desglose_por_bloque=desglose_por_bloque,
        ranking_incertidumbre=ranking_incertidumbre,
    )


def formatear_texto(
    resultado: ResultadoPoroteo, evidencia: RepositorioEvidencia, top_incertidumbre: int = 15
) -> str:
    """Salida legible en texto plano: proyección total, desglose por
    bloque, y el top N de legisladores por incertidumbre ("andá a hablar
    con estos")."""
    lineas = []
    v = resultado.votacion
    lineas.append(f"=== Poroteo: {v.titulo} ===")
    if v.eje:
        lineas.append(f"Eje: {v.eje}")
    if v.od:
        lineas.append(f"OD {v.od.numero} — firmantes: "
                       f"{len(v.od.mayoria)} mayoría, {len(v.od.minoria)} minoría, "
                       f"{len(v.od.disidencia_parcial)} disid. parcial, {len(v.od.disidencia_total)} disid. total")
    lineas.append("")

    pt = resultado.proyeccion_total
    lineas.append(f"PROYECCIÓN TOTAL ({pt.n_miembros} diputados)")
    lineas.append(f"  Afirmativos esperados: {pt.afirmativos_esperados} "
                   f"(rango {pt.rango_afirmativos[0]}-{pt.rango_afirmativos[1]})")
    lineas.append(f"  Negativos esperados:   {pt.negativos_esperados}")
    lineas.append("")

    lineas.append("DESGLOSE POR BLOQUE")
    for bloque, p in sorted(resultado.desglose_por_bloque.items(), key=lambda kv: -kv[1].n_miembros):
        lineas.append(f"  {bloque:<65} {p.afirmativos_esperados:>6.1f}/{p.n_miembros:<4} "
                       f"afirm. esperados (rango {p.rango_afirmativos[0]}-{p.rango_afirmativos[1]})")
    lineas.append("")

    lineas.append(f"TOP {top_incertidumbre} POR INCERTIDUMBRE (banda más ancha primero — \"andá a hablar con estos\")")
    for pred in resultado.ranking_incertidumbre[:top_incertidumbre]:
        nombre = evidencia.nombre_de(pred.id_diputado)
        bloque = evidencia.bloque_actual_de(pred.id_diputado)
        lineas.append(
            f"  {nombre:<35} [{bloque:<45}] p={pred.probabilidad_afirmativo:.2f} "
            f"banda=({pred.banda_confianza[0]:.2f}-{pred.banda_confianza[1]:.2f}, "
            f"ancho={pred.ancho_banda:.2f}) fuente={pred.fuente_dominante} n_ef={pred.n_evidencia_efectiva:.1f}"
        )

    return "\n".join(lineas)
