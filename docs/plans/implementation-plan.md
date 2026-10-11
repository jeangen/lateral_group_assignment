# Implementation Plan

Implements `docs/specs/data-model-and-decisions.md`. Ordered by the priority in the
brief: ingestion and model first, then quality, then reporting, then documentation.
Each task is one commit. Time budget: ~5 hours total.

## Phase 0 — Foundations (done in setup commits)

- [x] Repo skeleton
- [x] Spec
- [x] This plan
- [x] Config file and project tooling
- [x] Fixture recording script and edge-case fixtures

## Phase 1 — Ingestion (≈75 min)

1. **Config loader** — `src/wb_pipeline/config.py`
   - Load and validate `pipeline.yml` (codes uppercase, year range valid, no duplicates).
   - Test: valid config loads; invalid configs raise clear errors.
2. **API client** — `src/wb_pipeline/client.py`
   - Paged GET returning raw pages; payload validation (error-in-200, empty result);
     retries with backoff on network/429/5xx; fail fast on other 4xx.
   - HTTP transport injectable so tests use fixtures.
   - Tests: single page, multi-page, error-in-200, empty result, retry then success,
     retries exhausted, row count ≠ `total`.
3. **Raw persistence** — `src/wb_pipeline/ingest.py`
   - Create `raw.api_response` and `raw.pipeline_run`; insert pages in one transaction;
     skip `(request_key, payload_sha256)` already present.
   - Test: second run with same fixtures inserts zero rows.
4. **CLI entrypoint** — `src/wb_pipeline/run.py` + `make run`
   - `ingest` → `dbt build` → `export` in sequence; non-zero exit on failure.

## Phase 2 — Data model (≈60 min)

5. **dbt project + scope seed** — generate scope from config; sources on raw tables.
6. **Staging models** — `stg_wb__countries`, `stg_wb__observations`
   (latest payload per `request_key`, flatten, type, trim).
7. **Dimensions** — `dim_country`, `dim_indicator`, `dim_year`.
8. **Fact** — `fct_indicator_value`: spine left join, `value_status`, `row_hash`,
   incremental merge on the natural key.

## Phase 3 — Data quality and tests (≈60 min)

9. **dbt schema tests** — uniqueness, not null, relationships, accepted values.
10. **Custom DQ tests** — expected cell count, null ⇔ status, value ranges,
    GDP per capita consistency (warn).
11. **End-to-end idempotency test** — full pipeline twice on fixtures; assert zero
    changed fact rows and zero new raw rows.
12. **Revision test** — modify one fixture value; assert exactly one fact row updates
    and a new raw row exists.

## Phase 4 — Reporting (≈45 min)

13. `rpt_missing_data` + `rpt_incomplete_series`
14. `rpt_yoy_change`
15. `rpt_latest_comparison` (per-country latest and common latest year)
16. `rpt_income_group_by_year`
17. **CSV export** to `output/` and commit sample outputs.

## Phase 5 — Documentation (≈30 min)

18. README: quick start, architecture, model, decisions, assumptions, trade-offs.
19. README: production design note (scheduling, late/corrected data, monitoring,
    backfills, Snowflake + Glue/EMR mapping, Azure mapping).
20. README: AI usage, time spent, unfinished work and next steps.

## Stretch (only if time remains)

- Snapshot model for value history (SCD2).
- Dockerfile as an alternative run path.
- A simple HTML or Power BI view over the report tables.
