with fuente as (

    select *
    from {{ source('mareas_raw', 'altura_marea_por_miembro') }}

)

select
    estacion,
    fecha,
    hora,
    ina_miembro,
    altura_valor,
    prono_id,
    corid,
    marca_temporal_carga
from fuente
-- mareas_cargar_bigquery carga append-only (no hay MERGE): antes de
-- cargar chequea que fecha+hora+ina_miembro no exista ya para la
-- estacion, asi que en uso normal esto no deberia encontrar
-- duplicados. Mismo motivo que stg_mareas_ina: sin MERGE ni ninguna
-- restriccion de base de datos, este qualify es la unica defensa para
-- que int_altura_marea_por_hora no promedie sobre un miembro repetido.
qualify row_number() over (
    partition by estacion, fecha, hora, ina_miembro
    order by marca_temporal_carga desc
) = 1
