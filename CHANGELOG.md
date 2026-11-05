# Changelog

## 1.0.0 — 2026-11-04

First stable personal-use release of the hosted health dashboard.

### Included

- Five Overview sections: blood pressure, cardiovascular activity, sleep,
  dietary analysis, and intake versus training progress, with actionable charts
  and explicit source coverage.
- Energy and nutrition trends with selectable overlays, plus training and
  recovery detail views.
- A 5/3/1 next-cycle planner with editable Training Maxes and calculated sets.
- Effective-dated goals and revision history, including protected hosted editing.
- Scheduled Garmin, Hevy and Health Connect ingestion with source freshness checks.
- PostgreSQL hosting and local SQLite support.
- Encrypted recurring GitHub artifact backups with 30-day retention, isolated
  restore validation before upload, and download/checksum verification.

### Release verification

- Owner confirmed invitation-only Streamlit access.
- Live backup export, isolated restore check, encryption, upload and download
  verification passed; the recurring workflow is configured.
- Synthetic artifact upload/download and Overview checks passed in GitHub Actions.
- Existing application regression and recovery tests passed before release.

### Known limits and deferred work

- Laboratory-result imports and interpretation are deferred.
- Dietary completeness is a logging proxy; missing nutrient values and numeric
  zeros cannot always distinguish incomplete source data.
- Intake/training suggestions are coaching heuristics and do not change targets.
- Six hours is the personal sleep alert floor; the seven-hour adult reference
  remains visible.
- Backups cover application tables, not PostgreSQL roles, provider settings,
  external credentials or all Supabase-managed schemas. The full PostgreSQL
  restore drill is deferred.
- The hosted UI still initializes schemas; a separate least-privilege database
  role requires further work.
- Scheduled jobs require monitoring for failures, delays and inactivity-related
  disabling. Backup artifacts expire after 30 days.

Earlier iteration identifiers remain in module and test names to preserve imports
and workflow paths. Those filenames do not represent the current product version.
