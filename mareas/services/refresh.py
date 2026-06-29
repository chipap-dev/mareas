import io
import json
import logging
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .source import CACHE_DIR, load_station_cache
from .stations import load_station_catalog


logger = logging.getLogger(__name__)

SMN_URL = "https://ssl.smn.gob.ar/dpd/zipopendata.php?dato=pron5d"
USER_AGENT = "Mozilla/5.0"
PRON_COLS = [
    "temperatura",
    "viento_direccion",
    "viento_direccion_abreviatura",
    "viento_direccion_nombre",
    "viento_direccion_grados",
    "viento_km_h",
    "precipitacion_mm",
]
DIRECCIONES_VIENTO = [
    ("N", "Norte", 0.0),
    ("NE", "Nordeste", 45.0),
    ("E", "Este", 90.0),
    ("SE", "Sudeste", 135.0),
    ("S", "Sur", 180.0),
    ("SO", "Suroeste", 225.0),
    ("O", "Oeste", 270.0),
    ("NO", "Noroeste", 315.0),
]


def _request_bytes(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=45) as response:
        return response.read()


def _normalize_station_name(value):
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _is_separator(value):
    return re.fullmatch(r"\s*=+\s*", value or "") is not None


def _parse_spanish_date(value):
    match = re.match(r"^(\d{2})/([A-Z]{3})/(\d{4})$", value.strip().upper())
    if not match:
        return None

    day, month_abbr, year = match.groups()
    months = {
        "ENE": 1,
        "FEB": 2,
        "MAR": 3,
        "ABR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AGO": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DIC": 12,
    }
    month = months.get(month_abbr)
    if month is None:
        return None
    return datetime(int(year), month, int(day)).date()


def _convert_wind_direction(value):
    for abbreviation, name, angle in DIRECCIONES_VIENTO:
        lower = (angle - 22.5) % 360
        upper = (angle + 22.5) % 360
        if lower < upper:
            if lower <= value < upper:
                return abbreviation, name, angle
        elif value >= lower or value < upper:
            return abbreviation, name, angle
    return "N", "Norte", 0.0


def _decode_text(raw_bytes):
    for encoding in ["latin1", "utf-8", "cp1252", "utf-16", "utf-16le", "utf-16be"]:
        try:
            decoded = raw_bytes.decode(encoding, errors="ignore")
        except UnicodeDecodeError:
            continue
        if decoded.splitlines():
            return decoded
    return ""


def fetch_smn_forecast(stations):
    pronostico_ids = [item.get("pronostico_id") for item in stations if item.get("pronostico_id")]
    if not pronostico_ids:
        return {"ok": False, "records": [], "error": "No hay pronostico_id configurados."}

    try:
        payload = _request_bytes(SMN_URL)
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.warning("No se pudo descargar pronostico SMN: %s", exc)
        return {"ok": False, "records": [], "error": str(exc)}

    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            txt_names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
            if not txt_names:
                return {"ok": False, "records": [], "error": "ZIP del SMN sin TXT interno."}
            raw_txt = archive.read(txt_names[0])
    except zipfile.BadZipFile as exc:
        logger.warning("ZIP invalido desde SMN: %s", exc)
        return {"ok": False, "records": [], "error": "ZIP invalido del SMN."}

    content = _decode_text(raw_txt)
    if not content:
        return {"ok": False, "records": [], "error": "No se pudo decodificar el TXT del SMN."}

    lines = content.splitlines()
    headers = []
    for index, line in enumerate(lines):
        if not re.fullmatch(r"\s*[A-Z0-9_]+(?:\s+[A-Z0-9_]+)*\s*", line or ""):
            continue
        before_1 = lines[index - 1] if index - 1 >= 0 else ""
        before_2 = lines[index - 2] if index - 2 >= 0 else ""
        after_1 = lines[index + 1] if index + 1 < len(lines) else ""
        after_2 = lines[index + 2] if index + 2 < len(lines) else ""
        if (_is_separator(before_1) or _is_separator(before_2)) and (
            _is_separator(after_1) or _is_separator(after_2)
        ):
            headers.append((_normalize_station_name(line), index))

    header_positions = {position for _, position in headers}
    row_pattern = re.compile(
        r"(\d{2}/[A-Z]{3}/\d{4})\s+(\d{2})Hs\.\s+([-]?\d+(?:\.\d+)?)"
        r"\s+([A-Z]{1,3}|\d+)\s*\|\s*(\d+)\s+([\d\.]+)"
    )
    by_station = {}

    for station_name in pronostico_ids:
        normalized = _normalize_station_name(station_name)
        header_index = next((idx for name, idx in headers if name == normalized), None)
        if header_index is None:
            continue

        cursor = header_index + 1
        while cursor < len(lines) and (not lines[cursor].strip() or _is_separator(lines[cursor])):
            cursor += 1

        block_lines = []
        while cursor < len(lines):
            if cursor in header_positions and cursor != header_index:
                break
            current = lines[cursor]
            if current.strip() and not any(
                token in current for token in ["FECHA", "TEMPERATURA", "VIENTO", "PRECIPITACION"]
            ):
                block_lines.append(current)
            cursor += 1

        station_records = []
        for date_raw, hour_raw, temp_raw, wind_dir_raw, wind_speed_raw, rain_raw in row_pattern.findall(
            "\n".join(block_lines)
        ):
            date_obj = _parse_spanish_date(date_raw)
            if date_obj is None:
                continue

            try:
                degrees = float(wind_dir_raw.replace(",", "."))
                abbreviation, name, base_angle = _convert_wind_direction(degrees)
            except ValueError:
                wind_lookup = {abbr: (full_name, angle) for abbr, full_name, angle in DIRECCIONES_VIENTO}
                full_name, base_angle = wind_lookup.get(wind_dir_raw.strip().upper(), ("Norte", 0.0))
                abbreviation = wind_dir_raw.strip().upper() if wind_dir_raw.strip().upper() in wind_lookup else "N"
                degrees = float(base_angle)

            station_records.append(
                {
                    "fecha": date_obj.isoformat(),
                    "hora": f"{hour_raw}:00:00",
                    "temperatura": float(temp_raw),
                    "viento_direccion": degrees,
                    "viento_direccion_abreviatura": abbreviation,
                    "viento_direccion_nombre": name,
                    "viento_direccion_grados": base_angle,
                    "viento_km_h": int(wind_speed_raw),
                    "precipitacion_mm": float(rain_raw),
                }
            )
        by_station[station_name] = station_records

    return {"ok": True, "records": by_station, "error": None}


def _build_ina_url(station, start_date, end_date):
    return (
        "https://alerta.ina.gob.ar/pub/datos/datosProno"
        f"&timeStart={start_date:%Y-%m-%d}"
        f"&timeEnd={end_date:%Y-%m-%d}"
        f"&seriesId={station['series_id']}"
        f"&calId={station['cal_id']}"
        f"&all=false&siteCode={station['site_code']}"
        "&varId=2&format=json"
    )


def _load_previous_weather(station_key):
    try:
        records, _updated_at, _path = load_station_cache(station_key)
    except FileNotFoundError:
        return {}

    previous = {}
    for row in records:
        key = (row.get("fecha"), row.get("hora"))
        previous[key] = {column: row.get(column) for column in PRON_COLS}
    return previous


def _group_ina_rows(rows, start_date):
    grouped = {}
    for item in rows:
        timestamp = datetime.fromisoformat(item["timestart"])
        key = (timestamp.date().isoformat(), timestamp.time().isoformat())
        bucket = grouped.setdefault(
            key,
            {
                "fecha": key[0],
                "hora": key[1],
                "altura_minima": None,
                "altura_maxima": None,
                "altura_promedio": None,
            },
        )
        value = item["valor"]
        bucket["altura_minima"] = value if bucket["altura_minima"] is None else min(bucket["altura_minima"], value)
        bucket["altura_maxima"] = value if bucket["altura_maxima"] is None else max(bucket["altura_maxima"], value)
        if bucket["altura_promedio"] is None:
            bucket["altura_promedio"] = [value]
        else:
            bucket["altura_promedio"].append(value)

    normalized = []
    for record in grouped.values():
        values = record["altura_promedio"]
        record["altura_promedio"] = round(sum(values) / len(values), 2)
        normalized.append(record)

    synthetic = []
    start_boundary = datetime.combine(start_date, datetime.min.time())
    for record in normalized:
        if record["hora"] != "00:00:00":
            continue
        current = datetime.fromisoformat(f"{record['fecha']}T{record['hora']}")
        if current <= start_boundary:
            continue
        cloned = record.copy()
        shifted = current - timedelta(minutes=1)
        cloned["fecha"] = shifted.date().isoformat()
        cloned["hora"] = shifted.time().isoformat()
        synthetic.append(cloned)

    all_rows = normalized + synthetic
    all_rows.sort(key=lambda item: (item["fecha"], item["hora"]))
    return all_rows


def _merge_weather(station_key, station, tide_rows, forecast_result):
    previous_weather = _load_previous_weather(station_key)
    forecast_rows = {}
    if forecast_result["ok"]:
        for row in forecast_result["records"].get(station.get("pronostico_id"), []):
            forecast_rows[(row["fecha"], row["hora"])] = row

    merged = []
    for row in tide_rows:
        key = (row["fecha"], row["hora"])
        weather = forecast_rows.get(key) or previous_weather.get(key) or {}
        full_row = row.copy()
        for column in PRON_COLS:
            full_row[column] = weather.get(column)
        merged.append(full_row)
    return merged


def _filter_window(rows, start_date):
    last_full = start_date + timedelta(days=3)
    first_next = start_date + timedelta(days=4)
    filtered = []
    seen = set()
    for row in rows:
        row_date = datetime.fromisoformat(row["fecha"]).date()
        keep = row_date <= last_full or (row_date == first_next and row["hora"] == "00:00:00")
        if not keep:
            continue
        key = (row["fecha"], row["hora"])
        if key in seen:
            continue
        seen.add(key)
        filtered.append(row)
    return filtered


def refresh_station_data(station, forecast_result, now=None):
    now = now or datetime.now()
    start_date = now.date()
    end_date = start_date + timedelta(days=4)
    url = _build_ina_url(station, start_date, end_date)

    try:
        raw_payload = _request_bytes(url)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"INA no disponible para {station['key']}: {exc}") from exc

    try:
        parsed = json.loads(raw_payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON invalido del INA para {station['key']}: {exc}") from exc

    data = parsed.get("data", [])
    if not data:
        raise RuntimeError(f"INA no devolvio datos para {station['key']}.")

    grouped = _group_ina_rows(data, start_date)
    merged = _merge_weather(station["key"], station, grouped, forecast_result)
    filtered = _filter_window(merged, start_date)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"marea_{station['key']}.json"
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump({"datos": filtered}, handle, ensure_ascii=False, indent=2)

    return {
        "key": station["key"],
        "name": station["name"],
        "records": len(filtered),
        "cache_path": str(cache_path),
        "weather_source": "SMN" if forecast_result["ok"] else "cache previo",
    }


def refresh_all_station_data(station_key=None):
    stations = load_station_catalog()
    selected = [station for station in stations if station_key in (None, station["key"])]
    if not selected:
        raise ValueError(f"Estacion desconocida: {station_key}")

    forecast_result = fetch_smn_forecast(selected)
    results = []
    errors = []

    for station in selected:
        try:
            results.append(refresh_station_data(station, forecast_result))
        except Exception as exc:
            logger.exception("Error actualizando %s", station["key"])
            errors.append({"key": station["key"], "error": str(exc)})

    return {
        "ok": not errors,
        "forecast_ok": forecast_result["ok"],
        "forecast_error": forecast_result["error"],
        "results": results,
        "errors": errors,
    }
