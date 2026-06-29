"""
Formas de ejecutar:
- python manage.py mareas_validar_fuente
- python manage.py mareas_validar_fuente --json
"""

import json

from django.core.management.base import BaseCommand, CommandError

from mareas.services.admin_ops import validate_source


class Command(BaseCommand):
    help = "Valida catalogo, caches y transformacion de datos reales de Mareas."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        report = validate_source()
        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for result in report["results"]:
                self.stdout.write(
                    f"{result['key']}: {result['records']} registros | "
                    f"{result['days']} dias | {result['status']}"
                )
            for error in report["errors"]:
                self.stderr.write(f"{error['key']}: {error['error']}")

        if not report["ok"]:
            raise CommandError("La fuente real de Mareas tiene errores.")
