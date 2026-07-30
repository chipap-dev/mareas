-- El mart tiene que tener una sola fila por estacion+fecha+hora. Es
-- el riesgo concreto del coalesce que arma la altura de marea: si
-- int_altura_marea_por_hora dejara pasar mas de una fila por hora
-- (por ejemplo, si stg_altura_marea_por_miembro trajera mas o menos
-- de 5 miembros sin que assert_altura_marea_por_miembro_cinco_por_hora
-- lo atajara), el full outer join contra smn hace fan-out silencioso.

select estacion, fecha, hora, count(*) as filas
from {{ ref('mareas_por_estacion') }}
group by estacion, fecha, hora
having count(*) > 1
