# dbt_mareas

Proyecto dbt para el layer historico de Mareas en BigQuery
(`mareas_raw.lecturas` → staging → mart). Independiente del venv de la
app Django - ver la sección "Data pipeline" del README principal del
repo para el contexto completo.

## Setup (venv aislado)

`dbt-bigquery` **no** se instala en el Python global del sistema ni en
el venv de Django. Vive en un venv propio, exclusivo de esta carpeta:

**Git Bash / Linux / Mac:**
```bash
cd dbt_mareas
python -m venv .venv
source .venv/Scripts/activate   # Git Bash en Windows
# source .venv/bin/activate     # Linux / Mac
pip install dbt-bigquery
```

**Windows (CMD / PowerShell):**
```bat
cd dbt_mareas
python -m venv .venv
.venv\Scripts\activate
pip install dbt-bigquery
```

`dbt_mareas/.venv/` está en `.gitignore` (regla `.venv/` ya existente en
el `.gitignore` del repo).

## Credenciales

```bash
cp profiles.yml.example profiles.yml
```

`profiles.yml` ya viene con los valores reales de infra (`project:
chipap`, `dataset: mareas_raw`, `location: us-central1`, `keyfile:
../secrets/gcp-key.json`) - no hace falta editarlo salvo que cambie la
ubicación de la key. Nunca se commitea (`dbt_mareas/profiles.yml` está
en `.gitignore`).

## Comandos

Con el venv activado, parado en `dbt_mareas/`:

```bash
dbt parse             # chequeo de sintaxis, no requiere credenciales validas
dbt compile           # compila el SQL final
dbt run               # materializa staging (views) + mart (table)
dbt test              # not_null / accepted_values + tests de contenido (ver mas abajo)
dbt source freshness  # freshness de carga sobre mareas_raw.lecturas
dbt docs generate
```

## Modelos

Solo San Fernando llega a BigQuery (`mareas_cargar_bigquery --station
san_fernando`, ver `airflow_dags/mareas_dag.py`): Rosario/Zárate se
siguen sirviendo en vivo desde el cache JSON local, pero no entran a
esta capa - no aportaban historico real (su modelo INA esta stale) y
no tenia sentido pagar por cargarlas.

```
models/
├── staging/
│   ├── sources.yml        # declara mareas_raw.lecturas (San Fernando) como source,
│   │                       # con freshness directa
│   ├── stg_mareas_ina.sql # filas fuente_origen = 'ina', dedup por qualify (ver abajo)
│   └── stg_mareas_smn.sql # filas fuente_origen = 'smn', dedup por qualify (ver abajo)
└── marts/
    ├── mareas_por_estacion.sql  # combina ambos staging por estacion+fecha+hora
    └── schema.yml               # tests: not_null / accepted_values

tests/
├── assert_san_fernando_pronostico_reciente.sql  # severity=error: su modelo INA corre a diario
└── assert_staging_sin_duplicados.sql            # confirma que el dedup de staging no dejo duplicados
```

`mareas_cargar_bigquery` carga append-only (sin MERGE, sin DML - el
sandbox de BigQuery no lo permite, ver docs/decisiones_carga_
incremental_bigquery.md): antes de cargar consulta que
`estacion+fecha+hora+fuente_origen` ya existe, y solo agrega lo que
falta con `WRITE_APPEND`, asi que el raw no deberia acumular duplicados
en uso normal. El lado INA ademas solo carga fecha+hora con mas de 48h
de antiguedad (margen de asentamiento). El `qualify row_number()` en
los staging models es la unica red de seguridad restante contra un
duplicado: sin MERGE no hay ninguna restriccion de unicidad a nivel de
base de datos.

`dbt source freshness` mide cuando se **cargo** cada fila
(`marca_temporal_carga`), no cuando INA genero el pronostico - el loader
re-sube el cache completo todos los dias aunque su contenido no haya
cambiado. Por eso la señal real de "el pronostico de INA no avanza" es
el test de contenido `assert_san_fernando_pronostico_reciente.sql`, no
la freshness del source. Ver la sección "Data pipeline" del README
principal para el contexto completo (el caso real de Rosario/Zárate
detectado el 2026-07-22, y por que quedaron fuera de esta capa).
