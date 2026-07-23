with ina as (

    select * from {{ ref('stg_mareas_ina') }}

),

smn as (

    select * from {{ ref('stg_mareas_smn') }}

)

select
    coalesce(ina.estacion, smn.estacion) as estacion,
    coalesce(ina.fecha, smn.fecha) as fecha,
    coalesce(ina.hora, smn.hora) as hora,
    ina.altura_marea,
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
