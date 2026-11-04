# Access and application-data recovery

## Access boundaries

Repository visibility and Streamlit app visibility are separate. A public code
repository must contain no data exports, credentials or private backups. Verify
Streamlit's viewer settings and open the deployed URL in a signed-out/private
browser. Goal-editor password protection only gates edits; it does not protect
viewing the dashboard.

The dashboard connects server-side through DATABASE_URL. Browser-facing Supabase
API roles must not have access to the private tables. Use RLS and revoke table
privileges from PUBLIC, anon and authenticated. No API policies are needed for a
server-only application using an appropriately configured database role. A
separate least-privilege UI credential has not yet been verified. The app still
performs schema initialization at startup; switching it to a read-only database
role requires separating that initialization first.

## What this backup covers

`backup_data.py` exports all 13 application tables, including saved goals, source
markers and ingestion logs, to a checksummed gzip JSON archive. It contains
private health data. It is compressed, **not encrypted**: use protected storage
and never attach it to a public GitHub issue, release or workflow artifact.

The restore command creates a new SQLite file, reconstructs the application's
schema, checks row counts and checksums, runs SQLite integrity_check, and checks
Hevy workout/exercise/set links. It refuses to overwrite existing files. It never
writes to the production database.

This is application-data recovery, not a full PostgreSQL dump. PostgreSQL roles,
RLS configuration, database-level settings, Supabase-managed schemas, provider
configuration and external API credentials are not backed up. A full PostgreSQL
restore to an isolated PostgreSQL server remains a separate operational test.

## Export and verify

Set DATABASE_URL privately in your shell. Do not put it on the command line or
commit it. Select a private destination on your computer or protected storage:

```powershell
py -3.12 backup_data.py export --output backups/current.health-backup.json.gz
py -3.12 backup_data.py restore-sqlite --backup backups/current.health-backup.json.gz --destination backups/restore-check.sqlite
```

To export an existing local SQLite database instead, use `--sqlite PATH`; that
explicit choice overrides DATABASE_URL. Exports use a read-only repeatable-read
transaction on PostgreSQL. The application connection needs permission to read
all 13 tables. The backup does not include its connection string.

For local review, point NUTRITION_DB at the restored SQLite file **and unset
DATABASE_URL**, otherwise the app will still connect to the hosted database.

## Recover to a replacement hosted database

Keep the original backup unchanged. First run the isolated SQLite verification.
Provision a separate destination database and privately set DATABASE_URL to it.
Review the source counts before importing:

```powershell
py -3.12 migrate_sqlite_to_postgres.py --sqlite backups/restore-check.sqlite --dry-run
py -3.12 migrate_sqlite_to_postgres.py --sqlite backups/restore-check.sqlite
```

Migration includes goal history, resets the ingestion-log identity sequence, and
enables RLS/revokes public API access for application tables. Use a dedicated new
destination: upserts into an existing database do not remove unrelated rows and
are not an exact rollback. Compare counts and dated goals afterward; test the
app against the replacement before changing production connection settings.

## Remaining operational requirements

- Verify deployed Streamlit visibility and the viewer list while signed in.
- Test signed-out access to the exact deployed URL.
- Choose protected off-site storage and retention before scheduling backups.
- Configure recurring exports and monitor failures; no recurring backup is
  enabled by adding this utility.
- Run a full PostgreSQL recovery drill when direct database credentials and an
  isolated PostgreSQL target are available.

Supabase free projects should maintain their own off-site logical exports:
https://supabase.com/docs/guides/platform/backups

Streamlit access settings:
https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/app-settings
