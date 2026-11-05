# Personal Health Dashboard deployment

## Current architecture (1.1.0)

| Component | Responsibility |
|---|---|
| Streamlit Community Cloud | Invitation-only dashboard and protected goal editor |
| PostgreSQL | Persistent measurements, laboratory history, goals and sync markers |
| GitHub repository | Public source code; no plaintext health exports or credentials |
| GitHub Actions | Source ingestion and encrypted application-data backups |
| Google Drive | Health Connect ZIP source, read through a folder-scoped service account |
| Local SQLite | Local operation, imports and isolated recovery verification |

Repository visibility is independent of Streamlit viewer access. The owner
confirmed invitation-only Streamlit access for the 1.0 release. Recheck viewer
settings after deployment or sharing changes. Goal-editor protection only gates
edits; it does not control dashboard viewing.

## Local start

Use Python 3.12 and install `requirements.txt`:

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 -m streamlit run app.py
```

Without DATABASE_URL, the app uses SQLite; NUTRITION_DB selects its path.
With DATABASE_URL configured, the app uses PostgreSQL. Unset DATABASE_URL when
reviewing a restored SQLite file so you do not connect to the hosted database.

## Hosted configuration

Keep the PostgreSQL connection URL private. Use the actual provider-supplied
connection host, username and port; URL-encode password characters. Configure
TLS for the connection, with certificate verification where available.

In Streamlit secrets, configure root-level DATABASE_URL. Optionally configure
GOAL_EDIT_TOKEN to enable protected hosted goal editing; without it, the editor
is read-only. Do not supply Garmin or Hevy API keys to Streamlit.

The app initializes application schemas at startup. Provision the protected
`goal_history_schema.sql` before deploying saved-goal functionality. Browser API
roles must not have access to application tables. See [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md)
for access boundaries and replacement-database migration instructions.

Version 1.1.0 adds private laboratory tables. Provision `lab_schema.sql` before
deploying Labs to a new hosted database; it enables RLS and revokes browser API
access. SQLite initializes these tables automatically. Existing installations
with lab tables do not need a new migration for the 1.1.0 version update.
After adding labs, verify a backup run includes the new schema; the original
1.0 live-run check predates lab support.

### GitHub Actions configuration

| Setting | Type | Used by |
|---|---|---|
| DATABASE_URL | Secret | Sync jobs and backups |
| GARMIN_PERSONAL_API_KEY | Secret | Garmin sync |
| HEVY_API_KEY | Secret | Hevy sync |
| GCP_WORKLOAD_IDENTITY_PROVIDER | Variable | Health Connect Google authentication |
| GCP_SERVICE_ACCOUNT_EMAIL | Variable | Health Connect folder reader |
| GOOGLE_DRIVE_FOLDER_ID | Variable | Health Connect source folder |
| BACKUP_PUBLIC_KEY | Variable | Enables and encrypts recurring backups |

Health Connect uses Google Workload Identity Federation through the workflow's
OIDC identity. Grant the service account read access to the intended source
folder and restrict the identity trust to the intended repository/workflow.
It does not need ownership of a backup folder. Backup encryption is independent
of Google authorization: keep the matching private key outside GitHub.

### Schedules

| Workflow | Configured schedule |
|---|---|
| Garmin | 02:17, 08:17, 14:17 and 20:17 UTC |
| Hevy | 10:31 and 22:31 UTC |
| Health Connect | 03:43 America/New_York |
| Encrypted backup | 05:47 America/New_York |

Workflows also support manual dispatch. Health Connect manual dispatch defaults
to preview; select normal to import changes or force to reprocess an export.
Schedules may be delayed. Inspect Actions failures and the dashboard's source
freshness indicators; those indicators read database markers, not GitHub status.

## Release and operations

The first live encrypted backup passed export, isolated restore, encryption,
upload, download and ciphertext verification for 1.0. Each backup is retained
for 30 days. See [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md) for decryption, retention
limits and recovery. The first scheduled execution still needs routine monitoring.

After merging UI/module updates, rerun or reboot Streamlit if the app continues
to show the previous code. Review source freshness and dated goal settings after
a deployment. Enable GitHub Actions failure notifications and check run history
periodically, including after extended repository inactivity.

Remaining work is documented in [CHANGELOG.md](CHANGELOG.md). A separate
least-privilege UI database role and a full PostgreSQL restore drill are deferred;
the accepted 1.0 recovery check is isolated application-data restoration.
