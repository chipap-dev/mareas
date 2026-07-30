# Decisiones: carga incremental a BigQuery sin DML

Registro de las decisiones de diseño para reemplazar el MERGE (que nunca corrió
con éxito, por la restricción de DML del sandbox de BigQuery) por una carga
append-only. No es un changelog de código: es el motivo de cada decisión.

## 1. Margen de asentamiento: 48 horas

El INA no corre su modelo una vez por día como se asumía. Se detectaron dos
corridas distintas con 12 minutos de diferencia (2026-07-23, entre 00:30:37 y
00:42:36), y en ese lapso los valores de horas ya pasadas (hasta ~9-10h de
antigüedad al momento de la corrida) cambiaron. Horas con más de ~10h de
antigüedad no se movieron entre esas mismas corridas, y una fecha de casi un
mes de antigüedad no mostró ninguna deriva.

**Decisión**: cargar a `mareas_raw` solo `(fecha, hora)` con más de 48 horas de
antigüedad respecto al momento de la corrida. Dos veces el margen observado
donde se vio actividad, para no depender de una sola muestra de 12 minutos.

**Cómo se verificó**: comparando 4 cargas históricas reales de la versión
vieja sin commitear (`mareas_raw.lecturas`, cargas del 22 y 23 de julio de
2026) más dos consultas en vivo al INA separadas por segundos (corid y valores
idénticos, como se esperaba para una ventana tan corta).

## 2. La expiración de 60 días del sandbox es una restricción dura, no un default

Se probó explícitamente (no se asumió) si se podía quitar la expiración de 60
días que el sandbox de BigQuery impone a nivel dataset (`defaultTableExpirationMs`
= 5184000000 ms = 60 días, ya heredado por `lecturas` y `altura_marea_por_miembro`
en el momento de su creación).

**Prueba 1 (SQL, `ALTER TABLE ... SET OPTIONS(expiration_timestamp = NULL)`)**:
el job falla con `Table expiration time must be less than 60 days while in
sandbox mode`, pero como efecto secundario deja la tabla en un estado
inconsistente (sin expiración visible en los metadatos, pero también sin poder
correr después ni `ALTER` ni `DROP` sobre esa misma tabla vía query job — hubo
que borrarla con `bq rm -t`, que usa la API de tablas directa, no un query
job). No hay que confiar en este comportamiento: es un efecto colateral de un
job que la propia plataforma reporta como rechazado, no una vía soportada.

**Prueba 2 (cliente Python `google.cloud.bigquery`, el mecanismo real que usa
el código de producción)**: `update_table(expires=None)` lanza una excepción
real (403, mismo mensaje) y esta vez la tabla queda completamente intacta (sin
mutación parcial) — comportamiento limpio y confiable. Confirma que **no se
puede eliminar la expiración**, es una restricción real del sandbox.

**Prueba 3**: `update_table(expires=<fecha < 60 días desde ahora>)` y
`create_table(..., expires=<fecha < 60 días desde ahora>)` funcionan sin error,
de forma limpia y reproducible, tanto al crear la tabla como al actualizarla
después.

**Corrección (post-verificación)**: se planteó inicialmente renovar la
expiración cada corrida para tener historia permanente. El usuario aclaró que
nunca necesitó retención permanente — 60 días de historia real le alcanza. Se
descarta todo el plan de renovación.

**Decisión final**: se acepta la expiración de 60 días tal como viene por
default del dataset. No se toca, no se renueva, no se hace ningún manejo
especial de `expires` en el código. Sigue habiendo acumulación real de valor:
la ventana del INA es de ~14 días hacia atrás (ver sección 1), así que 60 días
de historia en BigQuery es más de 4 veces esa ventana — información que ya no
se puede reconstruir consultando al INA de nuevo si se perdiera.

**Límite real a documentar (distinto del de BigQuery)**: si el pipeline deja
de correr por más de ~12 días (ventana del INA de ~14 días menos el margen de
asentamiento de 48h), los datos de esos días quedan fuera de la ventana del
INA antes de poder cargarlos alguna vez — se pierden para siempre, sin que
tenga nada que ver con la expiración de BigQuery. Es la motivación real detrás
de la pregunta aparte sobre cómo hacer que el DAG corra solo.

## 3. Las 1067 filas existentes — pendiente de confirmación final

Caracterización de lo que hay hoy en `mareas_raw.lecturas` (296 claves
estacion+fecha+hora de origen INA, 101 de origen SMN, todo San Fernando):

| | INA | SMN |
|---|---|---|
| Claves con más de 1 fila (múltiples cargas) | 191 / 296 (65%) | 97 / 101 (96%) |
| Claves con valores en conflicto real entre cargas | 70 / 296 (24%) | n/a (no medido, esperable en pronóstico) |
| Claves ya con ≥48h de antigüedad en su última carga | 195 / 296 (66%) | 0 / 101 (0%) |
| Claves con <48h de antigüedad en su última carga | 101 / 296 (34%) | 101 / 101 (100%) |

Interpretación: no es basura homogénea. El 66% de las claves INA tiene, en su
última carga conocida, un valor capturado después de que nuestro propio
criterio de 48h lo habría considerado seguro — pero eso no prueba que sea el
valor final real: el experimento simplemente dejó de re-consultar en algún
punto no verificable, así que no hay confirmación de que esa "última versión"
no habría cambiado en una corrida posterior que nunca se hizo. El 24% muestra
conflicto de valores explícito entre cargas — evidencia directa de que esos
números todavía se estaban moviendo. Del lado SMN, el 100% de las claves son
inherentemente de corto plazo (pronóstico rodante), consistente con que el SMN
no tiene ventana de "asentamiento" (ver sección 5).

**Decisión final (confirmada)**: `DROP TABLE` de `lecturas` y de
`altura_marea_por_miembro`, recrear ambas vacías. Empezamos de hoy. Se pierde
ese mes de historia — irrecuperable, la ventana del INA ya dejó atrás las
fechas más viejas (probado: 2026-06-28 ya no está disponible en el INA desde
hoy). A cambio, las tablas arrancan con la garantía de unicidad intacta desde
el día uno, sin mezclar valores de origen incierto con los nuevos.

## 4. Asimetría INA / SMN dentro de `lecturas` (consecuencia buscada)

`lecturas` combina dos fuentes con comportamiento opuesto:

- **INA (marea)**: espera 48h antes de cargar, porque el valor puede seguir
  moviéndose mientras está fresco (ver sección 1).
- **SMN (clima)**: se carga apenas aparece en el pronóstico diario, sin
  esperar nada — no existe un endpoint de SMN para volver a preguntar por una
  fecha pasada, así que no hay nada que "esperar a que se asiente"; es una
  foto del pronóstico, no una observación que se corrige.

**Consecuencia visible en el mart** (`mareas_por_estacion`, `full outer join`
entre `ina` y `smn`): las horas de las últimas 48h van a tener clima sin
marea (`altura_marea` NULL, `temperatura`/`viento`/`lluvia` con dato). Es
esperado, no un bug — hay que documentarlo en `schema.yml` del mart para que
no se lea como una falla de carga.

## 5. Test `assert_san_fernando_pronostico_reciente` — necesita reescritura, no solo el umbral

El test actual mide `max(fecha)` de todo el mart y falla si tiene más de 2
días de atraso respecto a `current_date()`. La intención original (ver su
comentario) es detectar si el modelo INA (calId=432) dejó de actualizarse.

Con el diseño de 48h, el análisis es más sutil que "va a fallar siempre":
como `mareas_por_estacion.fecha` sale de un `coalesce(ina.fecha, smn.fecha)`
sobre un `full outer join`, y SMN sigue trayendo fechas de hoy hasta +3/+4
días (pronóstico rodante, sección 4), el `max(fecha)` de todo el mart se va a
seguir viendo "fresco" por el lado del clima **aunque la carga de marea se
rompa por completo**. El test no va a fallar — va a seguir pasando en verde,
pero dejando de medir lo que dice medir (la frescura de la marea/INA, no del
clima). Eso es peor que un test que falla: dejaría de detectar justo el
problema para el que se escribió.

**Decisión final (confirmada)**: reescrito para filtrar
`where altura_marea is not null` antes de tomar el `max` de fecha+hora —
aislando el lado INA del lado SMN — con umbral de **72 horas** (48h de margen
de asentamiento + 24h de margen operativo por cadencia del DAG). Se pasa a
comparar timestamp completo (fecha+hora), no solo fecha, porque 72h no es un
número entero de días.

## 6. `qualify row_number()` en staging — cambia de rol, no de forma

Se mantiene en `stg_mareas_ina` y `stg_altura_marea_por_miembro`, pero su
propósito cambia: antes era una red de seguridad que "en uso normal no
debería activarse nunca" (MERGE garantizaba unicidad en el raw). Ahora que no
hay MERGE ni ninguna restricción de base de datos, es la única defensa contra
un duplicado en el raw. Bajo el nuevo diseño, si algún duplicado se cuela va a
tener el mismo valor en todas las filas (porque solo se carga después de 48h
asentado) — a diferencia de las 1067 filas actuales, que tienen duplicados con
valores en conflicto real.

## 7. Test nuevo: unicidad a nivel raw, no solo en staging

Los tests existentes (`assert_staging_sin_duplicados`,
`assert_mareas_por_estacion_grano_unico`) verifican unicidad *después* de que
el `qualify` ya dedupeó. Ninguno corre contra `mareas_raw.lecturas` /
`altura_marea_por_miembro` directamente. Se propone agregar un test contra la
fuente cruda: si el chequeo de "¿ya existe?" en Python tuviera un bug y
cargara la misma `(fecha, hora)` en cada corrida, el `qualify` lo taparía para
siempre sin que nada lo marque. Un test a nivel fuente lo haría fallar de
forma visible.

## 8. Volumen: no es una restricción real a esta escala

Para 1 sola estación (San Fernando, todo lo que carga el DAG hoy):
- `lecturas`: ~50 filas/día → ~150 KB/mes.
- `altura_marea_por_miembro`: ~125 filas/día → ~375 KB/mes.
- Storage acumulado en años: decenas de MB, muy lejos del límite de 10 GiB.
- Bytes escaneados (chequeo de existencia + `dbt run`/`test`): fracción
  insignificante del 1 TiB/mes gratuito. No hace falta particionar ni
  clusterizar a este volumen.

## 9. Simplificación: se elimina toda la maquinaria de MERGE

Sin MERGE no hace falta tabla staging temporal, ni `_load_staging_table`, ni
`_merge_sql`, ni `_drop_staging_table`. El flujo pasa a ser: consultar qué
claves ya existen en la tabla destino, filtrar las filas nuevas candidatas
contra esas claves, y `load_table_from_json` directo al destino con
`WRITE_APPEND`. La consulta de "¿qué ya existe?" mantiene el mismo tope de
`maximum_bytes_billed` (200 MB) que tenía la query de MERGE, como la misma red
de seguridad de siempre.

## 10. Verificado: pedir una ventana hacia atrás más ancha que la real no rompe el fetch

Antes de escribir el fetch con ventana hacia atrás, se probó si pedirle al INA
un rango que arranca antes del borde real de su ventana (~14 días) hace fallar
toda la consulta o devuelve parcial. Se probó con `timeStart` 19 días atrás y
`timeEnd` hoy: devolvió 1685 filas, la primera fecha disponible siendo la que
correspondía al borde real de la ventana (~14 días atrás), sin error. Es
seguro pedir un margen generoso (20 días) sin preocuparse por acertar el borde
exacto día a día.

## 11. Consecuencia no prevista: altura_minima/altura_maxima ahora deberían estar siempre pobladas

Antes de este cambio, `mareas_por_estacion` tenía un split "T0": todo lo
anterior a que arrancara la carga de `altura_marea_por_miembro` solo tenía el
promedio (calculado en Python, sin min/max); todo lo posterior tenía min/max
(calculado en SQL). Al tirar ambas tablas y arrancarlas vacías el mismo día,
alimentadas del mismo fetch al INA en cada corrida, las dos ramas del
`coalesce` en `mareas_por_estacion.sql` van a tener exactamente la misma
cobertura de fecha+hora de ahora en más - `altura_minima`/`altura_maxima` ya
no deberían quedar NULL salvo que una de las dos cargas falle en una corrida
puntual. Documentado en `mareas_por_estacion.sql` y `schema.yml`.

## 12. Validación end-to-end (rama `feature/carga-incremental-append-only`)

- `python manage.py test mareas`: 13/13 tests OK.
- Corrida real contra el sandbox (`manage.py mareas_cargar_bigquery --station
  san_fernando`): 402 filas nuevas en `lecturas`, 1445 en
  `altura_marea_por_miembro`.
- Repetida inmediatamente después: 0 filas nuevas en ambas — confirma
  idempotencia.
- Verificado en BigQuery: cero duplicados por clave en ninguna de las dos
  tablas; última marea cargada con 51h de antigüedad (> 48h, como corresponde
  justo por encima del margen); SMN llega hasta la fecha de hoy (sin esperar).
- `dbt run` + `dbt test`: 5/5 modelos, 8/8 tests OK, incluyendo
  `assert_raw_sin_duplicados` (nuevo) y `assert_san_fernando_pronostico_reciente`
  reescrito con el umbral de 72h.

## Estado: todas las decisiones de diseño están aprobadas e implementadas en esta rama, validadas end-to-end contra el sandbox real.

Quedó un límite operativo real, fuera del alcance de este cambio de código: si
el pipeline deja de correr por más de ~12 días, se pierden datos para siempre
(ventana del INA, no expiración de BigQuery — ver sección 2). La pregunta de
cómo hacer que el DAG corra solo, sin depender de prender Docker a mano, se
resolvió aparte (ver conversación / README de `airflow_repo`).
