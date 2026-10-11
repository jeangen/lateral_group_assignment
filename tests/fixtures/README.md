# Test fixtures

Tests never call the live API. They read files from this directory.

## `recorded/`

Real World Bank API responses, captured verbatim by `make record-fixtures`
(`scripts/record_fixtures.py`). `manifest.json` lists the URL, page, fetch time and
sha256 of every file. Used for end-to-end tests of ingestion and the data model.

## `synthetic/`

Hand-written payloads in the exact shape of the API, covering edge cases that live data
may not exhibit on demand. **Values are illustrative, not real World Bank data.**

| File                              | Case                                                      |
|-----------------------------------|-----------------------------------------------------------|
| `country_two.json`                | Country metadata incl. trailing space in region name      |
| `indicator_multipage_p1.json`     | Page 1 of 2 (`per_page` = 2, `total` = 3)                 |
| `indicator_multipage_p2.json`     | Page 2 of 2                                               |
| `indicator_with_nulls.json`       | Observations with `value: null`                           |
| `indicator_total_mismatch.json`   | Metadata `total` disagrees with rows returned             |
| `empty_result.json`               | Valid empty result: `[metadata, null]` with `total` = 0   |
| `error_in_200.json`               | API error delivered with HTTP 200                         |
