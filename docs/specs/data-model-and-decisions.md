# Spec: Data Model and Design Decisions

Status: draft for review · Date: 2026-10-11

This document fixes the decisions the implementation depends on. Code follows this spec;
changes to these decisions are made here first.

## 1. Goal

Produce a dependable, traceable yearly dataset of country indicators from the World Bank
API that analysts can query without knowing the API, with missing data represented
explicitly rather than hidden or coerced to zero.

## 2. Scope

| Dimension  | Value (from `config/pipeline.yml`)                                      |
|------------|-------------------------------------------------------------------------|
| Countries  | BRA, CAN, DEU, GBR, IND, JPN, MEX, USA, ZAF                             |
| Indicators | SP.POP.TOTL, NY.GDP.MKTP.CD, NY.GDP.PCAP.CD, SP.DYN.LE00.IN             |
| Years      | 2018–2024 inclusive                                                     |
| Source     | World Bank API v2, source 2 (World Development Indicators), no API key  |

The expected universe is the cartesian product of the three: 9 × 4 × 7 = 252 cells.
Every one of those cells appears in the final fact table, observed or not.

## 3. Stack

- **Python** for ingestion (HTTP client, paging, retries, raw persistence).
- **DuckDB** as the local warehouse (single file, no server, SQL close to Snowflake).
- **dbt (dbt-duckdb)** for transformations, schema tests and documentation.
- **pytest** for unit and integration tests, using recorded fixtures only.
- **Make** as the single entry point (`make run`, `make test`).

Rationale: every layer maps directly to a production equivalent (DuckDB → Snowflake,
dbt-duckdb → dbt-snowflake, Python ingestion → Glue job / Azure Function / ADF).

## 4. Layers

```
World Bank API
     │  (HTTP, paged JSON)
     ▼
raw.api_response          append-only, one row per HTTP page, payload stored verbatim
     │
     ▼
staging (dbt views)       flatten JSON → typed rows; no business logic
     │
     ▼
marts (dbt tables)        dimensions + fact on a complete spine
     │
     ▼
reports (dbt views)       the four required analytical questions → CSV exports
```

The raw layer is written only by Python. Everything downstream is derived by dbt and
can be rebuilt from raw at any time without calling the API.

## 5. Raw layer

### `raw.api_response`

| Column               | Type      | Notes                                                        |
|----------------------|-----------|--------------------------------------------------------------|
| response_id          | VARCHAR   | PK. sha256 of `request_key` + `payload_sha256`               |
| request_key          | VARCHAR   | Canonical endpoint + sorted query params + page              |
| endpoint             | VARCHAR   | `country` or `indicator`                                     |
| url                  | VARCHAR   | Full URL requested                                           |
| page                 | INTEGER   | Page number requested                                        |
| http_status          | INTEGER   |                                                              |
| payload_sha256       | VARCHAR   | Hash of the raw response body                                |
| source_last_updated  | DATE      | `lastupdated` from response metadata, when present           |
| fetched_at           | TIMESTAMP | UTC                                                          |
| run_id               | VARCHAR   | Pipeline run that fetched it                                 |
| payload              | JSON      | Response body, verbatim                                      |

**Idempotency rule:** a response is inserted only if `(request_key, payload_sha256)`
is new. Re-fetching unchanged source data inserts nothing. A changed payload for the
same request is inserted as a new row; staging selects the latest per `request_key`.

### `raw.pipeline_run`

One row per run: `run_id`, `started_at`, `finished_at`, `status`, `config_sha256`,
counts of pages fetched and pages inserted. Supports auditing and replay.

## 6. Final data model

### `dim_country` — grain: one row per country

| Column            | Key | Notes                                                   |
|-------------------|-----|---------------------------------------------------------|
| country_iso3      | PK  | Business key (e.g. `BRA`)                               |
| country_iso2      |     |                                                         |
| country_name      |     |                                                         |
| region_code       |     |                                                         |
| region_name       |     | Trimmed (the API returns trailing spaces)               |
| income_group_code |     | e.g. `UMC`                                              |
| income_group_name |     | e.g. `Upper middle income`                              |
| response_id       | FK  | → `raw.api_response`                                    |

### `dim_indicator` — grain: one row per indicator

| Column           | Key | Notes                                                    |
|------------------|-----|----------------------------------------------------------|
| indicator_code   | PK  | Business key (e.g. `SP.POP.TOTL`)                        |
| indicator_name   |     | Analyst-facing name from config                          |
| unit             |     | `persons`, `current USD`, `years` (from config)          |
| source_name      |     | From the API                                             |

### `dim_year` — grain: one row per year in scope (from config)

### `fct_indicator_value` — grain: one row per country × indicator × year

| Column               | Key    | Notes                                                    |
|----------------------|--------|----------------------------------------------------------|
| country_iso3         | PK, FK | → `dim_country`                                          |
| indicator_code       | PK, FK | → `dim_indicator`                                        |
| year                 | PK, FK | → `dim_year`                                             |
| value                |        | DOUBLE, **nullable**. Never coerced to 0                 |
| value_status         |        | `observed` · `null_in_source` · `absent_from_source`     |
| obs_status           |        | Source observation flag, passed through                  |
| source_last_updated  |        | From the response that supplied the row                  |
| response_id          | FK     | → `raw.api_response`; NULL only when absent from source  |
| row_hash             |        | Hash of (value, value_status, obs_status)                |

**Built on a spine:** `dim_country × dim_indicator × dim_year`, left-joined to staged
observations. This guarantees all 252 cells exist and distinguishes two kinds of missing:

- `null_in_source` — the API returned the cell with `value: null`.
- `absent_from_source` — the API returned no row for the cell at all.

**Relationships:** `fct_indicator_value` → `dim_country`, `dim_indicator`, `dim_year`
(many-to-one). Every fact row with a value traces to exactly one raw response.

### Idempotency of the fact

The fact is materialized as a dbt incremental model with `unique_key =
(country_iso3, indicator_code, year)` and merge strategy. A row is updated only when
`row_hash` changes, so a re-run on unchanged data produces zero changed rows. This is
asserted by a test.

## 7. Reporting semantics

### 7.1 Missing or incomplete

- **Missing:** a fact row with `value_status <> 'observed'`.
- **Incomplete:** a country × indicator pair with at least one missing year in scope.
  Reported with observed count, missing count and the list of missing years.

### 7.2 Year-over-year change

- Prior value = the same country × indicator at `year - 1` **on the spine**
  (not the previous available year — gaps stay visible).
- `abs_change = value - prior_value`, NULL if either side is NULL.
- `pct_change = (value - prior_value) / ABS(prior_value)`, NULL if either side is
  NULL or `prior_value = 0`.
- `yoy_status`: `ok` · `first_year_in_scope` · `current_missing` · `prior_missing` ·
  `prior_zero`.

### 7.3 Latest available year comparison

Two definitions, both exposed, because "latest" is ambiguous:

- **Per country:** for each country × indicator, the most recent year with an observed
  value. Countries may be compared across different years; the year is shown.
- **Common year:** for each indicator, the most recent year in which *all* countries in
  scope have an observed value. Like-for-like comparison.

Both include a rank across countries per indicator.

### 7.4 Income group comparison by year

- Grouped by `income_group_name` × indicator × year.
- Outputs: `countries_in_group`, `countries_reporting`, `avg_value`, `median_value`,
  `min_value`, `max_value`.
- For additive indicators (population, GDP) also `sum_value`, only when all countries in
  the group report (otherwise NULL, to avoid understated totals).
- Aggregate GDP per capita for the group computed as `sum(GDP) / sum(population)`
  (weighted), alongside the unweighted average.

## 8. Data quality checks

| Check                                   | Severity | Layer   |
|-----------------------------------------|----------|---------|
| Fact grain unique                       | error    | marts   |
| Fact has exactly the expected cell count| error    | marts   |
| Keys not null, FKs resolve              | error    | marts   |
| `value_status` in accepted values       | error    | marts   |
| `value IS NULL` ⇔ status not observed   | error    | marts   |
| Every observed value has a response_id  | error    | marts   |
| Population > 0, GDP > 0                 | error    | marts   |
| Life expectancy in [20, 100]            | error    | marts   |
| GDP per capita ≈ GDP / population       | warn     | marts   |
| Raw payload shape valid                 | error    | ingest  |
| Rows received = `total` in metadata     | error    | ingest  |

GDP per capita consistency: relative difference ≤ configurable tolerance
(default 1%, to be calibrated against recorded data). Warn, not error: the source may
legitimately revise one indicator before another.

## 9. Ingestion behavior

- One request per indicator covering all countries (`country/BRA;CAN;…/indicator/X`),
  `date=2018:2024`, `per_page=1000`, `format=json`, `source=2`. Paged by metadata
  `pages`; loop is generic even if one page usually suffices.
- One request for country metadata (`country/BRA;CAN;…`).
- **Response validation:** the API can return errors as HTTP 200 with body
  `[{"message": [...]}]`. Treat any body that is not `[metadata, data]` as an error.
  A body of `[metadata, null]` with `total = 0` is a valid empty result.
- **Retries:** on network errors, HTTP 429 and 5xx: exponential backoff with jitter,
  bounded attempts (configurable). 4xx other than 429: fail fast.
- **Atomicity:** a run either inserts all of its new pages or none (single DuckDB
  transaction per run).
- **Unknown codes:** a configured country or indicator the API does not return fails the
  run with a clear message.

## 10. Extensibility

Adding a country, indicator or year range is a config change in
`config/pipeline.yml`. dbt reads the scope through a seed/var generated from the same
config, so the spine, dimensions and expected cell count follow automatically. No
pipeline code changes.

## 11. Assumptions

- Income group is the **current** World Bank classification. Historical
  classifications are not available from this endpoint, so a country's group is applied
  to all years. Documented limitation.
- Values are used as published (current US dollars, not inflation-adjusted).
- The World Bank API is the only production source; no manual corrections.
- Time zone for audit timestamps is UTC.

## 12. Out of scope

- Historical (SCD2) tracking of revised values. The raw layer keeps every distinct
  payload, so history is reconstructable; a snapshot model is listed as a next step.
- Dashboards. Optional per the brief.
