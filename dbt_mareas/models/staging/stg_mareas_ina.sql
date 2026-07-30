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
-- mareas_cargar_bigquery carga append-only (no hay MERGE ni ninguna
-- restriccion de unicidad a nivel de base de datos): antes de cargar
-- chequea que fecha+hora+fuente_origen no exista ya para la estacion,
-- asi que en uso normal esto no deberia encontrar duplicados. A
-- diferencia de cuando existia MERGE, este qualify es la UNICA defensa
-- contra un duplicado en el raw - si el chequeo de "ya existe" tuviera
-- un bug, esto es lo unico que evita que el join en mareas_por_estacion
-- haga fan-out. Ver tambien el test de unicidad contra la fuente cruda
-- (assert_raw_lecturas_sin_duplicados).
qualify row_number() over (
    partition by estacion, fecha, hora
    order by marca_temporal_carga desc
) = 1
