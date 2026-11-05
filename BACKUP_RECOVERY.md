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

## Daily encrypted Google Drive backups

The prepared workflow `.github/workflows/backup-drive.yml` runs daily at 05:47
America/New_York and supports manual runs. It remains disabled until the setup
below is complete and ENABLE_DRIVE_BACKUPS is true. GitHub may delay scheduled
runs; the selected time is not an exact completion guarantee.

Each run exports a consistent snapshot, restores it in an isolated temporary
SQLite file, checks integrity/hashes/links, encrypts the archive using libsodium
sealed boxes, uploads only encrypted bytes to the private backup folder, and
downloads the uploaded file to verify its SHA-256. Only after successful
verification does it move this app's backups older than 30 days to Drive Trash.
It never permanently deletes files or touches unrelated Drive files. Plaintext
files are confined to the runner's temporary directory and cleaned on exit. No
backup payload is stored as a GitHub artifact, release, or repository file.

The private decryption key stays on your computer/in your password manager.
GitHub receives only the public encryption key. Losing the private key makes
the encrypted archives unrecoverable; keep a second protected copy. The workflow
also needs its existing DATABASE_URL secret and a Google offline authorization
secret. A scheduled runner necessarily has access to the live database, so review
changes to the workflow before merging them.

### One-time setup on your computer

1. In your existing Google Cloud project, ensure Drive API is enabled. Create an
   OAuth client with application type **Desktop app** and download its JSON to a
   private local directory. Use only the `drive.file` scope, which limits access
   to files created/opened through this app. Do not use a service account for a
   personal My Drive destination: service accounts cannot own new files there.
2. Configure the OAuth app for personal ongoing use. A project left in external
   **Testing** issues refresh tokens that expire after seven days for this scope.
   Use **In production** before authorizing for ongoing backups; then authorize
   only your own account. If you change publishing state later, authorize again.
3. From the checked-out repository, run:

```powershell
py -3.12 -m pip install -r requirements-backup.txt
py -3.12 setup_drive_backup.py --client C:\private\oauth-client.json
```

The helper opens Google's normal consent flow on your computer, creates a new
private **Personal Health Dashboard Backups** folder, and writes three files in
`backups/setup/`. It refuses to reuse an existing output directory or overwrite
keys. If setup is interrupted, use a new `--output-dir` for a subsequent attempt.
No credential values are printed.

4. Keep **backup-private.key** offline/in your password manager; never add it to
   GitHub, Actions secrets or the backup folder. Keep another safe copy.
5. In repository **Settings → Secrets and variables → Actions**, add:

| Setting | Type | Value |
|---|---|---|
| BACKUP_DRIVE_AUTH_JSON | Secret | Entire contents of drive-backup-auth.json |
| BACKUP_PUBLIC_KEY | Secret | Contents of backup-public.txt |
| ENABLE_DRIVE_BACKUPS | Variable | true |

DATABASE_URL is reused from the existing sync jobs. Do not paste any credentials
or keys into chat or source code. The folder ID is already inside the private
authorization JSON. No new sharing with the existing Health Connect service
account is needed, and its read-only access remains unchanged.

6. Merge the backup PR, manually run **Daily encrypted Drive backup**, and verify
   success plus a new `.health-backup.enc` file in the created Drive folder. Only
   this live run verifies your OAuth authorization and actual Drive destination.
   Enable GitHub Actions failure notifications for this repository in your own
   notification settings. A merged but disabled workflow is not an active backup.

### Recover an encrypted backup

Download a `.health-backup.enc` file privately from Drive, then run locally:

```powershell
py -3.12 backup_crypto.py --input downloaded.health-backup.enc --private-key backups/setup/backup-private.key --output backups/recovered.health-backup.json.gz
py -3.12 backup_data.py restore-sqlite --backup backups/recovered.health-backup.json.gz --destination backups/recovery-check.sqlite
```

Both commands refuse to overwrite an existing output. The existing hosted
migration instructions above apply after successful local verification.

## Accepted scope and remaining activation

The owner will review Streamlit viewer access. The owner has deferred the full
PostgreSQL disaster-recovery drill; the application-data restore test is the
accepted recovery check for this release. Recurring Drive backups are not active
until private OAuth setup, Actions settings and the first verified live run are
complete. No hosting permissions or recurring settings were changed by writing
this code.

References:
- https://supabase.com/docs/guides/platform/backups
- https://developers.google.com/workspace/drive/api/guides/folder
- https://developers.google.com/identity/protocols/oauth2/
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- https://pynacl.readthedocs.io/en/latest/public/
