with miembros as (

    select * from {{ ref('stg_altura_marea_por_miembro') }}

)

select
    estacion,
    fecha,
    hora,
    min(altura_valor) as altura_minima,
    max(altura_valor) as altura_maxima,
    round(avg(altura_valor), 2) as altura_promedio,
    max(marca_temporal_carga) as marca_temporal_carga
from miembros
-- Cada grupo tiene que traer exactamente 5 miembros (ina_miembro 0-4)
-- - eso lo garantiza el test assert_altura_marea_por_miembro_cinco_por_hora,
-- no se re-chequea aca. round(avg(...), 2) NO replica el redondeo que
-- hacia Python en refresh.py::group_ina_rows - son modos distintos
-- (Python: half-to-even: BigQuery ROUND(): half-away-from-zero), asi
-- que en el borde exacto del centavo pueden diferir en un centavo. Se
-- redondea igual a 2 decimales para que la serie en mareas_por_estacion
-- no tenga un salto de precision visible en T0 (mas decimales de golpe
-- del lado que se sigue actualizando).
group by estacion, fecha, hora
