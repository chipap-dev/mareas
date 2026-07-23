"""
Aplanado de las lecturas cacheadas para la carga incremental a BigQuery
(`mareas_raw.lecturas`). No es usado por la app Django para servir al
visitante - solo por el management command `mareas_cargar_bigquery`.

Cada registro del cache combina en una sola fila datos de marea (INA) y
clima (SMN). Acá se separan en dos filas por `fecha + hora`, una por
fuente, para que el layer crudo en BigQuery conserve la procedencia del
dato tal como llega el pipeline (`fuente_origen`).
"""

TABLE_SCHEMA_FIELDS = [
    ("estacion", "STRING"),
    ("fecha", "DATE"),
    ("hora", "TIME"),
    ("altura_marea", "FLOAT64"),
    ("temperatura", "FLOAT64"),
    ("viento_velocidad", "FLOAT64"),
    ("viento_direccion", "STRING"),
    ("lluvia", "FLOAT64"),
    ("fuente_origen", "STRING"),
    ("marca_temporal_carga", "TIMESTAMP"),
]


def flatten_station_records(station_key, records, loaded_at_iso):
    """
    Convierte los registros del cache de una estacion en filas listas
    para BigQuery. Devuelve (filas, fuentes_sin_datos), donde
    `fuentes_sin_datos` es un subconjunto de {"ina", "smn"} indicando
    que esa fuente no tuvo ningun dato en todo el cache de la estacion
    (para que el caller pueda loguear un warning y seguir).
    """
    ina_rows = []
    smn_rows = []

    for record in records:
        fecha = record.get("fecha")
        hora = record.get("hora")

        ina_rows.append(
            {
                "estacion": station_key,
                "fecha": fecha,
                "hora": hora,
                "altura_marea": record.get("altura_promedio"),
                "temperatura": None,
                "viento_velocidad": None,
                "viento_direccion": None,
                "lluvia": None,
                "fuente_origen": "ina",
                "marca_temporal_carga": loaded_at_iso,
            }
        )
        smn_rows.append(
            {
                "estacion": station_key,
                "fecha": fecha,
                "hora": hora,
                "altura_marea": None,
                "temperatura": record.get("temperatura"),
                "viento_velocidad": record.get("viento_km_h"),
                "viento_direccion": record.get("viento_direccion_abreviatura"),
                "lluvia": record.get("precipitacion_mm"),
                "fuente_origen": "smn",
                "marca_temporal_carga": loaded_at_iso,
            }
        )

    fuentes_sin_datos = set()
    rows = []

    if any(row["altura_marea"] is not None for row in ina_rows):
        rows.extend(ina_rows)
    else:
        fuentes_sin_datos.add("ina")

    if any(
        row["temperatura"] is not None
        or row["viento_velocidad"] is not None
        or row["lluvia"] is not None
        for row in smn_rows
    ):
        rows.extend(smn_rows)
    else:
        fuentes_sin_datos.add("smn")

    return rows, fuentes_sin_datos
