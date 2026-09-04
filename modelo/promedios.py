#!/usr/bin/env python3
"""ModeloPromedios: versión 1 del motor de poroteo, por promedios
ponderados con shrinkage jerárquico a mano. Implementa ModeloPoroteo.

===========================================================================
FÓRMULA DE PONDERACIÓN (partial pooling a mano)
===========================================================================

Para cada legislador, se combinan tres niveles de evidencia histórica —
individual, subgrupo (cluster de ingesta/clustering_conflicto.py, corte
de 8), bloque — con shrinkage anidado tipo empirical Bayes: cada nivel se
"encoge" hacia el nivel inmediatamente más agregado en proporción a
cuánta evidencia propia tiene, usando una constante de shrinkage (una
pseudo-cuenta: cuántas observaciones "valen" el nivel más agregado).

    shrink(p, n, p_hacia, k) = (n * p + k * p_hacia) / (n + k)

Aplicado en cascada, de más agregado a más específico:

    p_bloque_eje      = shrink(p_bloque(eje),   n_bloque(eje),   p_bloque(general),   k_eje)
    p_subgrupo_eje    = shrink(p_subgrupo(eje), n_subgrupo(eje), p_bloque_eje,        k_eje)
    p_subgrupo_pooled = shrink(p_subgrupo_eje,  n_subgrupo,      p_bloque_eje,        k_bloque)
    p_individual_eje  = shrink(p_individual(eje), n_individual(eje), p_subgrupo_pooled, k_eje)
    p_final           = shrink(p_individual_eje, n_individual,   p_subgrupo_pooled,   k_sub)

Si el legislador no tiene subgrupo asignado (baja cobertura en el
clustering — Giordano, Matzkin), se salta el paso de subgrupo entero:

    p_final = shrink(p_individual_eje, n_individual, p_bloque_eje, k_bloque)
    (con p_individual_eje = shrink(p_individual(eje), n_individual(eje), p_bloque_eje, k_eje))

Los constantes (k_eje, k_bloque, k_sub) son parámetros del constructor,
no números mágicos en el código. Es el punto de apoyo conceptual para
migrar a PyMC: un modelo jerárquico bayesiano real estima estos mismos
"cuánto pesa cada nivel" a partir de la varianza de los datos en vez de
una constante fija a mano.

===========================================================================
EJE
===========================================================================

Si un bloque/subgrupo vota igual en todos los ejes, su tasa por-eje ya es
≈ igual a su tasa general y el shrinkage no cambia nada (LLA/UxP en la
mayoría de los ejes). Si un subgrupo SÍ es sensible al eje (los díscolos
de Provincias Unidas en económico/fiscal), su tasa por-eje difiere y eso
se propaga solo por la cascada — no hace falta un flag explícito de
"bloque sensible al eje".

===========================================================================
BANDA DE CONFIANZA (heurística v1, no un intervalo estadístico real)
===========================================================================

    ancho = min(ANCHO_MAXIMO, ANCHO_BASE / sqrt(1 + n_evidencia_efectiva)) * factor_volatilidad
    factor_volatilidad = 1.5 - cohesion_bloque   (si cohesion_bloque es None -> volatilidad máxima, factor=1.5)

Más evidencia efectiva -> banda más angosta. Bloque de cohesión baja (o
no calculable) -> banda más ancha ("impredecibles por arreglo"). Esto es
un placeholder explícitamente heurístico — con PyMC esto se reemplaza
por un intervalo de credibilidad real de la posterior.

===========================================================================
MODO CON OD: anclaje + propagación
===========================================================================

Firmantes anclan su propia probabilidad_afirmativo a un valor fijo según
tipo (ver constantes ancla_* del constructor), con banda angosta fija
(evidencia directa, no inferida).

Propagación al resto del bloque: para cada bloque con firmantes, se
calcula una señal = promedio ponderado de (ancla_firmante - p_baseline_firmante)
sobre los firmantes de ese bloque (p_baseline = lo que el modelo ya
esperaba de ellos ANTES de aplicar anclas). Esa señal se suma a los NO
firmantes del mismo bloque, con fuerza:

    fuerza = cohesion_bloque * (n_firmantes_del_bloque / n_miembros_del_bloque)

(bloques fragmentados o con pocos firmantes propagan poco; bloques
cohesivos con muchos firmantes propagan casi entera la señal). La banda
de los no-firmantes propagados se angosta en proporción a `fuerza`
(1 - 0.5*fuerza), porque la señal del bloque es evidencia adicional.
"""

import math
from typing import Optional

from .datos_evidencia import RepositorioEvidencia, TasaEvidencia
from .interfaz import ModeloPoroteo, PrediccionLegislador, Votacion

ANCHO_MAXIMO_BANDA = 0.9
ANCHO_BASE_BANDA = 1.3
ANCLA_BANDA_MEDIA = 0.02  # +/- alrededor del valor ancla para un firmante de OD


class ModeloPromedios(ModeloPoroteo):
    def __init__(
        self,
        evidencia: RepositorioEvidencia,
        k_eje: float = 3.0,
        k_bloque: float = 8.0,
        k_sub: float = 5.0,
        ancla_mayoria: float = 0.97,
        ancla_minoria: float = 0.03,
        ancla_disidencia_parcial: float = 0.75,
        ancla_disidencia_total: float = 0.25,
    ):
        """
        k_eje, k_bloque, k_sub: pseudo-cuentas de shrinkage (ver docstring
            del módulo). Más alto = se necesita más evidencia propia antes
            de confiar en el nivel más específico por sobre el más agregado.
        ancla_*: probabilidad a la que se fija un firmante de OD según el
            tipo de firma.
        """
        self.evidencia = evidencia
        self.k_eje = k_eje
        self.k_bloque = k_bloque
        self.k_sub = k_sub
        self.ancla_mayoria = ancla_mayoria
        self.ancla_minoria = ancla_minoria
        self.ancla_disidencia_parcial = ancla_disidencia_parcial
        self.ancla_disidencia_total = ancla_disidencia_total

    # ------------------------------------------------------------------
    # shrinkage
    # ------------------------------------------------------------------

    @staticmethod
    def _shrink(tasa: TasaEvidencia, hacia: float, k: float) -> float:
        return (tasa.n * tasa.probabilidad_afirmativo + k * hacia) / (tasa.n + k)

    def _propension_baseline(self, id_diputado: str, eje: Optional[str]):
        """Devuelve (p_final, n_evidencia_efectiva, fuente_dominante) —
        la cascada de shrinkage documentada arriba, SIN anclas de OD."""
        ev = self.evidencia
        bloque = ev.bloque_actual_de(id_diputado)
        subgrupo = ev.subgrupo_de(id_diputado)

        p_bloque_gen = ev.tasa_bloque(bloque, eje=None)
        if eje:
            p_bloque_eje_raw = ev.tasa_bloque(bloque, eje=eje)
            p_bloque_eje = self._shrink(p_bloque_eje_raw, p_bloque_gen.probabilidad_afirmativo, self.k_eje)
        else:
            p_bloque_eje = p_bloque_gen.probabilidad_afirmativo

        n_individual = ev.tasa_individual(id_diputado, eje=None).n

        if subgrupo is not None:
            tasa_sub_gen = ev.tasa_subgrupo(subgrupo, eje=None)
            if eje:
                tasa_sub_eje = ev.tasa_subgrupo(subgrupo, eje=eje)
                p_sub_eje = self._shrink(tasa_sub_eje, p_bloque_eje, self.k_eje)
            else:
                p_sub_eje = tasa_sub_gen.probabilidad_afirmativo
            p_sub_pooled = self._shrink(
                TasaEvidencia(p_sub_eje, tasa_sub_gen.n), p_bloque_eje, self.k_bloque
            )
            p_hacia_individual = p_sub_pooled
            k_final = self.k_sub
            fuente_agregada = "subgrupo"
        else:
            p_hacia_individual = p_bloque_eje
            k_final = self.k_bloque
            fuente_agregada = "bloque"

        tasa_ind_gen = ev.tasa_individual(id_diputado, eje=None)
        if eje:
            tasa_ind_eje = ev.tasa_individual(id_diputado, eje=eje)
            p_ind_eje = self._shrink(tasa_ind_eje, p_hacia_individual, self.k_eje)
        else:
            p_ind_eje = tasa_ind_gen.probabilidad_afirmativo

        p_final = self._shrink(TasaEvidencia(p_ind_eje, n_individual), p_hacia_individual, k_final)

        n_evidencia_efectiva = n_individual + k_final
        fuente_dominante = "individual" if n_individual > k_final else fuente_agregada
        return p_final, n_evidencia_efectiva, fuente_dominante

    def _banda(self, n_evidencia_efectiva: float, bloque: str) -> tuple:
        cohesion = self.evidencia.cohesion_de_bloque(bloque)
        factor_volatilidad = 1.5 - cohesion if cohesion is not None else 1.5
        ancho = min(
            ANCHO_MAXIMO_BANDA,
            (ANCHO_BASE_BANDA / math.sqrt(1 + n_evidencia_efectiva)) * factor_volatilidad,
        )
        return ancho

    def _predicciones_baseline(self, votacion: Votacion) -> dict:
        predicciones = {}
        for id_ in self.evidencia.universo_diputados():
            p, n_ef, fuente = self._propension_baseline(id_, votacion.eje)
            bloque = self.evidencia.bloque_actual_de(id_)
            ancho = self._banda(n_ef, bloque)
            low = max(0.0, p - ancho / 2)
            high = min(1.0, p + ancho / 2)
            predicciones[id_] = PrediccionLegislador(
                id_diputado=id_,
                probabilidad_afirmativo=round(p, 4),
                banda_confianza=(round(low, 4), round(high, 4)),
                n_evidencia_efectiva=round(n_ef, 2),
                fuente_dominante=fuente,
            )
        return predicciones

    # ------------------------------------------------------------------
    # modo con OD: anclaje + propagación
    # ------------------------------------------------------------------

    def _ancla_de_tipo(self, tipo: str) -> float:
        return {
            "mayoria": self.ancla_mayoria,
            "minoria": self.ancla_minoria,
            "disidencia_parcial": self.ancla_disidencia_parcial,
            "disidencia_total": self.ancla_disidencia_total,
        }[tipo]

    def _aplicar_od(self, predicciones: dict, votacion: Votacion) -> dict:
        od = votacion.od
        firmantes_por_tipo = {
            "mayoria": od.mayoria,
            "minoria": od.minoria,
            "disidencia_parcial": od.disidencia_parcial,
            "disidencia_total": od.disidencia_total,
        }
        firmantes_ids = {id_ for ids in firmantes_por_tipo.values() for id_ in ids}

        p_baseline = {id_: pred.probabilidad_afirmativo for id_, pred in predicciones.items()}

        resultado = dict(predicciones)

        # 1) anclar a los firmantes
        for tipo, ids in firmantes_por_tipo.items():
            ancla = self._ancla_de_tipo(tipo)
            for id_ in ids:
                if id_ not in resultado:
                    continue  # firmante fuera del universo de predicción (no en banca actual)
                resultado[id_] = PrediccionLegislador(
                    id_diputado=id_,
                    probabilidad_afirmativo=ancla,
                    banda_confianza=(
                        max(0.0, ancla - ANCLA_BANDA_MEDIA),
                        min(1.0, ancla + ANCLA_BANDA_MEDIA),
                    ),
                    n_evidencia_efectiva=predicciones[id_].n_evidencia_efectiva,
                    fuente_dominante="ancla_od",
                )

        # 2) señal por bloque: promedio de (ancla - p_baseline) entre firmantes de ese bloque
        señal_por_bloque = {}
        firmantes_por_bloque = {}
        for id_ in firmantes_ids:
            if id_ not in p_baseline:
                continue
            bloque = self.evidencia.bloque_actual_de(id_)
            firmantes_por_bloque.setdefault(bloque, []).append(id_)

        for bloque, ids in firmantes_por_bloque.items():
            deltas = [resultado[id_].probabilidad_afirmativo - p_baseline[id_] for id_ in ids]
            señal_por_bloque[bloque] = sum(deltas) / len(deltas)

        # 3) propagar a los NO firmantes de cada bloque con firmantes
        for bloque, señal in señal_por_bloque.items():
            miembros = self.evidencia.miembros_de_bloque(bloque)
            n_miembros = len(miembros) or 1
            n_firmantes = len(firmantes_por_bloque[bloque])
            cohesion = self.evidencia.cohesion_de_bloque(bloque) or 0.0
            fuerza = cohesion * (n_firmantes / n_miembros)

            for id_ in miembros:
                if id_ in firmantes_ids or id_ not in resultado:
                    continue
                base = resultado[id_]
                p_nuevo = min(1.0, max(0.0, base.probabilidad_afirmativo + fuerza * señal))
                ancho_previo = base.banda_confianza[1] - base.banda_confianza[0]
                ancho_nuevo = ancho_previo * (1 - 0.5 * fuerza)
                low = max(0.0, p_nuevo - ancho_nuevo / 2)
                high = min(1.0, p_nuevo + ancho_nuevo / 2)
                resultado[id_] = PrediccionLegislador(
                    id_diputado=id_,
                    probabilidad_afirmativo=round(p_nuevo, 4),
                    banda_confianza=(round(low, 4), round(high, 4)),
                    n_evidencia_efectiva=base.n_evidencia_efectiva,
                    fuente_dominante="propagado_od" if fuerza > 0 else base.fuente_dominante,
                )

        return resultado

    # ------------------------------------------------------------------
    # interfaz
    # ------------------------------------------------------------------

    def predecir(self, votacion: Votacion) -> dict:
        predicciones = self._predicciones_baseline(votacion)
        if votacion.od is not None:
            predicciones = self._aplicar_od(predicciones, votacion)
        return predicciones
