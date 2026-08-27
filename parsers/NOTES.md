# Notas del parser de PDF de actas (`acta_pdf_parser.py`)

## Rol: parser de respaldo, no vía principal

La vía principal para los votos de cada acta es el CSV que genera
votaciones.hcdn.gob.ar en el navegador (client-side, sin llamada de red).
Este parser de PDF existe para:

- Extraer metadata de cabecera (período, sesión, acta, fecha, tipo de
  mayoría, resultado, presidente) que el CSV del sitio no trae.
- Servir de último recurso para los votos si en algún caso puntual no se
  puede conseguir el CSV pero sí el PDF.

No usar este parser como fuente principal de votos: depende de que
pdfplumber pueda extraer la tabla via ruling lines del PDF, algo específico
del template actual de HCDN que puede cambiar sin aviso.

## Limitación de calidad de datos: cabecera vs. detalle no siempre reconcilian 1 a 1

Validado contra el acta id global 5995 (acta correlativo Nº 29, período
144° Ordinario, 5° Sesión Especial, 6° Reunión — O.D. 207 "Ley Joaquín",
27/08/2026):

- La cabecera del PDF informa: `Presentes: 220 votando + 1 sin votar = 221`,
  `Ausentes: 36` → total 257 (coincide con "Miembros del Cuerpo: 257").
- La tabla de detalle (por nombre) solo lista **256** personas: 220 con
  voto `AFIRMATIVO` + 36 `AUSENTE`.
- El diputado "presente pero sin votar" **no aparece identificado por
  nombre en ningún lado del PDF** — solo existe como conteo agregado en la
  cabecera.

Implicancia para el pipeline: no asumir que
`len(filas_de_detalle) == miembros_del_cuerpo`, ni que se puede reconstruir
la nómina completa de "presentes" a partir del detalle nominal. Si el
pipeline necesita conciliar cabecera vs. detalle, hay que tolerar este tipo
de diferencia (probablemente 0 o 1 persona, la que está presente sin
votar) en vez de tratarla como error de parseo.

`parse_acta_pdf()` en este módulo expone esto vía la clave `reconciliacion`
(`reconcilia_1_a_1: False` en este caso, con el detalle de conteos).

## Otro artefacto de PDF a tener en cuenta

El texto en negrita del PDF (título del acta, valores de resultado, etc.)
sale con cada carácter duplicado por superposición de glifos —
`"AAFFIIRRMMAATTIIVVOO"` en vez de `"AFIRMATIVO"`. `_dedupe_bold_line()`
lo revierte token por token (los espacios no se duplican). Si HCDN cambia
cómo generan el PDF, esta heurística podría dejar de aplicar y habría que
revisarla.
