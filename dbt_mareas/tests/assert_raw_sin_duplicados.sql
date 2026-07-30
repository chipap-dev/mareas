-- A diferencia de assert_staging_sin_duplicados (que mide *despues*
-- de que el qualify de staging ya dedupeo), este test corre contra la
-- fuente cruda. Sin MERGE ni ninguna restriccion de base de datos, la
-- unica garantia de unicidad es el chequeo de "ya existe" que hace
-- mareas_cargar_bigquery antes de cada load_table_from_json. Si ese
-- chequeo tuviera un bug y cargara la misma clave en cada corrida, el
-- qualify de staging lo taparia para siempre sin que nada lo marque -
-- este test es lo que lo haria fallar de forma visible.

with lecturas as (

    select estacion, fecha, hora, fuente_origen, count(*) as filas
    from {{ source('mareas_raw', 'lecturas') }}
    group by estacion, fecha, hora, fuente_origen
    having count(*) > 1

),

altura_miembro as (

    select estacion, fecha, hora, ina_miembro, count(*) as filas
    from {{ source('mareas_raw', 'altura_marea_por_miembro') }}
    group by estacion, fecha, hora, ina_miembro
    having count(*) > 1

)

select estacion, fecha, hora, fuente_origen as columna_extra, filas from lecturas
union all
select estacion, fecha, hora, cast(ina_miembro as string) as columna_extra, filas from altura_miembro
