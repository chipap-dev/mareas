-- San Fernando depende del modelo INA calId=432 ("regre_sfer"). Si la
-- marea cargada tiene mas de 72h de atraso es un problema real del
-- pipeline y debe bloquear el DAG. (Rosario/Zarate no se cargan a
-- BigQuery, ver dbt_mareas/models/staging/sources.yml).
--
-- Umbral de 72h = 48h de margen de asentamiento (ver docs/decisiones_
-- carga_incremental_bigquery.md, seccion 1) + 24h de margen operativo
-- por la cadencia del DAG. Se compara timestamp completo (fecha+hora),
-- no solo fecha, porque 72h no es un numero entero de dias.
--
-- Filtra "where altura_marea is not null" antes del max(): el mart
-- hace un full outer join entre marea (INA, con el margen de 48h) y
-- clima (SMN, que se carga sin esperar y llega hasta hoy+4 dias - ver
-- bigquery_export.py). Si se midiera el max(fecha) de todo el mart sin
-- este filtro, el lado SMN mantendria la fecha "fresca" aunque la
-- carga de marea se rompiera del todo, y el test quedaria en verde sin
-- medir lo que dice medir.

select
    estacion,
    max(timestamp(datetime(fecha, hora))) as ultima_marea,
    timestamp_diff(current_timestamp(), max(timestamp(datetime(fecha, hora))), hour) as horas_atraso
from {{ ref('mareas_por_estacion') }}
where estacion = 'san_fernando' and altura_marea is not null
group by estacion
having timestamp_diff(current_timestamp(), max(timestamp(datetime(fecha, hora))), hour) > 72
