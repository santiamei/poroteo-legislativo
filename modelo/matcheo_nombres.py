#!/usr/bin/env python3
"""Matcheo tolerante de nombres pegados a mano (apellido solo, "A.
Apellido", "Nombre Apellido", apellido compuesto) contra la tabla de
nombres canónicos del repositorio de evidencia.

No fuerza nada: si una consulta matchea 0 o más de 1 persona, queda
listada aparte para que quien cargó la OD decida — nunca se adivina.

Usado por app.py para los 4 textareas del modo con OD.
"""

import re
import unicodedata
from dataclasses import dataclass


def _normalizar(s: str) -> str:
    s = s.upper()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(s: str) -> set:
    s = _normalizar(s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return {t for t in s.split() if t}


@dataclass(frozen=True)
class Candidato:
    id_diputado: str
    nombre_canonico: str


@dataclass(frozen=True)
class ResultadoMatcheo:
    matcheados: dict      # {texto_pegado: id_diputado}
    sin_match: list       # [texto_pegado, ...]
    ambiguos: dict        # {texto_pegado: [Candidato, ...]}

    @property
    def ids(self) -> tuple:
        """Los id_diputado matcheados, listos para una lista de CargaOD."""
        return tuple(self.matcheados.values())

    @property
    def hay_problemas(self) -> bool:
        return bool(self.sin_match or self.ambiguos)


def _candidatos_para(consulta: str, tabla_nombres: dict) -> list:
    """tabla_nombres: {id_diputado: nombre_canonico}, ya scopeada al
    universo que corresponda (en la app, los 257 actuales)."""
    consulta = consulta.strip()
    if not consulta:
        return []

    inicial = None
    m = re.match(r"^([A-Za-zÁÉÍÓÚÑáéíóúñ])\.\s+(.+)$", consulta)
    if m:
        inicial = _normalizar(m.group(1))
        resto = m.group(2)
    else:
        resto = consulta

    # Los tokens de una sola letra (iniciales de segundo nombre, ej. la "G"
    # de "María G. Flores") nunca aparecen como token suelto en el nombre
    # canónico ("MARIA GABRIELA") y rompían el match por subconjunto. Se
    # descartan acá; la inicial PRINCIPAL ("A." al inicio) ya se maneja
    # aparte, más abajo, solo para desambiguar entre candidatos.
    tks = {t for t in _tokens(resto) if len(t) > 1}
    if not tks:
        return []

    candidatos = [
        Candidato(id_, nombre)
        for id_, nombre in tabla_nombres.items()
        if tks <= _tokens(nombre)
    ]

    if inicial and len(candidatos) > 1:
        partes_nombre = lambda nombre: nombre.split(",", 1)[1].strip() if "," in nombre else nombre
        filtrados = [
            c for c in candidatos
            if partes_nombre(c.nombre_canonico) and _normalizar(partes_nombre(c.nombre_canonico))[0] == inicial
        ]
        if filtrados:
            candidatos = filtrados

    return candidatos


def matchear_nombres(lineas, tabla_nombres: dict) -> ResultadoMatcheo:
    """lineas: iterable de strings (una consulta por línea, típicamente
    de un textarea pegado a mano — líneas vacías se ignoran).
    tabla_nombres: {id_diputado: nombre_canonico} del universo a buscar.
    """
    matcheados = {}
    sin_match = []
    ambiguos = {}

    for linea in lineas:
        texto = linea.strip()
        if not texto:
            continue
        candidatos = _candidatos_para(texto, tabla_nombres)
        if len(candidatos) == 1:
            matcheados[texto] = candidatos[0].id_diputado
        elif len(candidatos) == 0:
            sin_match.append(texto)
        else:
            ambiguos[texto] = candidatos

    return ResultadoMatcheo(matcheados=matcheados, sin_match=sin_match, ambiguos=ambiguos)
