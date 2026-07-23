-- San Fernando depende del modelo INA calId=432 ("regre_sfer"), que corre
-- a diario. Si el pronostico cargado tiene mas de 2 dias de atraso es un
-- problema real del pipeline y debe bloquear el DAG. (Rosario/Zarate no
-- se cargan a BigQuery, ver dbt_mareas/models/staging/sources.yml).

select
    estacion,
    max(fecha) as max_fecha,
    date_diff(current_date(), max(fecha), day) as dias_atraso
from {{ ref('mareas_por_estacion') }}
where estacion = 'san_fernando'
group by estacion
having date_diff(current_date(), max(fecha), day) > 2
