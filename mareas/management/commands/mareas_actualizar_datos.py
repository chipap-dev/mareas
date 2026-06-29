"""
Formas de ejecutar:
- python manage.py mareas_actualizar_datos
- python manage.py mareas_actualizar_datos --station san_fernando
- python manage.py mareas_actualizar_datos --json
- python manage.py mareas_actualizar_datos --station san_fernando --json
"""

import json

from django.core.management.base import BaseCommand, CommandError

from mareas.services.admin_ops import refresh_real_data


class Command(BaseCommand):
    help = "Actualiza los caches locales de Mareas desde INA y SMN."

    def add_arguments(self, parser):
        parser.add_argument("--station", dest="station_key")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        try:
            result = refresh_real_data(station_key=options["station_key"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(f"No se pudieron actualizar los datos reales: {exc}") from exc

        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            forecast_status = "OK" if result["forecast_ok"] else f"sin SMN ({result['forecast_error']})"
            self.stdout.write(f"Pronostico SMN: {forecast_status}")
            for item in result["results"]:
                self.stdout.write(
                    f"{item['key']}: {item['records']} registros | meteo: {item['weather_source']} | {item['cache_path']}"
                )
            for error in result["errors"]:
                self.stderr.write(f"{error['key']}: {error['error']}")

        if result["errors"]:
            raise CommandError("Algunas estaciones no pudieron actualizarse.")
