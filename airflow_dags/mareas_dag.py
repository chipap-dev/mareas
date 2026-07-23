"""
DAG de orquestacion diaria de la capa de datos de Mareas.

Este archivo vive versionado en el repo de Mareas, pero no trae un
stack de Airflow propio: se asume que corre en el Airflow que ya
existe aparte (airflow_repo), copiando o linkeando este archivo a esa
carpeta dags/ (ver airflow_repo/scripts/sync_dags.sh).

El contenedor de Airflow monta mareas_repo en /opt/mareas (solo codigo
y credenciales) y trae sus dependencias (Django, dbt-bigquery,
google-cloud-bigquery) ya instaladas en la imagen - no depende de
ningun venv creado en el host.

Orden: actualizar_cache -> cargar_bigquery -> dbt_run -> dbt_test.

`actualizar_cache` refresca el cache local de las 3 estaciones (eso es
lo que sirve la app en vivo, sin cambios). `cargar_bigquery` sube solo
San Fernando: Rosario/Zarate no aportaban historico real (INA dejo de
generar pronosticos nuevos para esas dos, ver dbt_mareas/models/staging
/sources.yml) y no tenia sentido pagar por cargarlas.
"""

import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator

MAREAS_REPO_DIR = "/opt/mareas"
DBT_PROJECT_DIR = f"{MAREAS_REPO_DIR}/dbt_mareas"

MAREAS_ENV = {
    **os.environ,
    "GCP_PROJECT_ID": "chipap",
    "GCP_DATASET_RAW": "mareas_raw",
    "GCP_LOCATION": "us-central1",
    "GOOGLE_APPLICATION_CREDENTIALS": f"{MAREAS_REPO_DIR}/secrets/gcp-key.json",
    # profiles.yml vive junto a dbt_project.yml; dbt no lo busca ahi por
    # defecto (busca en ~/.dbt/), asi que se lo indicamos explicitamente.
    "DBT_PROFILES_DIR": DBT_PROJECT_DIR,
}

default_args = {
    "owner": "mareas",
    "retries": 0,
}

with DAG(
    dag_id="mareas_dag",
    description="Actualiza el cache de Mareas, lo carga a BigQuery y corre dbt.",
    default_args=default_args,
    schedule="@daily",
    # airflow.utils.dates.days_ago was removed in Airflow 3.x; a fixed
    # past date is the recommended replacement (catchup=False means the
    # exact value doesn't matter beyond "in the past").
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    tags=["mareas", "bigquery", "dbt"],
) as dag:

    actualizar_cache = BashOperator(
        task_id="actualizar_cache",
        bash_command=f"cd {MAREAS_REPO_DIR} && python manage.py mareas_actualizar_datos",
        env=MAREAS_ENV,
        retries=2,
        retry_delay=timedelta(minutes=5),
    )

    cargar_bigquery = BashOperator(
        task_id="cargar_bigquery",
        bash_command=(
            f"cd {MAREAS_REPO_DIR} && "
            "python manage.py mareas_cargar_bigquery --station san_fernando"
        ),
        env=MAREAS_ENV,
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {DBT_PROJECT_DIR} && dbt run",
        env=MAREAS_ENV,
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {DBT_PROJECT_DIR} && dbt test",
        env=MAREAS_ENV,
    )

    actualizar_cache >> cargar_bigquery >> dbt_run >> dbt_test
