"""
Formas de ejecutar:
- python manage.py mareas_ver_cache
- python manage.py mareas_ver_cache --station san_fernando
- python manage.py mareas_ver_cache --json
- python manage.py mareas_ver_cache --station rosario --json
"""

import json

from django.core.management.base import BaseCommand

from mareas.services.admin_ops import summarize_cache


class Command(BaseCommand):
    help = "Muestra resumen del cache real de Mareas para una estacion o para todas."

    def add_arguments(self, parser):
        parser.add_argument("--station", dest="station_key")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        summary = summarize_cache(options["station_key"])
        if options["as_json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
            return

        for item in summary:
            days = ", ".join(item["days"])
            self.stdout.write(
                f"{item['key']}: {item['records']} registros | dias: {days} | actualizado: {item['updated_at']}"
            )
