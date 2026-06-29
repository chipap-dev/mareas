import json
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
STATIONS_FILE = DATA_DIR / "estaciones.json"


def load_station_catalog():
    with STATIONS_FILE.open("r", encoding="utf-8") as handle:
        raw_items = json.load(handle)

    stations = []
    for item in raw_items:
        stations.append(
            {
                "key": item["id"],
                "name": item["nombre"],
                "series_id": item["series_id"],
                "site_code": item["site_code"],
                "cal_id": item["cal_id"],
                "pronostico_id": item.get("pronostico_id"),
            }
        )

    return stations
