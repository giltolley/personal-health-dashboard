# Personal Health Dashboard · pre-1.0

Supports **local SQLite** (compatible with your existing v0.3.2 database) and **standard PostgreSQL** by setting `DATABASE_URL`. Keeps Garmin and Hevy sync clients separate from the Streamlit UI. Includes optional GitHub Actions schedules for free cloud deployment.

**Start here:** [DEPLOYMENT.md](DEPLOYMENT.md). First test locally and back up your SQLite file. No cloud credentials or database are included in this archive.

Local quick start (Python 3.12+):

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 -m streamlit run app.py
```

Audit your actual local database size:

```powershell
py -3.12 size_audit.py --sqlite nutrition_analytics.sqlite
```

CLI sync (works with SQLite or PostgreSQL):

```powershell
py -3.12 sync_all.py --garmin --days 14
py -3.12 sync_all.py --hevy
```

With `DATABASE_URL` set, scheduled jobs write to PostgreSQL. The hosted Streamlit UI intentionally hides raw Health Connect imports and live API sync buttons: exports are processed locally and keys belong in the scheduled-job environment, not the frontend.

Security: this repository contains code only and may be public. Deployed app visibility is a separate setting that must be verified in Streamlit. Keep credentials and health exports out of Git. A local data-recovery test is documented in BACKUP_RECOVERY.md; it is not a full PostgreSQL disaster-recovery certification.


## Actionable Overview

The Overview answers five questions: blood pressure, cardiovascular activity,
sleep, dietary gaps, and intake versus strength progress. It uses completed days
through the selected end date and displays source coverage. Six hours is the
personal sleep alert floor; seven hours remains the general adult reference.
Garmin intensity minutes already weight vigorous activity twice. Hevy training
days are separate and are not added to aerobic minutes.

Nutrition summaries preserve unknown daily totals if any meal has a NULL value
for that nutrient. The 3+ meal-record completeness proxy cannot verify food-entry
accuracy or distinguish an omitted nutrient stored as numeric zero. Training
suggestions compare two 28-day windows and are coaching heuristics, not automatic
calorie adjustments. Waist tracking is optional; lab imports are deferred.

Run `python -m unittest -v test_overview test_streamlit_v07_smoke` to check
thresholds, sparse records, nutrition aggregation, and all five rendered sections.


The Overview includes BP trends, activity progress, daily nutrient bars and
separate weight/lift charts. Missing values remain gaps.

## Saved goals and phase history

Goal snapshots are stored in `goal_history`, not in the repository or browser
session. Effective dates drive historical calorie/fiber/protein references;
corrections for an existing date append a revision. A known prior goal with an
unknown start is displayed as context and is not extrapolated onto older dates.
The analysis warns when a 28-day window spans target changes and withholds
muscle-gain suggestions for other phases. Protein references are unknown until
explicitly recorded; an old day's missing reference is not scored as failure.

SQLite creates the goals table locally. Hosted PostgreSQL requires the protected
schema in `goal_history_schema.sql` to be provisioned before deploying this code.
Hosted editing is read-only by default: configure a private `GOAL_EDIT_TOKEN`
Streamlit secret and enter it in the sidebar to save future changes. Never commit
this password or personal goal entries. Local editing requires no password.
Rerun or reboot the hosted app after merging to refresh imported modules.

Run `python -m unittest -v test_goals test_overview test_overview_charts test_streamlit_v07_smoke`.


## Live source health

Overview shows current source freshness separately from historical analysis dates.
Data & Sync shares the same source-specific checks. Garmin requests are checked
per dataset (18-hour grace); Health Connect and Hevy allow 36 hours. Measurement
dates are checked separately: two calendar days for daily sources, three for
weight. Coverage counts seven completed local days, excluding today. Hevy workout,
BP and body-fat dates are event-driven and do not trigger stale-sync warnings.

Health Connect now records an unchanged-export check without reimporting the ZIP.
Older entries record completed imports only. Hevy records last successful sync;
failed attempts must still be inspected in GitHub Actions. The UI reads database
markers, not a live GitHub API feed. No measurement or credential is sent to GitHub.


See [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md) for private application-data export, isolated restore verification, access checks and remaining operational requirements.


Daily encrypted GitHub artifact backups are prepared in `.github/workflows/backup-artifact.yml`.
Add the nonsecret BACKUP_PUBLIC_KEY repository variable to enable the schedule;
keep its matching private key outside GitHub. See BACKUP_RECOVERY.md for activation,
30-day retention, verification and recovery instructions.
