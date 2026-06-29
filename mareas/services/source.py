import json
from datetime import datetime
from pathlib import Path

from .stations import DATA_DIR


CACHE_DIR = DATA_DIR / "cache"


def load_station_cache(station_key):
    cache_path = CACHE_DIR / f"marea_{station_key}.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"Cache not found for station '{station_key}'")

    with cache_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    updated_at = datetime.fromtimestamp(cache_path.stat().st_mtime)
    return payload.get("datos", []), updated_at, cache_path
