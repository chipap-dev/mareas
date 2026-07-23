-- mareas_cargar_bigquery hace MERGE por estacion+fecha+hora+fuente_origen,
-- asi que el raw no deberia acumular duplicados en uso normal.
-- stg_mareas_ina y stg_mareas_smn igual dedupean con qualify
-- row_number() como red de seguridad (se quedan con la carga mas
-- reciente). Este test confirma que el dedup efectivamente deja una
-- sola fila por clave: si devuelve filas, mareas_por_estacion puede
-- estar haciendo fan-out en el full outer join.

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
