-- Cada estacion+fecha+hora del INA tiene que traer exactamente 5
-- lecturas (ina_miembro 0-4, ver
-- mareas/services/bigquery_export.py::assign_ina_miembros). Si viniera
-- con menos o mas, int_altura_marea_por_hora calcularia min/max/promedio
-- sobre un conjunto incompleto o inflado sin que nada lo marque - mejor
-- que falle aca.

select estacion, fecha, hora, count(*) as filas, count(distinct ina_miembro) as miembros_distintos
from {{ ref('stg_altura_marea_por_miembro') }}
group by estacion, fecha, hora
having count(*) != 5 or count(distinct ina_miembro) != 5
