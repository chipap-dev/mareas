with altura_sql as (

    select * from {{ ref('int_altura_marea_por_hora') }}

),

altura_python as (

    select
        estacion,
        fecha,
        hora,
        altura_marea as altura_promedio,
        marca_temporal_carga
    from {{ ref('stg_mareas_ina') }}

),

-- Coalesce de dos fuentes de altura de marea.
--
-- Historia de este modelo (para entender por que existen dos ramas en
-- vez de una): hasta la migracion a carga append-only (ver
-- docs/decisiones_carga_incremental_bigquery.md), altura_python traia
-- todo lo anterior a un "T0" y altura_sql todo lo posterior, sin
-- superposicion - mareas_raw.lecturas se cargaba con MERGE desde el
-- cache local, mareas_raw.altura_marea_por_miembro no existia antes de
-- ese T0. Esa carga vieja se descarto por completo (DROP TABLE, ver
-- decisiones seccion 3): ambas tablas arrancan vacias desde el mismo
-- dia, y mareas_cargar_bigquery ahora puebla las dos con el mismo
-- fetch al INA (una sola consulta, reusada - ver
-- mareas_cargar_bigquery.py) y el mismo filtro de asentamiento de 48h.
-- Consecuencia: de aca en adelante altura_sql y altura_python van a
-- tener exactamente la misma cobertura de fecha+hora, no complementaria
-- como antes - el full outer join ya no hace falta para "completar
-- huecos" entre las dos, pero se mantiene por robustez (si algun dia
-- una de las dos cargas fallara sola, la otra sigue cubriendo).
--
-- altura_sql (int_altura_marea_por_hora, sobre
-- mareas_raw.altura_marea_por_miembro) trae altura_minima y
-- altura_maxima ademas del promedio, calculadas en SQL sobre las 5
-- lecturas crudas del INA; altura_python (stg_mareas_ina, sobre
-- mareas_raw.lecturas) solo trae el promedio. El coalesce prioriza
-- altura_sql cuando esta presente (trae min/max); en la practica, con
-- las dos cargas en lockstep, deberia estarlo siempre salvo que una de
-- las dos cargas haya fallado en una corrida puntual.
ina as (

    select
        coalesce(altura_sql.estacion, altura_python.estacion) as estacion,
        coalesce(altura_sql.fecha, altura_python.fecha) as fecha,
        coalesce(altura_sql.hora, altura_python.hora) as hora,
        altura_sql.altura_minima,
        altura_sql.altura_maxima,
        coalesce(altura_sql.altura_promedio, altura_python.altura_promedio) as altura_promedio,
        greatest(
            coalesce(altura_sql.marca_temporal_carga, timestamp('1970-01-01')),
            coalesce(altura_python.marca_temporal_carga, timestamp('1970-01-01'))
        ) as marca_temporal_carga
    from altura_sql
    full outer join altura_python
        on altura_sql.estacion = altura_python.estacion
        and altura_sql.fecha = altura_python.fecha
        and altura_sql.hora = altura_python.hora

),

smn as (

    select * from {{ ref('stg_mareas_smn') }}

)

select
    coalesce(ina.estacion, smn.estacion) as estacion,
    coalesce(ina.fecha, smn.fecha) as fecha,
    coalesce(ina.hora, smn.hora) as hora,
    ina.altura_minima,
    ina.altura_maxima,
    ina.altura_promedio as altura_marea,
    smn.temperatura,
    smn.viento_velocidad,
    smn.viento_direccion,
    smn.lluvia,
    greatest(
        coalesce(ina.marca_temporal_carga, timestamp('1970-01-01')),
        coalesce(smn.marca_temporal_carga, timestamp('1970-01-01'))
    ) as marca_temporal_carga
from ina
full outer join smn
    on ina.estacion = smn.estacion
    and ina.fecha = smn.fecha
    and ina.hora = smn.hora
