# Mareas - Tide & Weather Dashboard

A Django app that displays live tide height and weather data for Argentine river stations, sourced from two official APIs (INA and SMN), with a BigQuery + dbt + Airflow layer behind it for historical analysis.

I check tide levels here myself.

**No database. No configuration. Clone and run.**

---

## What it does

- Current tide height, trend (rising / falling / stable), and next high/low tide
- Weather: temperature, wind speed & direction, rainfall
- SVG tide chart, hand-built in vanilla JS
- 3 stations: San Fernando, Rosario, Zárate - the ones with the most people living along the river, San Fernando especially (up to 4 days of forecast)
- Visual theme shifts with time of day (dawn / day / sunset / night)

---

## Data pipeline

```
INA API + SMN feed → local JSON cache → Django app (live)
                    ↘ BigQuery (raw) → dbt → mart → Airflow (daily)
```

- The live dashboard reads a local per-station JSON cache: zero added latency, no dependency on the warehouse
- A separate loader appends incrementally into BigQuery (no DML - the BigQuery sandbox doesn't allow it; checks what's already loaded and only adds what's missing), building a real time series instead of a rolling snapshot
- dbt builds two staging models (INA, SMN) and one mart, `mareas_por_estacion`, joining tide and weather by station/date/hour
- Tests cover freshness, duplicates, and forecast staleness
- Airflow runs the pipeline daily: refresh → load → `dbt run` → `dbt test`

![Airflow DAG run](static/img/pipeline/airflow_dag_exitoso.png)
![dbt lineage graph](static/img/pipeline/dbt_lineage.png)
![dbt docs: mareas_por_estacion model](static/img/pipeline/dbt_database.png)

See [`dbt_mareas/README.md`](dbt_mareas/README.md) for the full dbt setup.

---

## Stack

Python 3.11 · Django 4.2 · Vanilla JS · CSS custom properties

Data layer: BigQuery · dbt · Airflow · Docker

---

## Architecture

```
mareas/
├── services/
│   ├── stations.py         # station catalog
│   ├── refresh.py          # fetches INA + SMN
│   ├── transform.py        # interpolation, extremes, merge
│   ├── landing.py          # view context
│   └── bigquery_export.py
└── management/commands/     # mareas_actualizar_datos, mareas_cargar_bigquery

dbt_mareas/         # staging + mart models on mareas_raw
airflow_dags/        # mareas_dag.py
```

---

## Run locally

```bash
git clone https://github.com/chipap-dev/mareas.git
cd mareas
python -m venv venv
source venv/bin/activate      # venv\Scripts\activate on Windows
pip install -r requirements_mareas.txt
python manage.py runserver
```

Open [http://localhost:8000](http://localhost:8000): loads instantly from the cached data already in the repo.

```bash
python manage.py mareas_actualizar_datos   # refresh live data
```

To run the BigQuery + dbt layer, see [`dbt_mareas/README.md`](dbt_mareas/README.md).

---

Built by [Claudia Cáceres](https://chipap.net) · [LinkedIn](https://linkedin.com/in/claudiacaceresv) · Buenos Aires, Argentina
