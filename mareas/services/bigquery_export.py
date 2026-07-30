"""
Aplanado de datos de Mareas para la carga incremental (append-only) a
BigQuery. No es usado por la app Django para servir al visitante -
solo por el management command `mareas_cargar_bigquery`.

Dos tablas independientes:

- `mareas_raw.lecturas`: una fila por fecha+hora+fuente_origen. El
  lado INA (`flatten_ina_lecturas_rows`) sale de una consulta directa
  al INA con ventana hacia atrás, agregada a promedio por
  `refresh.py::group_ina_rows`, filtrada a horas con mas de 48h de
  antiguedad (ver mareas_cargar_bigquery.py - el valor todavia se
  mueve mientras esta fresco). El lado SMN
  (`flatten_smn_lecturas_rows`) sale del cache local (el pronostico
  que ya sirve al dashboard), sin ese filtro: el SMN no tiene forma de
  volver a consultar una fecha pasada, asi que se carga apenas
  aparece, una sola vez.
- `mareas_raw.altura_marea_por_miembro`: las 5 lecturas crudas de
  marea que el INA devuelve por hora, sin agregar
  (`flatten_ina_raw_rows` / `assign_ina_miembros`), mismo filtro de
  48h que el lado INA de `lecturas`.
"""

from collections import defaultdict
from datetime import datetime

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

TABLE_SCHEMA_FIELDS_ALTURA_MIEMBRO = [
    ("estacion", "STRING"),
    ("fecha", "DATE"),
    ("hora", "TIME"),
    ("ina_miembro", "INT64"),
    ("altura_valor", "FLOAT64"),
    ("prono_id", "INT64"),
    ("corid", "INT64"),
    ("marca_temporal_carga", "TIMESTAMP"),
]


def flatten_ina_lecturas_rows(station_key, ina_records, loaded_at_iso):
    """
    Convierte registros agregados de marea (salida de
    `refresh.py::group_ina_rows`, ya filtrada a horas asentadas - ver
    mareas_cargar_bigquery.py) en filas de `mareas_raw.lecturas`,
    fuente_origen='ina'. Devuelve (filas, tiene_datos): `tiene_datos`
    es False si `ina_records` no tenia ningun valor de altura (para
    que el caller pueda loguear un warning y seguir sin cargar nada).
    """
    rows = [
        {
            "estacion": station_key,
            "fecha": record.get("fecha"),
            "hora": record.get("hora"),
            "altura_marea": record.get("altura_promedio"),
            "temperatura": None,
            "viento_velocidad": None,
            "viento_direccion": None,
            "lluvia": None,
            "fuente_origen": "ina",
            "marca_temporal_carga": loaded_at_iso,
        }
        for record in ina_records
    ]
    tiene_datos = any(row["altura_marea"] is not None for row in rows)
    return rows, tiene_datos


def flatten_smn_lecturas_rows(station_key, cache_records, loaded_at_iso):
    """
    Convierte los registros del cache local (el pronostico que ya
    sirve al dashboard) en filas de `mareas_raw.lecturas`,
    fuente_origen='smn'. Sin filtro de asentamiento: el SMN no tiene
    forma de volver a consultar una fecha pasada, asi que se carga tal
    como esta en el cache apenas aparece. Devuelve (filas,
    tiene_datos), mismo motivo que `flatten_ina_lecturas_rows`.
    """
    rows = [
        {
            "estacion": station_key,
            "fecha": record.get("fecha"),
            "hora": record.get("hora"),
            "altura_marea": None,
            "temperatura": record.get("temperatura"),
            "viento_velocidad": record.get("viento_km_h"),
            "viento_direccion": record.get("viento_direccion_abreviatura"),
            "lluvia": record.get("precipitacion_mm"),
            "fuente_origen": "smn",
            "marca_temporal_carga": loaded_at_iso,
        }
        for record in cache_records
    ]
    tiene_datos = any(
        row["temperatura"] is not None or row["viento_velocidad"] is not None or row["lluvia"] is not None
        for row in rows
    )
    return rows, tiene_datos


def assign_ina_miembros(raw_rows):
    """
    Agrupa las lecturas crudas del INA (ver
    `mareas.services.refresh.fetch_ina_raw_rows`) por `(fecha, hora)` y
    asigna `ina_miembro` 0-4 ordenando cada grupo por `valor`
    ascendente (desempate por `prono_id` ascendente si dos valores son
    identicos). Es estable por construccion: `prono_id` es secuencial
    por corrida del INA y no sirve como clave entre corridas (la misma
    fecha+hora se re-pronostica con ids nuevos cada dia), pero el
    orden por valor no depende de la corrida.

    Si alguna hora no trae exactamente 5 lecturas, levanta ValueError
    en vez de asignar un rango corrido: significa que la API cambio de
    forma o el fetch fue parcial, y cargar igual inventaria un miembro
    que no existio.
    """
    grouped = defaultdict(list)
    for row in raw_rows:
        timestamp = datetime.fromisoformat(row["timestart"])
        key = (timestamp.date().isoformat(), timestamp.time().isoformat())
        grouped[key].append(row)

    result = []
    for (fecha, hora), rows in grouped.items():
        if len(rows) != 5:
            raise ValueError(
                f"Se esperaban 5 lecturas del INA para {fecha} {hora}, llegaron {len(rows)}."
            )
        ordered = sorted(rows, key=lambda r: (r["valor"], r["prono_id"]))
        for miembro, row in enumerate(ordered):
            result.append(
                {
                    "fecha": fecha,
                    "hora": hora,
                    "ina_miembro": miembro,
                    "altura_valor": row["valor"],
                    "prono_id": row["prono_id"],
                }
            )

    return result


def flatten_ina_raw_rows(station_key, raw_rows, corid, loaded_at_iso):
    """
    Convierte las lecturas crudas de una estacion en filas listas para
    `mareas_raw.altura_marea_por_miembro`. A diferencia de
    `flatten_station_records`, no agrega nada: conserva las 5 alturas
    de cada hora, identificadas por `ina_miembro`. `corid` (id de
    corrida del INA) se guarda como columna de trazabilidad, no como
    parte de la clave.
    """
    return [
        {
            "estacion": station_key,
            "fecha": miembro["fecha"],
            "hora": miembro["hora"],
            "ina_miembro": miembro["ina_miembro"],
            "altura_valor": miembro["altura_valor"],
            "prono_id": miembro["prono_id"],
            "corid": corid,
            "marca_temporal_carga": loaded_at_iso,
        }
        for miembro in assign_ina_miembros(raw_rows)
    ]
