-- mareas_cargar_bigquery carga append-only (sin MERGE): antes de
-- cargar consulta que estacion+fecha+hora+fuente_origen ya existe, asi
-- que el raw no deberia acumular duplicados en uso normal.
-- stg_mareas_ina y stg_mareas_smn igual dedupean con qualify
-- row_number() como unica red de seguridad restante (se quedan con la
-- carga mas reciente) - sin MERGE no hay ninguna restriccion de
-- unicidad a nivel de base de datos. Este test confirma que el dedup
-- efectivamente deja una sola fila por clave: si devuelve filas,
-- mareas_por_estacion puede estar haciendo fan-out en el full outer
-- join.

with ina as (

    select estacion, fecha, hora, count(*) as filas
    from {{ ref('stg_mareas_ina') }}
    group by estacion, fecha, hora
    having count(*) > 1

),

smn as (

    select estacion, fecha, hora, count(*) as filas
    from {{ ref('stg_mareas_smn') }}
    group by estacion, fecha, hora
    having count(*) > 1

)

select * from ina
union all
select * from smn
