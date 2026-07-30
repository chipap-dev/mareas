import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

# Import explicito del modulo del comando antes de que mock.patch
# necesite resolver su dotted path por primera vez: sin esto,
# mock.patch("mareas.management.commands.mareas_cargar_bigquery.X", ...)
# puede resolver el submodulo por un camino distinto al que usa
# call_command() internamente (import_module vs getattr encadenado
# sobre el paquete padre), parcheando un objeto de modulo que no es el
# que termina ejecutandose. Mismo problema de fondo que en
# test_actualizar_datos_command.py.
from mareas.management.commands import mareas_cargar_bigquery  # noqa: F401
from mareas.services.bigquery_export import (
    assign_ina_miembros,
    flatten_ina_lecturas_rows,
    flatten_ina_raw_rows,
    flatten_smn_lecturas_rows,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# 5 lecturas crudas para una misma hora, prono_id deliberadamente
# fuera de orden respecto del valor (como llegan realmente del INA -
# ver mareas/services/refresh.py::fetch_ina_raw_rows).
INA_RAW_ROWS_UNA_HORA = [
    {"prono_id": 5003, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.30},
    {"prono_id": 5001, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.10},
    {"prono_id": 5002, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.20},
    {"prono_id": 5004, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.40},
    {"prono_id": 5005, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.50},
]


def _ina_raw_rows_asentadas(dias_atras=5):
    """
    Mismo shape que INA_RAW_ROWS_UNA_HORA, pero con timestart calculado
    en relacion al momento en que corre el test (no un string fijo):
    la carga a BigQuery filtra por antiguedad real (ver
    mareas_cargar_bigquery.py::ASENTAMIENTO_HORAS = 48), asi que un
    fixture con fecha fija se volveria invalido con el tiempo.
    """
    momento = (datetime.now() - timedelta(days=dias_atras)).replace(minute=0, second=0, microsecond=0)
    timestart = momento.isoformat()
    return [
        {"prono_id": 6001, "timestart": timestart, "timeend": timestart, "valor": 1.10},
        {"prono_id": 6002, "timestart": timestart, "timeend": timestart, "valor": 1.20},
        {"prono_id": 6003, "timestart": timestart, "timeend": timestart, "valor": 1.30},
        {"prono_id": 6004, "timestart": timestart, "timeend": timestart, "valor": 1.40},
        {"prono_id": 6005, "timestart": timestart, "timeend": timestart, "valor": 1.50},
    ]


class AssignInaMiembrosTests(SimpleTestCase):
    def test_asigna_0_a_4_ordenando_por_valor_ascendente(self):
        miembros = assign_ina_miembros(INA_RAW_ROWS_UNA_HORA)

        self.assertEqual({m["ina_miembro"] for m in miembros}, {0, 1, 2, 3, 4})
        by_miembro = {m["ina_miembro"]: m for m in miembros}
        self.assertEqual(by_miembro[0]["altura_valor"], 1.10)
        self.assertEqual(by_miembro[0]["prono_id"], 5001)
        self.assertEqual(by_miembro[4]["altura_valor"], 1.50)
        self.assertEqual(by_miembro[4]["prono_id"], 5005)

    def test_desempata_por_prono_id_ascendente_si_el_valor_se_repite(self):
        empatados = [
            {"prono_id": 9002, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.20},
            {"prono_id": 9001, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.20},
            {"prono_id": 9003, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.30},
            {"prono_id": 9004, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.40},
            {"prono_id": 9005, "timestart": "2026-07-22T00:00:00", "timeend": "2026-07-22T00:00:00", "valor": 1.50},
        ]

        miembros = assign_ina_miembros(empatados)
        by_miembro = {m["ina_miembro"]: m for m in miembros}
        self.assertEqual(by_miembro[0]["prono_id"], 9001)
        self.assertEqual(by_miembro[1]["prono_id"], 9002)

    def test_falla_explicito_si_una_hora_trae_cuatro_lecturas(self):
        with self.assertRaisesMessage(
            ValueError, "Se esperaban 5 lecturas del INA para 2026-07-22 00:00:00, llegaron 4."
        ):
            assign_ina_miembros(INA_RAW_ROWS_UNA_HORA[:4])

    def test_falla_explicito_si_una_hora_trae_seis_lecturas(self):
        extra = {**INA_RAW_ROWS_UNA_HORA[0], "prono_id": 5006, "valor": 1.60}
        with self.assertRaisesMessage(
            ValueError, "Se esperaban 5 lecturas del INA para 2026-07-22 00:00:00, llegaron 6."
        ):
            assign_ina_miembros(INA_RAW_ROWS_UNA_HORA + [extra])


class FlattenInaRawRowsTests(SimpleTestCase):
    def test_agrega_estacion_corid_y_marca_temporal_a_cada_miembro(self):
        rows = flatten_ina_raw_rows("san_fernando", INA_RAW_ROWS_UNA_HORA, 123456, "2026-07-22T00:00:00+00:00")

        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(row["estacion"], "san_fernando")
            self.assertEqual(row["corid"], 123456)
            self.assertEqual(row["marca_temporal_carga"], "2026-07-22T00:00:00+00:00")
        self.assertEqual({row["ina_miembro"] for row in rows}, {0, 1, 2, 3, 4})


class FlattenIntLecturasRowsTests(SimpleTestCase):
    """
    flatten_ina_lecturas_rows / flatten_smn_lecturas_rows reemplazan a
    la vieja flatten_station_records: antes una sola funcion leia un
    registro de cache con marea+clima mezclados; ahora cada fuente sale
    de un origen distinto (ver bigquery_export.py) y se aplana por
    separado.
    """

    def setUp(self):
        payload = json.loads((FIXTURES_DIR / "marea_ejemplo.json").read_text(encoding="utf-8"))
        self.records = payload["datos"]

    def test_flatten_ina_produce_una_fila_por_registro_sin_columnas_de_clima(self):
        rows, tiene_datos = flatten_ina_lecturas_rows("san_fernando", self.records, "2026-07-22T00:00:00+00:00")

        self.assertTrue(tiene_datos)
        self.assertEqual(len(rows), len(self.records))
        for row in rows:
            self.assertEqual(row["estacion"], "san_fernando")
            self.assertEqual(row["fuente_origen"], "ina")
            self.assertEqual(row["marca_temporal_carga"], "2026-07-22T00:00:00+00:00")
            self.assertIsNone(row["temperatura"])
        self.assertEqual(rows[0]["altura_marea"], self.records[0]["altura_promedio"])

    def test_flatten_ina_marca_sin_datos_si_no_hay_ningun_altura_promedio(self):
        registros_vacios = [{**r, "altura_promedio": None} for r in self.records]

        rows, tiene_datos = flatten_ina_lecturas_rows("san_fernando", registros_vacios, "2026-07-22T00:00:00+00:00")

        self.assertFalse(tiene_datos)
        self.assertTrue(all(row["altura_marea"] is None for row in rows))

    def test_flatten_smn_produce_una_fila_por_registro_sin_altura_marea(self):
        rows, tiene_datos = flatten_smn_lecturas_rows("san_fernando", self.records, "2026-07-22T00:00:00+00:00")

        self.assertTrue(tiene_datos)
        self.assertEqual(len(rows), len(self.records))
        for row in rows:
            self.assertEqual(row["estacion"], "san_fernando")
            self.assertEqual(row["fuente_origen"], "smn")
            self.assertIsNone(row["altura_marea"])
        self.assertEqual(rows[0]["temperatura"], self.records[0]["temperatura"])
        self.assertEqual(rows[0]["viento_velocidad"], self.records[0]["viento_km_h"])

    def test_flatten_smn_marca_sin_datos_cuando_todo_es_none(self):
        registros_sin_clima = [
            {**self.records[0], "temperatura": None, "viento_km_h": None, "precipitacion_mm": None}
        ]

        rows, tiene_datos = flatten_smn_lecturas_rows("rosario", registros_sin_clima, "2026-07-22T00:00:00+00:00")

        self.assertFalse(tiene_datos)


class CargarBigQueryCommandTests(SimpleTestCase):
    """
    Corre el management command con el cliente de BigQuery mockeado:
    no debe pegarle a BigQuery real ni requerir credenciales ni el
    paquete google-cloud-bigquery instalado.
    """

    def _run_command(self, ina_raw_rows):
        payload = json.loads((FIXTURES_DIR / "marea_ejemplo.json").read_text(encoding="utf-8"))
        fixture_records = payload["datos"]

        fake_bigquery = mock.MagicMock()
        fake_bigquery.WriteDisposition.WRITE_APPEND = "WRITE_APPEND"
        fake_client = mock.MagicMock()
        # Sin claves existentes: todas las filas candidatas son nuevas.
        fake_client.query.return_value.result.return_value = []
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
                    with mock.patch(
                        "mareas.management.commands.mareas_cargar_bigquery.fetch_ina_raw_rows",
                        return_value=(ina_raw_rows, 999888),
                    ):
                        call_command("mareas_cargar_bigquery", station="san_fernando")

        return fake_client, fake_bigquery

    def test_carga_append_only_sin_staging_ni_merge(self):
        fake_client, fake_bigquery = self._run_command(_ina_raw_rows_asentadas())

        # Dos tablas, dos loads directos al destino: lecturas (ina
        # asentado + smn del cache) y altura_marea_por_miembro (mismo
        # fetch ina, crudo).
        self.assertEqual(fake_client.load_table_from_json.call_count, 2)
        lecturas_call, altura_miembro_call = fake_client.load_table_from_json.call_args_list

        lecturas_rows, lecturas_destino = lecturas_call.args
        self.assertEqual(lecturas_destino, "chipap.mareas_raw.lecturas")
        self.assertEqual(len(lecturas_rows), 3)  # 1 hora ina asentada + 2 registros smn del cache
        self.assertEqual({row["fuente_origen"] for row in lecturas_rows}, {"ina", "smn"})

        miembro_rows, miembro_destino = altura_miembro_call.args
        self.assertEqual(miembro_destino, "chipap.mareas_raw.altura_marea_por_miembro")
        self.assertEqual(len(miembro_rows), 5)  # 5 miembros de la unica hora asentada
        self.assertEqual({row["ina_miembro"] for row in miembro_rows}, {0, 1, 2, 3, 4})
        self.assertTrue(all(row["corid"] == 999888 for row in miembro_rows))

        # write_disposition = WRITE_APPEND en ambos loads, no WRITE_TRUNCATE.
        for call in fake_bigquery.LoadJobConfig.call_args_list:
            self.assertEqual(call.kwargs["write_disposition"], "WRITE_APPEND")

        # Sin MERGE: una query por tabla (el chequeo de "ya existe"),
        # con el mismo tope de bytes facturados de siempre.
        self.assertEqual(fake_client.query.call_count, 2)
        for call in fake_bigquery.QueryJobConfig.call_args_list:
            self.assertEqual(call.kwargs["maximum_bytes_billed"], 200 * 1024 * 1024)

        # Sin tabla staging: nada que crear ni borrar aparte del load directo.
        fake_client.delete_table.assert_not_called()

    def test_no_carga_lecturas_del_ina_con_menos_de_48h_de_antiguedad(self):
        fake_client, _fake_bigquery = self._run_command(_ina_raw_rows_asentadas(dias_atras=0))

        # La hora de "hoy" no esta asentada (no llega a 48h): no
        # produce fila ina en lecturas ni miembros en
        # altura_marea_por_miembro, asi que ese segundo load ni se
        # intenta - solo corre el de lecturas, con las 2 filas smn del
        # cache (que no espera asentamiento).
        self.assertEqual(fake_client.load_table_from_json.call_count, 1)
        (lecturas_call,) = fake_client.load_table_from_json.call_args_list
        lecturas_rows, lecturas_destino = lecturas_call.args
        self.assertEqual(lecturas_destino, "chipap.mareas_raw.lecturas")
        self.assertEqual([row["fuente_origen"] for row in lecturas_rows], ["smn", "smn"])
