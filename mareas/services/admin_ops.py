from .landing import get_mareas_context
from .refresh import refresh_all_station_data
from .source import CACHE_DIR, load_station_cache
from .stations import load_station_catalog
from .transform import build_station_payload


def list_stations():
    stations = load_station_catalog()
    output = []
    for station in stations:
        cache_path = CACHE_DIR / f"marea_{station['key']}.json"
        output.append(
            {
                "key": station["key"],
                "name": station["name"],
                "pronostico_id": station.get("pronostico_id"),
                "cache_exists": cache_path.exists(),
                "cache_path": str(cache_path),
            }
        )
    return output


def summarize_cache(station_key=None):
    stations = load_station_catalog()
    selected = [station for station in stations if station_key in (None, station["key"])]
    output = []

    for station in selected:
        records, updated_at, cache_path = load_station_cache(station["key"])
        grouped_days = sorted({item["fecha"] for item in records})
        output.append(
            {
                "key": station["key"],
                "name": station["name"],
                "records": len(records),
                "days": grouped_days,
                "updated_at": updated_at.isoformat(),
                "cache_path": str(cache_path),
            }
        )

    return output


def render_station_payload(station_key, day_slug=None):
    station = next((item for item in load_station_catalog() if item["key"] == station_key), None)
    if station is None:
        raise ValueError(f"Estacion desconocida: {station_key}")

    records, updated_at, _cache_path = load_station_cache(station_key)
    payload = build_station_payload(station, records, updated_at)

    if day_slug is not None:
        day = next((item for item in payload["days"] if item["slug"] == day_slug), None)
        if day is None:
            raise ValueError(f"Dia no encontrado para la estacion {station_key}: {day_slug}")
        return {
            "station": payload["key"],
            "name": payload["name"],
            "source_status_label": payload["source_status_label"],
            "source_status_detail": payload["source_status_detail"],
            "day": day,
        }

    return payload


def summarize_context():
    context = get_mareas_context()
    return {
        "title": context["title"],
        "default_station": context["default_station"],
        "visual_moment": context["visual_moment"],
        "stations": [
            {
                "key": station["key"],
                "name": station["name"],
                "days": len(station["days"]),
                "source_status_label": station["source_status_label"],
            }
            for station in context["stations"]
        ],
        "source_warning": context.get("source_warning"),
    }


def validate_source():
    results = []
    errors = []

    for station in load_station_catalog():
        try:
            records, updated_at, cache_path = load_station_cache(station["key"])
            payload = build_station_payload(station, records, updated_at)
            results.append(
                {
                    "key": station["key"],
                    "records": len(records),
                    "days": len(payload["days"]),
                    "status": payload["source_status_label"],
                    "cache_path": str(cache_path),
                }
            )
        except Exception as exc:
            errors.append({"key": station["key"], "error": str(exc)})

    return {"ok": not errors, "results": results, "errors": errors}

def refresh_real_data(station_key=None):
    return refresh_all_station_data(station_key=station_key)
