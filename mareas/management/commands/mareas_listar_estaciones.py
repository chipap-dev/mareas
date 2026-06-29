"""
Formas de ejecutar:
- python manage.py mareas_listar_estaciones
- python manage.py mareas_listar_estaciones --json
"""

import json

from django.core.management.base import BaseCommand

from mareas.services.admin_ops import list_stations


class Command(BaseCommand):
    help = "Lista las estaciones disponibles de Mareas y si tienen cache local."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        stations = list_stations()
        if options["as_json"]:
            self.stdout.write(json.dumps(stations, ensure_ascii=False, indent=2))
            return

        for station in stations:
            status = "cache OK" if station["cache_exists"] else "sin cache"
            self.stdout.write(
                f"{station['key']}: {station['name']} | {status} | {station['cache_path']}"
            )
