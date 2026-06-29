"""
Formas de ejecutar:
- python manage.py mareas_ver_estacion --station san_fernando
- python manage.py mareas_ver_estacion --station rosario
- python manage.py mareas_ver_estacion --station san_fernando --day 2026-02-02
- python manage.py mareas_ver_estacion --station san_fernando --json
- python manage.py mareas_ver_estacion --station zarate --day 2026-02-03 --json
"""

import json

from django.core.management.base import BaseCommand, CommandError

from mareas.services.admin_ops import render_station_payload


class Command(BaseCommand):
    help = "Renderiza el payload transformado de una estacion de Mareas."

    def add_arguments(self, parser):
        parser.add_argument("--station", required=True, dest="station_key")
        parser.add_argument("--day", dest="day_slug")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        try:
            payload = render_station_payload(options["station_key"], options["day_slug"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if options["as_json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        if "day" in payload:
            day = payload["day"]
            self.stdout.write(
                f"{payload['name']} | {day['label']} {day['date_label']} | "
                f"altura {day['height_now']} | estado {day['state']} | "
                f"pleamar {day['next_high']} | bajamar {day['next_low']}"
            )
            return

        self.stdout.write(
            f"{payload['name']} | {len(payload['days'])} dias | {payload['source_status_label']}"
        )
