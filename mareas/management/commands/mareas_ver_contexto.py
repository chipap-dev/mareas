"""
Formas de ejecutar:
- python manage.py mareas_ver_contexto
- python manage.py mareas_ver_contexto --json
"""

import json

from django.core.management.base import BaseCommand

from mareas.services.admin_ops import summarize_context


class Command(BaseCommand):
    help = "Muestra el resumen del contexto que hoy consume la vista Mareas."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        context = summarize_context()
        if options["as_json"]:
            self.stdout.write(json.dumps(context, ensure_ascii=False, indent=2))
            return

        self.stdout.write(
            f"default={context['default_station']} | visual={context['visual_moment']}"
        )
        for station in context["stations"]:
            self.stdout.write(
                f"- {station['key']}: {station['days']} dias | {station['source_status_label']}"
            )
        if context["source_warning"]:
            self.stdout.write(f"warning: {context['source_warning']}")
