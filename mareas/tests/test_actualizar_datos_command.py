from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

COMMAND_MODULE = "mareas.management.commands.mareas_actualizar_datos"


def _fake_result(results, errors):
    return {
        "ok": not errors,
        "forecast_ok": True,
        "forecast_error": None,
        "results": results,
        "errors": errors,
    }


class ActualizarDatosCommandTests(SimpleTestCase):
    """
    INA puede quedar con un modelo de pronostico stale para alguna
    estacion puntual (ver rosario/zarate, calId=489 sin corridas nuevas
    desde 2026-06-26) sin que el resto del pipeline este roto. El
    comando debe distinguir degradacion parcial (exit 0, warning en
    log) de fallo total (exit != 0).
    """

    def test_si_todas_las_estaciones_fallan_el_comando_sale_con_error(self):
        fake_result = _fake_result(
            results=[],
            errors=[
                {"key": "rosario", "error": "INA no devolvio datos para rosario."},
                {"key": "zarate", "error": "INA no devolvio datos para zarate."},
            ],
        )

        with mock.patch(f"{COMMAND_MODULE}.refresh_real_data", return_value=fake_result):
            with self.assertRaises(CommandError):
                call_command("mareas_actualizar_datos")

    def test_si_una_estacion_falla_pero_otra_no_el_comando_sale_ok_y_loguea_warning(self):
        fake_result = _fake_result(
            results=[
                {
                    "key": "san_fernando",
                    "name": "San Fernando",
                    "records": 97,
                    "cache_path": "marea_san_fernando.json",
                    "weather_source": "SMN",
                }
            ],
            errors=[{"key": "rosario", "error": "INA no devolvio datos para rosario."}],
        )

        with mock.patch(f"{COMMAND_MODULE}.refresh_real_data", return_value=fake_result):
            with self.assertLogs(COMMAND_MODULE, level="WARNING") as logs:
                call_command("mareas_actualizar_datos")

        self.assertTrue(
            any("rosario" in message and "INA no devolvio datos para rosario." in message for message in logs.output)
        )
