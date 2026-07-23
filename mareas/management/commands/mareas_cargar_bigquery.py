"""
Carga incremental del cache local de Mareas a BigQuery
(`mareas_raw.lecturas`), para poder analizar series historicas de
marea y clima. No corre como parte del flujo que sirve al visitante.

Usa MERGE (upsert) en vez de un simple append: la clave natural es
estacion + fecha + hora + fuente_origen, y cada corrida se queda con
la version mas reciente (`marca_temporal_carga`) de cada fila. Esto es
necesario porque el cache local re-sube su ventana completa en cada
corrida diaria: sin dedup, una misma fecha+hora queda duplicada en el
raw una vez por cada dia que aparecio en esa ventana (ver
`mareas/services/bigquery_export.py` y `dbt_mareas/models/staging/`).
Con MERGE la tabla no crece sin limite - se acota a la cantidad real
de fecha+hora que existieron alguna vez.

Forma de ejecutar:
- python manage.py mareas_cargar_bigquery
- python manage.py mareas_cargar_bigquery --station san_fernando
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand, CommandError

from mareas.services.bigquery_export import TABLE_SCHEMA_FIELDS, flatten_station_records
from mareas.services.source import load_station_cache
from mareas.services.stations import load_station_catalog

logger = logging.getLogger(__name__)

TABLE_NAME = "lecturas"

# Tope duro de bytes escaneados por corrida del MERGE. La tabla es
# minuscula (algunas estaciones, un puñado de filas por dia), asi que
# esto nunca deberia activarse en uso normal - es una red de seguridad
# para no depender solo de "los numeros dan chico": si algo hace que la
# consulta necesite escanear mas de esto, falla en vez de facturar.
MAX_BYTES_BILLED = 200 * 1024 * 1024  # 200 MB

_MERGE_KEY_COLUMNS = ("estacion", "fecha", "hora", "fuente_origen")


def _get_client_and_config():
    from google.cloud import bigquery

    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ["GCP_DATASET_RAW"]
    location = os.environ["GCP_LOCATION"]

    client = bigquery.Client(project=project_id, location=location)
    table_ref = f"{project_id}.{dataset}.{TABLE_NAME}"
    return client, table_ref, bigquery


def _schema(bigquery):
    return [bigquery.SchemaField(name, field_type) for name, field_type in TABLE_SCHEMA_FIELDS]


def _ensure_table(client, table_ref, bigquery):
    table = bigquery.Table(table_ref, schema=_schema(bigquery))
    client.create_table(table, exists_ok=True)


def _load_staging_table(client, table_ref, bigquery, rows):
    """
    Sube `rows` a una tabla temporal (mismo dataset que el target,
    prefijo `_staging_`), con expiracion de 1 hora como red de
    seguridad si el borrado explicito de `_drop_staging_table` no
    llegara a correr. El load job en si no se factura por bytes (solo
    la carga de datos - a diferencia de una query - es gratis en
    BigQuery).
    """
    dataset_ref = table_ref.rsplit(".", 1)[0]
    staging_table_ref = f"{dataset_ref}._staging_mareas_{uuid.uuid4().hex}"

    table = bigquery.Table(staging_table_ref, schema=_schema(bigquery))
    table.expires = datetime.now(timezone.utc) + timedelta(hours=1)
    client.create_table(table)

    job_config = bigquery.LoadJobConfig(
        schema=_schema(bigquery),
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(rows, staging_table_ref, job_config=job_config)
    job.result()
    return staging_table_ref


def _drop_staging_table(client, staging_table_ref):
    client.delete_table(staging_table_ref, not_found_ok=True)


def _merge_sql(table_ref, staging_table_ref):
    update_columns = [name for name, _ in TABLE_SCHEMA_FIELDS if name not in _MERGE_KEY_COLUMNS]
    insert_columns = [name for name, _ in TABLE_SCHEMA_FIELDS]

    on_clause = " AND ".join(f"target.{col} = staging.{col}" for col in _MERGE_KEY_COLUMNS)
    update_clause = ", ".join(f"{col} = staging.{col}" for col in update_columns)
    insert_cols_clause = ", ".join(insert_columns)
    insert_values_clause = ", ".join(f"staging.{col}" for col in insert_columns)

    return f"""
        MERGE `{table_ref}` AS target
        USING `{staging_table_ref}` AS staging
        ON {on_clause}
        WHEN MATCHED AND staging.marca_temporal_carga > target.marca_temporal_carga THEN
            UPDATE SET {update_clause}
        WHEN NOT MATCHED THEN
            INSERT ({insert_cols_clause})
            VALUES ({insert_values_clause})
    """


def _merge_rows(client, table_ref, bigquery, rows):
    staging_table_ref = _load_staging_table(client, table_ref, bigquery, rows)
    try:
        job_config = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED)
        query_job = client.query(_merge_sql(table_ref, staging_table_ref), job_config=job_config)
        query_job.result()
    finally:
        _drop_staging_table(client, staging_table_ref)


class Command(BaseCommand):
    help = "Sube el cache local de Mareas a BigQuery (mareas_raw.lecturas, MERGE incremental)."

    def add_arguments(self, parser):
        parser.add_argument("--station", dest="station_key")

    def handle(self, *args, **options):
        try:
            client, table_ref, bigquery = _get_client_and_config()
        except KeyError as exc:
            raise CommandError(f"Falta la variable de entorno {exc}.") from exc

        _ensure_table(client, table_ref, bigquery)

        stations = load_station_catalog()
        station_key = options["station_key"]
        selected = [s for s in stations if station_key in (None, s["key"])]
        if not selected:
            raise CommandError(f"Estacion desconocida: {station_key}")

        loaded_at_iso = datetime.now(timezone.utc).isoformat()
        total_rows = 0
        errors = []

        for station in selected:
            key = station["key"]
            try:
                records, _updated_at, _cache_path = load_station_cache(key)
            except FileNotFoundError:
                self.stderr.write(f"{key}: sin cache local, se omite.")
                logger.warning("Sin cache local para la estacion %s, se omite.", key)
                continue

            rows, fuentes_sin_datos = flatten_station_records(key, records, loaded_at_iso)
            for fuente in sorted(fuentes_sin_datos):
                self.stderr.write(f"{key}: sin datos de {fuente}, se omiten esas filas.")
                logger.warning("Estacion %s sin datos de la fuente %s.", key, fuente)

            if not rows:
                continue

            try:
                _merge_rows(client, table_ref, bigquery, rows)
            except Exception as exc:
                logger.exception("Error subiendo filas de %s a BigQuery", key)
                errors.append({"key": key, "error": str(exc)})
                continue

            total_rows += len(rows)
            self.stdout.write(f"{key}: {len(rows)} filas actualizadas/insertadas en {table_ref}.")

        self.stdout.write(f"Total: {total_rows} filas procesadas.")

        if errors:
            for error in errors:
                self.stderr.write(f"{error['key']}: {error['error']}")
            raise CommandError("Algunas estaciones no pudieron cargarse a BigQuery.")
