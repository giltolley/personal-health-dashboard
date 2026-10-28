# Personal Health Dashboard v0.4 — Portable cloud preparation

This release is a portability upgrade, **not yet a confirmed live cloud deployment**.
Current UI is the same v0.3.2 dashboard; the Hevy full-reconciliation fallback is included.

## Architecture and service responsibilities

- **Streamlit Community Cloud:** browser UI only, **private app** from a **private GitHub repository**. Give it only the database connection secret.
- **Supabase Free PostgreSQL:** persistent analytical measurements. No raw Health Connect ZIP files or auth tokens are stored in the database. The free tier includes 500 MB but may pause for inactivity and has no automatic backups.
- **GitHub Actions:** Garmin job every six hours, Hevy job once a day. Both jobs write to the same database. They run without Streamlit or your PC.
- **Your computer/Android:** Health Connect export stays local for now. Use the existing local dashboard import, then migrate its selected records. Automated daily HC retrieval is a *future* integration and is not configured in this release.

## First, test locally without a cloud account

1. Back up your existing dashboard folder, especially `nutrition_analytics.sqlite`.
2. Stop Streamlit; replace your **code files** with this release, but **do not overwrite your existing SQLite database**.
3. Install requirements: `py -3.12 -m pip install -r requirements.txt`.
4. Start locally: `py -3.12 -m streamlit run app.py`.
5. Confirm Nutrition, Garmin/recovery, Renpho and Training views still work.
6. Audit your own SQLite file: `py -3.12 size_audit.py --sqlite nutrition_analytics.sqlite`.

`DATABASE_URL` is optional. When unset, the app uses the same local SQLite file and local key files as before.

## Set up the free cloud deployment (when ready)

### A. Create PostgreSQL database

1. Create a Supabase Free project.
2. In **Connect**, copy the **Session pooler** PostgreSQL connection URL (usually port 5432); use the actual supplied host and username, not a guessed one. The direct endpoint may be IPv6-only.
3. Use a strong database password. URL-percent-encode special password characters.
4. Prefer verified TLS (`sslmode=verify-full` plus Supabase's root certificate) where possible; at minimum set `sslmode=require`. This encrypts the connection but does not fully verify server identity.
5. In a local PowerShell session, set `$env:DATABASE_URL` to the connection string. **Do not paste it into code or your Git repository.**

### B. Migrate your existing data

Run from the dashboard folder:

```powershell
py -3.12 migrate_sqlite_to_postgres.py --sqlite nutrition_analytics.sqlite --dry-run
py -3.12 migrate_sqlite_to_postgres.py --sqlite nutrition_analytics.sqlite
```

The source SQLite file is opened read-only; the destination tables are created in PostgreSQL and records are upserted by primary key. A repeated migration should not duplicate rows. If migration fails, keep the SQLite backup and review the error before retrying.

**No live Supabase instance was available during development, so this is a staging implementation. Validate the PostgreSQL connection and migrated counts before enabling scheduled jobs.**

### C. Create a private GitHub repository

1. Create a **private** repository for the dashboard and push the code only.
2. Verify the `.gitignore` excluded any `.sqlite`, `.db`, ZIP, JSON, `.env`, tokens and `secrets.toml`. Check your staged file list **before** the first push.
3. In **Settings → Secrets and variables → Actions**, create exactly these repository secrets:
   - `DATABASE_URL`: Supabase PostgreSQL session-pooler connection URL
   - `GARMIN_PERSONAL_API_KEY`: Garmin personal key
   - `HEVY_API_KEY`: Hevy Pro key
4. Under **Actions**, test each workflow using **Run workflow** before relying on the schedules. Workflows only retrieve measurements and store them; they do not modify Garmin or Hevy.
5. Automatic schedules may be delayed, especially on busy GitHub infrastructure. Monitor runs and data freshness.

### D. Deploy private Streamlit dashboard

1. Visit Streamlit Community Cloud, link your **private GitHub repo**, and select `app.py`.
2. Choose **private app**, not public. Community Cloud permits one private app at a time on its free offering.
3. In the deployment's **Advanced settings → Secrets**, enter the root-level TOML setting:

```toml
DATABASE_URL = "postgresql://REPLACE_WITH_YOUR_CONNECTION_URL"
```

4. Do **not** put your Garmin or Hevy keys in Streamlit. The dashboard reads PostgreSQL; Actions performs API syncing separately.
5. Check that the imported history appears and the app is private. Do not share its URL or grant viewers unless intended.

## Why the architecture is portable

Nothing imports Supabase SDKs, GitHub APIs, or Streamlit-specific services into the ingestion modules.
`DATABASE_URL` accepts any standard PostgreSQL DSN, including Render or Railway. The separate cron entrypoint `sync_all.py` can run on any scheduler, and `app.py` can run on any Streamlit-compatible Python server. SQLite remains the local fallback.

## Backups and privacy

- **Free Supabase does not provide automatic database backups.** Configure an independent encrypted backup before relying on the cloud as your sole copy.
- Keep the existing `nutrition_analytics.sqlite` and Health Connect exports securely on your computer during migration.
- The private Streamlit service and GitHub Actions will both reach the same PostgreSQL database. Use distinct read-only and write database credentials in a future security-hardening release if possible.
- API keys expire/revoke independently; track future expiry in your own password manager.
- Do not commit plaintext health exports, workout JSON, database credentials or bearer-token cache files.
- The free cloud deployment is suitable for personal experimentation, **not a high-availability or regulatory-grade medical system**.

## Scope still outstanding

- Automated Health Connect export retrieval from your chosen cloud destination
- Nutrition CSV backfill converter and October 2026 gap repair
- End-to-end Supabase/PostgreSQL integration testing
- Automated encrypted off-site database backup
- More granular database roles and long-term data-quality alerting
