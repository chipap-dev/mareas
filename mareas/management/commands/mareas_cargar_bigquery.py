"""
Carga incremental (append-only) de Mareas a BigQuery, en dos tablas
independientes del mismo dataset (`mareas_raw`). No corre como parte
del flujo que sirve al visitante.

- `lecturas`: marea (INA) + clima (SMN) por fecha+hora, una fila por
  fuente_origen. El lado INA sale de una consulta directa al INA con
  ventana hacia atras (no del cache local, que solo tiene "hoy en
  adelante" - ver mareas/services/source.py). El lado SMN sigue
  saliendo del cache local, sin cambios.
- `altura_marea_por_miembro`: las 5 lecturas crudas de marea que el
  INA devuelve por hora, sin agregar. Reusa la misma consulta al INA
  que el lado INA de `lecturas` (antes eran dos fetches separados).

No hay MERGE ni tabla staging: se consulta que (fecha, hora[, columna
extra]) ya existen en la tabla destino para la estacion, se filtran las
filas candidatas contra esas claves, y se cargan las que faltan con
`load_table_from_json` + WRITE_APPEND. Autorecuperable por
construccion: correr esto dos veces seguidas, o despues de que el DAG
estuvo caido unos dias, no duplica nada - simplemente no encuentra
nada nuevo para agregar, o completa lo que falto.

Margen de asentamiento (INA): el INA re-corre su modelo bastante mas
seguido que "una vez por dia" (se midieron dos corridas con 12 minutos
de diferencia) y revisa una ventana movil de horas ya pasadas, no solo
el pronostico futuro - ver docs/decisiones_carga_incremental_bigquery.md,
seccion 1. Por eso solo se cargan fecha+hora con mas de
ASENTAMIENTO_HORAS de antiguedad: cargar antes arriesga escribir un
valor que el INA todavia va a revisar, y sin MERGE no hay forma de
corregirlo despues.

El SMN no tiene este problema ni esta solucion: no existe un endpoint
para volver a consultarle una fecha pasada, asi que su lado de
`lecturas` se carga apenas aparece en el pronostico diario, sin
esperar nada (ver bigquery_export.py). Consecuencia visible en el mart:
las ultimas horas van a tener clima sin marea, hasta que esas horas
crucen el margen de asentamiento.

Forma de ejecutar:
- python manage.py mareas_cargar_bigquery
- python manage.py mareas_cargar_bigquery --station san_fernando
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand, CommandError

from mareas.services.bigquery_export import (
    TABLE_SCHEMA_FIELDS,
    TABLE_SCHEMA_FIELDS_ALTURA_MIEMBRO,
    flatten_ina_lecturas_rows,
    flatten_ina_raw_rows,
    flatten_smn_lecturas_rows,
)
from mareas.services.refresh import fetch_ina_raw_rows, group_ina_rows
from mareas.services.source import load_station_cache
from mareas.services.stations import load_station_catalog

logger = logging.getLogger(__name__)

TABLE_NAME = "lecturas"
TABLE_NAME_ALTURA_MIEMBRO = "altura_marea_por_miembro"

# Tope duro de bytes escaneados por consulta de "que ya existe" contra
# BigQuery. Las tablas son minusculas (una estacion, un puñado de filas
# por dia), asi que esto nunca deberia activarse en uso normal - es una
# red de seguridad para no depender solo de "los numeros dan chico".
MAX_BYTES_BILLED = 200 * 1024 * 1024  # 200 MB

# Una fecha+hora del INA se carga solo si tiene mas antiguedad que
# esto respecto al momento de la corrida. Ver docs/decisiones_carga_
# incremental_bigquery.md, seccion 1: se midio que el INA revisa una
# ventana movil de ~9-10h hacia atras en cada corrida: 48h da margen
# amplio sobre eso.
ASENTAMIENTO_HORAS = 48

# Cuantos dias hacia atras pedirle al INA en cada corrida. La ventana
# real del INA se midio en ~14 dias (ver decisiones, seccion 1 y 10);
# pedir de mas no rompe el fetch (se probo: un rango que arranca antes
# del borde real devuelve parcial, no falla), asi que se deja margen
# para que el pipeline se autorecupere solo si estuvo caido varios
# dias. Mas alla de ~(14 - ASENTAMIENTO_HORAS/24) dias de inactividad,
# la ventana del INA ya descarto esos datos antes de poder cargarlos -
# eso no lo arregla ningun margen de este numero.
HISTORIA_DIAS_ATRAS = 20

_CLAVE_LECTURAS = ("fecha", "hora", "fuente_origen")
_CLAVE_ALTURA_MIEMBRO = ("fecha", "hora", "ina_miembro")


def _get_client_and_config():
    from google.cloud import bigquery

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ["GCP_DATASET_RAW"]
    location = os.environ["GCP_LOCATION"]

    client = bigquery.Client(project=project_id, location=location)
    return client, project_id, dataset, bigquery


def _schema(bigquery, schema_fields):
    return [bigquery.SchemaField(name, field_type) for name, field_type in schema_fields]


def _ensure_table(client, table_ref, bigquery, schema_fields):
    table = bigquery.Table(table_ref, schema=_schema(bigquery, schema_fields))
    client.create_table(table, exists_ok=True)


def _existing_keys(client, bigquery, table_ref, key_columns, estacion):
    """
    Que valores de `key_columns` ya existen en `table_ref` para
    `estacion`. Un SELECT, no un load: cuenta contra el cupo de bytes
    escaneados (protegido igual con maximum_bytes_billed), nunca contra
    el de bytes facturados de un load job (que no existe).
    """
    columnas = ", ".join(key_columns)
    query = f"SELECT DISTINCT {columnas} FROM `{table_ref}` WHERE estacion = @estacion"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("estacion", "STRING", estacion)],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    resultado = client.query(query, job_config=job_config).result()

    claves = set()
    for fila in resultado:
        valores = []
        for columna in key_columns:
            valor = fila[columna]
            if hasattr(valor, "isoformat"):
                valor = valor.isoformat()
            valores.append(valor)
        claves.add(tuple(valores))
    return claves


def _append_missing_rows(client, bigquery, table_ref, rows, schema_fields, key_columns, estacion):
    """
    Carga solo las filas de `rows` cuya clave (`key_columns`) todavia
    no existe en `table_ref` para `estacion`. Devuelve cuantas filas
    nuevas se cargaron. WRITE_APPEND directo al destino: sin tabla
    staging, sin MERGE.
    """
    if not rows:
        return 0

    existentes = _existing_keys(client, bigquery, table_ref, key_columns, estacion)
    nuevas = [row for row in rows if tuple(row[columna] for columna in key_columns) not in existentes]
    if not nuevas:
        return 0

    job_config = bigquery.LoadJobConfig(
        schema=_schema(bigquery, schema_fields),
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_json(nuevas, table_ref, job_config=job_config)
    job.result()
    return len(nuevas)


def _filtrar_asentado(raw_rows, ahora):
    """
    Se queda con las lecturas crudas del INA cuyo `timestart` tiene mas
    de ASENTAMIENTO_HORAS de antiguedad respecto a `ahora`. Filtra a
    nivel de lectura individual, pero como las 5 lecturas de una misma
    fecha+hora comparten `timestart`, un grupo pasa completo o se
    descarta completo - nunca queda a medias para
    `assign_ina_miembros`.
    """
    corte = ahora - timedelta(hours=ASENTAMIENTO_HORAS)
    return [row for row in raw_rows if datetime.fromisoformat(row["timestart"]) <= corte]


class Command(BaseCommand):
    help = (
        "Sube Mareas a BigQuery: mareas_raw.lecturas y "
        "mareas_raw.altura_marea_por_miembro. Append-only incremental, "
        "sin DML: carga solo lo que todavia no existe."
    )

    def add_arguments(self, parser):
        parser.add_argument("--station", dest="station_key")

    def handle(self, *args, **options):
        try:
            client, project_id, dataset, bigquery = _get_client_and_config()
        except KeyError as exc:
            raise CommandError(f"Falta la variable de entorno {exc}.") from exc

        table_ref = f"{project_id}.{dataset}.{TABLE_NAME}"
        table_ref_altura_miembro = f"{project_id}.{dataset}.{TABLE_NAME_ALTURA_MIEMBRO}"

        _ensure_table(client, table_ref, bigquery, TABLE_SCHEMA_FIELDS)
        _ensure_table(client, table_ref_altura_miembro, bigquery, TABLE_SCHEMA_FIELDS_ALTURA_MIEMBRO)

        stations = load_station_catalog()
        station_key = options["station_key"]
        selected = [s for s in stations if station_key in (None, s["key"])]
        if not selected:
            raise CommandError(f"Estacion desconocida: {station_key}")

        ahora = datetime.now()
        loaded_at_iso = datetime.now(timezone.utc).isoformat()
        total_rows = 0
        errors = []

        for station in selected:
            key = station["key"]

            start_date = ahora.date() - timedelta(days=HISTORIA_DIAS_ATRAS)
            end_date = ahora.date() + timedelta(days=1)
            try:
                data, corid = fetch_ina_raw_rows(station, start_date, end_date)
            except RuntimeError as exc:
                logger.exception("Error consultando al INA para %s", key)
                errors.append({"key": key, "error": str(exc)})
                continue

            asentados = _filtrar_asentado(data, ahora)

            grouped = group_ina_rows(asentados, start_date)
            ina_rows, ina_tiene_datos = flatten_ina_lecturas_rows(key, grouped, loaded_at_iso)
            if not ina_tiene_datos:
                self.stderr.write(f"{key}: sin datos asentados de ina, se omiten esas filas en {TABLE_NAME}.")
                logger.warning("Estacion %s sin datos ina asentados.", key)
                ina_rows = []

            try:
                cache_records, _updated_at, _cache_path = load_station_cache(key)
            except FileNotFoundError:
                self.stderr.write(f"{key}: sin cache local, se omiten filas smn en {TABLE_NAME}.")
                logger.warning("Sin cache local para la estacion %s.", key)
                smn_rows = []
            else:
                smn_rows, smn_tiene_datos = flatten_smn_lecturas_rows(key, cache_records, loaded_at_iso)
                if not smn_tiene_datos:
                    self.stderr.write(f"{key}: sin datos de smn, se omiten esas filas en {TABLE_NAME}.")
                    logger.warning("Estacion %s sin datos de smn.", key)
                    smn_rows = []

            lecturas_rows = ina_rows + smn_rows
            if lecturas_rows:
                try:
                    agregadas = _append_missing_rows(
                        client, bigquery, table_ref, lecturas_rows, TABLE_SCHEMA_FIELDS, _CLAVE_LECTURAS, key
                    )
                except Exception as exc:
                    logger.exception("Error subiendo filas de %s a %s", key, TABLE_NAME)
                    errors.append({"key": key, "error": str(exc)})
                else:
                    total_rows += agregadas
                    self.stdout.write(
                        f"{key}: {agregadas} filas nuevas en {table_ref} (de {len(lecturas_rows)} candidatas)."
                    )

            try:
                miembro_rows = flatten_ina_raw_rows(key, asentados, corid, loaded_at_iso)
            except ValueError as exc:
                logger.exception("Error separando lecturas crudas asentadas del INA para %s", key)
                errors.append({"key": key, "error": str(exc)})
                continue

            if miembro_rows:
                try:
                    agregadas = _append_missing_rows(
                        client,
                        bigquery,
                        table_ref_altura_miembro,
                        miembro_rows,
                        TABLE_SCHEMA_FIELDS_ALTURA_MIEMBRO,
                        _CLAVE_ALTURA_MIEMBRO,
                        key,
                    )
                except Exception as exc:
                    logger.exception("Error subiendo filas de %s a %s", key, TABLE_NAME_ALTURA_MIEMBRO)
                    errors.append({"key": key, "error": str(exc)})
                else:
                    total_rows += agregadas
                    self.stdout.write(
                        f"{key}: {agregadas} filas nuevas en {table_ref_altura_miembro} "
                        f"(de {len(miembro_rows)} candidatas)."
                    )

        self.stdout.write(f"Total: {total_rows} filas nuevas cargadas.")

        if errors:
            for error in errors:
                self.stderr.write(f"{error['key']}: {error['error']}")
            raise CommandError("Algunas estaciones no pudieron cargarse a BigQuery.")
