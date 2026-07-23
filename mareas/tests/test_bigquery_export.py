import json
import sys
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

from mareas.services.bigquery_export import flatten_station_records

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class FlattenStationRecordsTests(SimpleTestCase):
    def setUp(self):
        payload = json.loads((FIXTURES_DIR / "marea_ejemplo.json").read_text(encoding="utf-8"))
        self.records = payload["datos"]

    def test_aplana_a_filas_ina_y_smn_con_las_columnas_esperadas(self):
        rows, fuentes_sin_datos = flatten_station_records(
            "san_fernando", self.records, "2026-07-22T00:00:00+00:00"
        )

        self.assertEqual(fuentes_sin_datos, set())
        self.assertEqual(len(rows), len(self.records) * 2)

        expected_columns = {
            "estacion",
            "fecha",
            "hora",
            "altura_marea",
            "temperatura",
            "viento_velocidad",
            "viento_direccion",
            "lluvia",
            "fuente_origen",
            "marca_temporal_carga",
        }
        for row in rows:
            self.assertEqual(set(row.keys()), expected_columns)
            self.assertEqual(row["estacion"], "san_fernando")
            self.assertEqual(row["marca_temporal_carga"], "2026-07-22T00:00:00+00:00")

        ina_row = next(row for row in rows if row["fuente_origen"] == "ina")
        self.assertEqual(ina_row["altura_marea"], self.records[0]["altura_promedio"])
        self.assertIsNone(ina_row["temperatura"])

        smn_row = next(row for row in rows if row["fuente_origen"] == "smn")
        self.assertEqual(smn_row["temperatura"], self.records[0]["temperatura"])
        self.assertEqual(smn_row["viento_velocidad"], self.records[0]["viento_km_h"])
        self.assertIsNone(smn_row["altura_marea"])

    def test_marca_fuente_sin_datos_cuando_todo_es_none(self):
        records_sin_clima = [
            {**self.records[0], "temperatura": None, "viento_km_h": None, "precipitacion_mm": None}
        ]

        rows, fuentes_sin_datos = flatten_station_records(
            "rosario", records_sin_clima, "2026-07-22T00:00:00+00:00"
        )

        self.assertEqual(fuentes_sin_datos, {"smn"})
        self.assertTrue(all(row["fuente_origen"] == "ina" for row in rows))


class CargarBigQueryCommandTests(SimpleTestCase):
    """
    Corre el management command con el cliente de BigQuery mockeado:
    no debe pegarle a BigQuery real ni requerir credenciales ni el
    paquete google-cloud-bigquery instalado.
    """

    def test_command_hace_merge_con_tope_de_bytes_facturados(self):
        payload = json.loads((FIXTURES_DIR / "marea_ejemplo.json").read_text(encoding="utf-8"))
        fixture_records = payload["datos"]

        fake_bigquery = mock.MagicMock()
        fake_bigquery.WriteDisposition.WRITE_TRUNCATE = "WRITE_TRUNCATE"
        fake_client = mock.MagicMock()
        fake_bigquery.Client.return_value = fake_client
        fake_google_cloud = mock.MagicMock(bigquery=fake_bigquery)

        env = {
            "GCP_PROJECT_ID": "chipap",
            "GCP_DATASET_RAW": "mareas_raw",
            "GCP_LOCATION": "us-central1",
        }

        with mock.patch.dict(
            sys.modules, {"google.cloud": fake_google_cloud, "google.cloud.bigquery": fake_bigquery}
        ):
            with mock.patch.dict("os.environ", env):
                with mock.patch(
                    "mareas.management.commands.mareas_cargar_bigquery.load_station_cache",
                    return_value=(fixture_records, None, None),
                ):
                    call_command("mareas_cargar_bigquery", station="san_fernando")

        # Las filas se suben a una tabla staging temporal, no directo al target.
        fake_client.load_table_from_json.assert_called_once()
        load_args, _load_kwargs = fake_client.load_table_from_json.call_args
        rows, staging_table_ref = load_args
        self.assertEqual(len(rows), 4)  # 2 registros x (ina + smn)
        self.assertTrue(staging_table_ref.startswith("chipap.mareas_raw._staging_mareas_"))

        _, load_job_config_kwargs = fake_bigquery.LoadJobConfig.call_args
        self.assertEqual(load_job_config_kwargs["write_disposition"], "WRITE_TRUNCATE")

        # El MERGE hacia el target corre con un tope duro de bytes facturados.
        fake_client.query.assert_called_once()
        (merge_sql,), query_kwargs = fake_client.query.call_args
        self.assertIn("MERGE `chipap.mareas_raw.lecturas`", merge_sql)
        self.assertIn(staging_table_ref, merge_sql)
        self.assertIn("marca_temporal_carga", merge_sql)

        _, query_job_config_kwargs = fake_bigquery.QueryJobConfig.call_args
        self.assertEqual(query_job_config_kwargs["maximum_bytes_billed"], 200 * 1024 * 1024)

        # La tabla staging se borra despues del MERGE, exista o no.
        fake_client.delete_table.assert_called_once_with(staging_table_ref, not_found_ok=True)
