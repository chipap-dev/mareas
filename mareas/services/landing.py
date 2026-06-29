import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .source import load_station_cache
from .stations import load_station_catalog
from .transform import BUENOS_AIRES, build_station_payload, get_visual_moment


logger = logging.getLogger(__name__)


def get_mareas_context():
    try:
        station_catalog = load_station_catalog()
        stations = []
        load_errors = []

        for station_config in station_catalog:
            try:
                records, updated_at, _cache_path = load_station_cache(station_config["key"])
                station_payload = build_station_payload(station_config, records, updated_at)
                stations.append(station_payload)
            except Exception as exc:
                logger.exception("Failed loading Mareas data for station %s", station_config["key"])
                load_errors.append(f"{station_config['name']}: {exc}")

        if not stations:
            raise ValueError("No real Mareas stations could be loaded")

        default_station = "san_fernando"
        active_station = next(
            (station for station in stations if station["key"] == default_station),
            stations[0],
        )
        today_slug = datetime.now(BUENOS_AIRES).date().isoformat()
        active_day = next(
            (day for day in active_station["days"] if day["slug"] == today_slug),
            active_station["days"][0],
        )

        technical_sections = [
            {
                "title": "Como se usa",
                "content": "Elegís la estación, cambiás de fecha y ves altura actual, próximas referencias y evolución diaria sin salir de la misma pantalla.",
            },
            {
                "title": "De dónde sale la información",
                "content": "Los datos cargados en esta versión se actualizan con alturas del INA y meteorología del SMN, guardados localmente dentro de la app.",
            },
            {
                "title": "Tecnologías",
                "content": "La app nueva mantiene Django templates para la interfaz y mueve la lectura, transformación y normalización de datos reales a servicios separados en mareas/services.",
            },
            {
                "title": "Datos y archivos",
                "content": "El catálogo de estaciones y los JSON por estación viven dentro del proyecto nuevo para que Mareas funcione de forma autónoma en tiempo de ejecución.",
            },
            {
                "title": "Actualización",
                "content": "La última actualización visible usa la fecha real del archivo cacheado de cada estación. Si una fuente no estuviera disponible, el sistema conserva fallback controlado.",
            },
            {
                "title": "Detalle técnico",
                "content": "Los bloques visibles muestran solo datos confirmados por las fuentes oficiales cargadas. Si un campo no existe todavia en una fuente confiable, la interfaz lo oculta.",
            },
        ]

        context = {
            "title": "Mareas",
            "description": "Herramienta web para consultar alturas de marea, datos meteorológicos y próximos días.",
            "stations": stations,
            "default_station": active_station["key"],
            "active_station": active_station,
            "active_day": active_day,
            "days": active_station["days"],
            "visual_moment": get_visual_moment(),
            "technical_sections": technical_sections,
        }

        if load_errors:
            context["source_warning"] = " | ".join(load_errors)

        return context
    except Exception as exc:
        logger.exception("Falling back to simulated Mareas data")
        return _get_fallback_context(str(exc))


def _get_fallback_context(error_message):
    fallback_day = {
        "slug": "fallback",
        "label": "Hoy",
        "date_label": "--",
        "state": "Pendiente",
        "height_now": "-- m",
        "height_change": "Sin datos reales disponibles",
        "next_high": "--:--",
        "next_low": "--:--",
        "temperature": "Sin dato",
        "wind": "Sin dato",
        "sky": "Sin dato",
        "has_sky": False,
        "rain": "Sin dato",
        "updated_at": "--/-- --:--",
        "is_simulated": True,
        "current_marker": {"time": "12:00", "label": "Ahora", "height": 0.0},
        "next_high_marker": {"time": "18:00", "label": "Pleamar", "height": 0.4},
        "next_low_marker": {"time": "06:00", "label": "Bajamar", "height": -0.1},
        "chart_points": [
            {"time": "00", "height": 0.1},
            {"time": "03", "height": 0.0},
            {"time": "06", "height": -0.1},
            {"time": "09", "height": 0.0},
            {"time": "12", "height": 0.1},
            {"time": "15", "height": 0.2},
            {"time": "18", "height": 0.4},
            {"time": "21", "height": 0.2},
        ],
        "chart_min_points": [
            {"time": "00:00", "height": 0.0},
            {"time": "03:00", "height": -0.1},
            {"time": "06:00", "height": -0.2},
            {"time": "09:00", "height": -0.1},
            {"time": "12:00", "height": 0.0},
            {"time": "15:00", "height": 0.1},
            {"time": "18:00", "height": 0.2},
            {"time": "21:00", "height": 0.1},
        ],
        "chart_max_points": [
            {"time": "00:00", "height": 0.2},
            {"time": "03:00", "height": 0.1},
            {"time": "06:00", "height": 0.0},
            {"time": "09:00", "height": 0.1},
            {"time": "12:00", "height": 0.2},
            {"time": "15:00", "height": 0.3},
            {"time": "18:00", "height": 0.5},
            {"time": "21:00", "height": 0.3},
        ],
        "table_rows": [
            {"time": "00:00", "min": "0.00 m", "avg": "0.10 m", "max": "0.20 m"},
            {"time": "03:00", "min": "-0.10 m", "avg": "0.00 m", "max": "0.10 m"},
            {"time": "06:00", "min": "-0.20 m", "avg": "-0.10 m", "max": "0.00 m"},
            {"time": "09:00", "min": "-0.10 m", "avg": "0.00 m", "max": "0.10 m"},
            {"time": "12:00", "min": "0.00 m", "avg": "0.10 m", "max": "0.20 m"},
            {"time": "15:00", "min": "0.10 m", "avg": "0.20 m", "max": "0.30 m"},
            {"time": "18:00", "min": "0.20 m", "avg": "0.40 m", "max": "0.50 m"},
            {"time": "21:00", "min": "0.10 m", "avg": "0.20 m", "max": "0.30 m"},
        ],
    }
    fallback_station = {
        "key": "san_fernando",
        "name": "San Fernando",
        "days": [fallback_day],
        "source_status_label": "Datos simulados",
        "source_status_detail": "No se pudo cargar la fuente real.",
    }

    return {
        "title": "Mareas",
        "description": "Herramienta web para consultar alturas de marea, datos meteorologicos y proximos dias.",
        "stations": [fallback_station],
        "default_station": "san_fernando",
        "active_station": fallback_station,
        "active_day": fallback_day,
        "days": fallback_station["days"],
        "visual_moment": get_visual_moment(),
        "technical_sections": [
            {
                "title": "Estado de la fuente",
                "content": f"No se pudo cargar la fuente real: {error_message}",
            }
        ],
        "source_warning": error_message,
    }
