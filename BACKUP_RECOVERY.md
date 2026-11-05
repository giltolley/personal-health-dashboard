# Access and application-data recovery

## 1.0 operational status

The owner confirmed invitation-only Streamlit viewing. The first live backup
completed successfully, including isolated restore validation, encryption,
artifact upload, download and checksum verification. The daily schedule is
configured. Monitor scheduled runs and keep the private decryption key protected.
The full PostgreSQL restore drill remains deferred by the owner.

The setup instructions below also apply to a new deployment; do not regenerate
keys for an existing installation unless deliberately rotating them. Keep older
private keys for any retained artifacts encrypted with their public keys.

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

`backup_data.py` exports all 16 application tables, including laboratory collections, panels and results, saved goals, source
markers and ingestion logs, to a checksummed gzip JSON archive. It contains
private health data. It is compressed, **not encrypted**: use protected storage
and never attach it to a public GitHub issue, release or workflow artifact.

The restore command creates a new SQLite file, reconstructs the application's
schema, checks row counts and checksums, runs SQLite integrity_check, and checks
Hevy workout/exercise/set links and laboratory collection/panel/result links.
Version 2 includes laboratory history; older version 1 archives remain readable. It refuses to overwrite existing files. It never
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
all 16 tables. The backup does not include its connection string.

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

## Daily encrypted GitHub artifacts

The workflow `.github/workflows/backup-artifact.yml` runs daily at 05:47
America/New_York and supports manual runs. Scheduled runs may be delayed.
It remains disabled until the BACKUP_PUBLIC_KEY repository variable is present.

Each run exports a consistent snapshot, verifies an isolated SQLite restore,
encrypts the archive using libsodium sealed boxes, uploads only ciphertext as a
GitHub Actions artifact with 30-day retention, downloads it again and verifies
its exact SHA-256. Plaintext stays in a temporary directory. Public-repository
artifacts are accessible to signed-in readers, so only encrypted files may be
uploaded. The private decryption key never belongs on GitHub. Losing that key
makes these archives unrecoverable; keep two protected copies.

### One-time activation

1. Obtain a key pair privately. If generating your own, install
   `requirements-backup.txt` and run `python backup_crypto.py --generate-keys backups/keys`.
   This creates a new directory and refuses to overwrite an existing one.
2. Save Health_Dashboard_Backup_Private_Key.txt in your password manager and keep
   a second protected copy. Never upload it to GitHub.
3. Merge the backup PR. In repository Settings → Secrets and variables → Actions
   → Variables, create **BACKUP_PUBLIC_KEY** using the public-key file's contents.
   This is a nonsecret repository variable. The existing DATABASE_URL Actions
   secret is reused; no Google authorization or new credential is needed.
4. Under Actions, manually run **Daily encrypted database backup**. Confirm the
   entire run passes and contains an encrypted-health-backup artifact. This is
   required to verify actual database access and artifact storage. Adding the
   variable also enables the daily schedule; code alone does not activate it.
5. Enable Actions failure notifications in your GitHub notification settings.
   Public-repository schedules can be disabled after 60 days without repository
   activity. Check the run history periodically. Artifacts expire after 30 days;
   download a protected copy if a longer recovery window is needed.

To pause future backups, delete BACKUP_PUBLIC_KEY. Existing artifacts retain their
expiry. Review workflow changes before merging: the scheduled job reads live data.
CI exercises upload/download using synthetic encrypted data without production
credentials. A full PostgreSQL restore drill remains deferred by the owner.

### Recover an encrypted artifact

Open a successful backup run in Actions and download its encrypted-health-backup
artifact. Extract the ZIP to obtain dashboard.health-backup.enc, then run locally:

```powershell
py -3.12 -m pip install -r requirements-backup.txt
py -3.12 backup_crypto.py --input dashboard.health-backup.enc --private-key C:\private\Health_Dashboard_Backup_Private_Key.txt --output backups/recovered.health-backup.json.gz
py -3.12 backup_data.py restore-sqlite --backup backups/recovered.health-backup.json.gz --destination backups/recovery-check.sqlite
```

Commands refuse to overwrite existing files. Use the replacement-database
migration steps above after successful local verification. The owner handles the
Streamlit access review, which is complete for 1.0. New deployments must repeat
the access review, activation and first live backup verification.

References:
- https://docs.github.com/en/actions/using-workflows/storing-workflow-data-as-artifacts
- https://docs.github.com/en/actions/managing-workflow-runs/disabling-and-enabling-a-workflow
- https://pynacl.readthedocs.io/en/latest/public/
