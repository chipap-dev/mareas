# Mareas — Tide & Weather Dashboard

A Django app that displays tide heights and weather data for Argentine river stations.  
Data comes from two official sources: INA (Instituto Nacional del Agua) and SMN (Servicio Meteorológico Nacional).

**No database. No configuration. Clone and run.**

---

## What it does

- Current tide height, trend (rising / falling / stable), and next high/low tide
- Weather data: temperature, wind speed & direction, rainfall
- SVG chart built in vanilla JS — no visualization library
- 3 stations: San Fernando, Rosario, Zárate
- Up to 4 days of forecast
- Visual theme changes based on time of day (dawn / day / sunset / night)

---

## Run locally

Requirements: Python 3.11+

**Linux / Mac:**
```bash
git clone https://github.com/chipap-dev/mareas.git
cd mareas
python -m venv venv
source venv/bin/activate
pip install -r requirements_mareas.txt
python manage_mareas.py runserver
```

**Windows (Git Bash):**
```bash
git clone https://github.com/chipap-dev/mareas.git
cd mareas
python -m venv venv
source venv/Scripts/activate
pip install -r requirements_mareas.txt
python manage_mareas.py runserver
```

**Windows (CMD / PowerShell):**
```bat
git clone https://github.com/chipap-dev/mareas.git
cd mareas
python -m venv venv
venv\Scripts\activate
pip install -r requirements_mareas.txt
python manage_mareas.py runserver
```

Open [http://localhost:8000](http://localhost:8000)

The app loads with cached data already included in the repo. No API calls needed.

---

## Refresh data (optional)

```bash
cd mareas
python manage_mareas.py mareas_actualizar_datos
```

Other commands:

```bash
python manage_mareas.py mareas_listar_estaciones   # list stations and cache status
python manage_mareas.py mareas_validar_fuente      # validate cache integrity
python manage_mareas.py mareas_ver_contexto        # inspect the full rendered context
```

---

## Architecture

No ORM, no migrations, no database.

```
mareas/
├── services/
│   ├── stations.py    # station catalog from JSON
│   ├── source.py      # per-station JSON cache
│   ├── refresh.py     # fetches INA REST API + SMN ZIP/TXT
│   ├── transform.py   # interpolates height, detects extremes, merges weather
│   ├── landing.py     # builds view context with controlled fallback
│   └── data/
│       ├── estaciones.json
│       └── cache/     # one JSON file per station
├── views/
│   ├── index.py
│   └── actualizar.py  # token-protected endpoint for scheduled refresh
└── management/commands/
```

Data pipeline: INA REST JSON + SMN ZIP/TXT → grouped & merged → local JSON cache → transform layer → Django template

---

## Stack

Python 3.11 · Django 4.2 · Whitenoise · Vanilla JS · CSS custom properties · `urllib`

---

Built by [Claudia Cáceres](https://chipap.net) · [LinkedIn](https://linkedin.com/in/claudiacaceresv) · Buenos Aires, Argentina
