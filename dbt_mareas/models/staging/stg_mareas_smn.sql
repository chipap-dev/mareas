with fuente as (

    select *
    from {{ source('mareas_raw', 'lecturas') }}
    where fuente_origen = 'smn'

)

select
    estacion,
    fecha,
    hora,
    temperatura,
    viento_velocidad,
    viento_direccion,
    lluvia,
    marca_temporal_carga
from fuente
-- ver stg_mareas_ina.sql: mismo motivo, mismo dedup.
qualify row_number() over (
    partition by estacion, fecha, hora
    order by marca_temporal_carga desc
) = 1
