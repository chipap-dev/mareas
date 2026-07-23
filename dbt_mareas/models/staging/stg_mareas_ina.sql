with fuente as (

    select *
    from {{ source('mareas_raw', 'lecturas') }}
    where fuente_origen = 'ina'

)

select
    estacion,
    fecha,
    hora,
    altura_marea,
    marca_temporal_carga
from fuente
-- mareas_cargar_bigquery hace MERGE por estacion+fecha+hora+fuente_origen,
-- asi que en uso normal esto no deberia encontrar duplicados. Se deja
-- como red de seguridad (por ejemplo, filas cargadas antes de este
-- MERGE) para que el join en mareas_por_estacion no pueda hacer fan-out.
qualify row_number() over (
    partition by estacion, fecha, hora
    order by marca_temporal_carga desc
) = 1
