from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")
DAY_LABELS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MONTH_LABELS = {
    1: "Ene",
    2: "Feb",
    3: "Mar",
    4: "Abr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dic",
}
WEATHER_PLACEHOLDER = "Sin dato"


def get_visual_moment(current_time=None):
    current_time = current_time or datetime.now(BUENOS_AIRES)
    hour = current_time.hour
    if 5 <= hour < 8:
        return "amanecer"
    if 8 <= hour < 18:
        return "dia"
    if 18 <= hour < 21:
        return "atardecer"
    return "noche"


def build_station_payload(station_config, records, updated_at, *, current_time=None):
    current_time = current_time or datetime.now(BUENOS_AIRES)
    day_records = _group_records_by_day(records)
    today = current_time.date()
    available_dates = [d for d in sorted(day_records.keys()) if d >= today]
    if not available_dates:
        raise ValueError(f"No records available for station '{station_config['key']}'")

    days = []
    missing_fields = set()

    for day_date in available_dates[:4]:
        day_payload, day_missing = _build_day_payload(
            day_date=day_date,
            records=day_records[day_date],
            updated_at=updated_at,
            current_time=current_time,
        )
        days.append(day_payload)
        missing_fields.update(day_missing)

    source_status_label = "Datos reales" if not missing_fields else "Datos parciales"
    source_status_detail = (
        "Fuente real cacheada desde INA y SMN."
        if not missing_fields
        else f"Fuente real con campos pendientes: {', '.join(sorted(missing_fields))}."
    )

    return {
        "key": station_config["key"],
        "name": station_config["name"],
        "days": days,
        "source_status_label": source_status_label,
        "source_status_detail": source_status_detail,
    }


def _build_day_payload(day_date, records, updated_at, *, current_time):
    sorted_records = sorted(records, key=lambda item: item["hour_value"])
    sample_points = _build_chart_points(sorted_records, "height_value")
    sample_min_points = _build_chart_points(sorted_records, "altura_minima")
    sample_max_points = _build_chart_points(sorted_records, "altura_maxima")
    table_rows = _build_table_rows(sorted_records)
    if not sample_points:
        raise ValueError(f"No chart points available for {day_date.isoformat()}")

    reference_hour = _reference_hour_for_day(day_date, sorted_records, current_time)
    current_height = _interpolate(sorted_records, reference_hour)
    previous_height = _interpolate(sorted_records, max(0.0, reference_hour - 1.0))
    state_delta = current_height - previous_height

    high_event = _find_day_extreme(sorted_records, find_high=True)
    low_event = _find_day_extreme(sorted_records, find_high=False)
    weather = _build_weather_snapshot(sorted_records, reference_hour)

    missing_fields = set()

    return (
        {
            "slug": day_date.isoformat(),
            "label": _day_label(day_date, current_time.date()),
            "date_label": _date_label(day_date),
            "state": _state_label(state_delta),
            "height_now": _format_height(current_height),
            "height_change": _format_change(current_height - previous_height),
            "next_high": high_event["time"],
            "next_low": low_event["time"],
            "temperature": weather["temperature"],
            "wind": weather["wind"],
            "sky": weather["sky"],
            "has_sky": weather["sky"] != WEATHER_PLACEHOLDER,
            "rain": weather["rain"],
            "updated_at": updated_at.astimezone(BUENOS_AIRES).strftime("%d/%m %H:%M"),
            "is_simulated": False,
            "current_marker": {
                "time": _format_hour_label(reference_hour),
                "label": "Ahora",
                "height": round(current_height, 2),
            },
            "next_high_marker": {
                "time": high_event["time"],
                "label": "Pleamar",
                "height": round(high_event["height"], 2),
            },
            "next_low_marker": {
                "time": low_event["time"],
                "label": "Bajamar",
                "height": round(low_event["height"], 2),
            },
            "chart_points": sample_points,
            "chart_min_points": sample_min_points,
            "chart_max_points": sample_max_points,
            "table_rows": table_rows,
        },
        missing_fields,
    )


def _group_records_by_day(records):
    grouped = defaultdict(list)
    for record in records:
        day_date = datetime.strptime(record["fecha"], "%Y-%m-%d").date()
        hour_value = _parse_hour_to_float(record["hora"])
        grouped[day_date].append(
            {
                **record,
                "day_date": day_date,
                "hour_value": hour_value,
                "height_value": _to_float(record.get("altura_promedio")),
            }
        )

    return grouped


def _build_chart_points(records, field_name):
    seen_times = set()
    chart_points = []
    for record in records:
        time_label = record["hora"][:5]
        if time_label in seen_times:
            continue
        seen_times.add(time_label)
        value = record.get(field_name)
        if field_name != "height_value":
            value = _to_float(value)
        chart_points.append(
            {
                "time": time_label,
                "height": round(value if value is not None else record["height_value"], 2),
            }
        )

    return chart_points


def _build_table_rows(records):
    rows = []
    seen_times = set()
    for record in records:
        time_label = record["hora"][:5]
        if time_label in seen_times:
            continue
        seen_times.add(time_label)
        rows.append(
            {
                "time": time_label,
                "min": _format_height(_to_float(record.get("altura_minima")) or record["height_value"]),
                "avg": _format_height(record["height_value"]),
                "max": _format_height(_to_float(record.get("altura_maxima")) or record["height_value"]),
            }
        )
    return rows


def _reference_hour_for_day(day_date, records, current_time):
    max_hour = records[-1]["hour_value"]
    if day_date == current_time.date():
        return min(max_hour, current_time.hour + current_time.minute / 60)

    candidate = current_time.hour + current_time.minute / 60
    if records[0]["hour_value"] <= candidate <= max_hour:
        return candidate

    return min(12.0, max_hour)


def _interpolate(records, target_hour):
    if target_hour <= records[0]["hour_value"]:
        return records[0]["height_value"]
    if target_hour >= records[-1]["hour_value"]:
        return records[-1]["height_value"]

    for current_record, next_record in zip(records, records[1:]):
        start = current_record["hour_value"]
        end = next_record["hour_value"]
        if start <= target_hour <= end:
            span = end - start
            if span == 0:
                return current_record["height_value"]
            ratio = (target_hour - start) / span
            return current_record["height_value"] + (
                (next_record["height_value"] - current_record["height_value"]) * ratio
            )

    return records[-1]["height_value"]


def _find_day_extreme(records, *, find_high):
    points = [{"hour": item["hour_value"], "height": item["height_value"]} for item in records]
    selected = max(points, key=lambda p: p["height"]) if find_high else min(points, key=lambda p: p["height"])
    return {"time": _format_hour_label(selected["hour"]), "height": selected["height"]}


def _find_next_extreme(records, reference_hour, *, find_high):
    points = [{"hour": item["hour_value"], "height": item["height_value"]} for item in records]
    extrema = []
    for index, point in enumerate(points):
        left_height = points[index - 1]["height"] if index > 0 else None
        right_height = points[index + 1]["height"] if index < len(points) - 1 else None

        is_extreme = False
        if find_high:
            if left_height is not None and right_height is not None:
                is_extreme = point["height"] >= left_height and point["height"] >= right_height
            elif left_height is None and right_height is not None:
                is_extreme = point["height"] >= right_height
            elif left_height is not None and right_height is None:
                is_extreme = point["height"] >= left_height
        else:
            if left_height is not None and right_height is not None:
                is_extreme = point["height"] <= left_height and point["height"] <= right_height
            elif left_height is None and right_height is not None:
                is_extreme = point["height"] <= right_height
            elif left_height is not None and right_height is None:
                is_extreme = point["height"] <= left_height

        if is_extreme:
            extrema.append(point)

    future_extrema = [point for point in extrema if point["hour"] >= reference_hour]
    selected = future_extrema[0] if future_extrema else (
        max(points, key=lambda item: item["height"]) if find_high else min(points, key=lambda item: item["height"])
    )

    return {
        "time": _format_hour_label(selected["hour"]),
        "height": selected["height"],
    }


def _build_weather_snapshot(records, reference_hour):
    def nearest_with_value(field_name):
        candidates = [item for item in records if _to_float(item.get(field_name)) is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda item: abs(item["hour_value"] - reference_hour))

    temperature_record = nearest_with_value("temperatura")
    wind_record = nearest_with_value("viento_km_h")
    rain_record = nearest_with_value("precipitacion_mm")

    temperature = WEATHER_PLACEHOLDER
    if temperature_record:
        temperature = _format_number(temperature_record["temperatura"], suffix=" C")

    wind = WEATHER_PLACEHOLDER
    if wind_record:
        wind_speed = _format_number(wind_record["viento_km_h"], suffix=" km/h", decimals=0)
        wind_direction = (wind_record.get("viento_direccion_abreviatura") or "").strip()
        wind = f"{wind_speed} {wind_direction}".strip()

    rain = WEATHER_PLACEHOLDER
    if rain_record:
        rain = _format_number(rain_record["precipitacion_mm"], suffix=" mm")

    return {
        "temperature": temperature,
        "wind": wind,
        "sky": WEATHER_PLACEHOLDER,
        "rain": rain,
    }


def _day_label(day_date, today):
    if day_date == today:
        return "Hoy"
    if day_date == today + timedelta(days=1):
        return "Mañana"
    return DAY_LABELS[day_date.weekday()]


def _date_label(day_date):
    return f"{day_date.day:02d} {MONTH_LABELS[day_date.month]}"


def _state_label(delta):
    if delta > 0.03:
        return "Subiendo"
    if delta < -0.03:
        return "Bajando"
    return "Estable"


def _format_height(value):
    return f"{value:.2f} m"


def _format_change(delta):
    sign = "+" if delta >= 0 else "-"
    return f"{sign}{abs(delta):.2f} m en la ultima hora"


def _format_number(value, *, suffix="", decimals=1):
    numeric = _to_float(value)
    if numeric is None:
        return WEATHER_PLACEHOLDER

    if decimals == 0 or float(numeric).is_integer():
        rendered = str(int(round(numeric)))
    else:
        rendered = f"{numeric:.{decimals}f}"
    return f"{rendered}{suffix}"


def _parse_hour_to_float(raw_value):
    hour_string = raw_value[:5]
    parsed_time = datetime.strptime(hour_string, "%H:%M").time()
    return parsed_time.hour + parsed_time.minute / 60


def _format_hour_label(hour_value):
    base = datetime.combine(date.today(), time.min) + timedelta(hours=hour_value)
    return base.strftime("%H:%M")


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    return None
