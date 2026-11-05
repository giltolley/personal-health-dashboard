# Personal Health Dashboard · 1.1.0

A personal health dashboard with a decision-focused Overview, nutrition and energy analysis, training and recovery views, laboratory history and comparisons, saved goal history, and a 5/3/1 next-cycle planner. Supports local SQLite and hosted PostgreSQL through `DATABASE_URL`. Ingestion runs separately from the Streamlit UI.

**Start here:** [DEPLOYMENT.md](DEPLOYMENT.md) for the current architecture and configuration, [CHANGELOG.md](CHANGELOG.md) for release notes, and [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md) for recovery.

For the 1.0 deployment, invitation-only Streamlit access has been confirmed and the first live encrypted backup passed verification. Daily backups are configured with 30-day retention. Keep monitoring scheduled runs; a full PostgreSQL restore drill is deferred.

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

With `DATABASE_URL` set, scheduled jobs write to PostgreSQL. The hosted Streamlit UI intentionally hides raw Health Connect imports and live API sync buttons: Health Connect exports are retrieved from Drive by a scheduled job, and integration credentials belong in the scheduled-job environment.

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
calorie adjustments. Waist tracking is optional. Laboratory collections are available in the Labs tab.

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
markers, not a live GitHub API feed. Plaintext measurements and credentials are not committed to the repository. Scheduled runners process private data, and the backup workflow uploads only encrypted payloads as artifacts.


See [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md) for private application-data export, isolated restore verification, access checks and ongoing operational requirements.


Daily encrypted GitHub artifact backups are implemented in `.github/workflows/backup-artifact.yml`.
Add the nonsecret BACKUP_PUBLIC_KEY repository variable to enable the schedule;
keep its matching private key outside GitHub. See BACKUP_RECOVERY.md for activation,
30-day retention, verification and recovery instructions.

## Development checks

Use Python 3.12, install `requirements-backup.txt`, then run `python -m unittest discover -v`.
Tests use synthetic fixtures; keep production credentials out of the test environment.
The app displays the release version from `version.py`; historical module/test
filenames are retained for compatibility.

## Laboratory history (added in 1.1.0)

The Labs tab groups results by collection and panel, independently of the daily
start/end date filters. It preserves text, intervals, inequalities, units and
lab-specific normal ranges. Range status is calculated from those supplied
ranges; missing ranges and unassessed text are never labeled normal. An optional
filter shows results definitively outside the lab range. Source transcriptions,
blank fields and administrative notes remain available for review.

Provision hosted lab tables with `lab_schema.sql` before deploying this version.
It enables RLS and revokes access from browser API roles, matching the existing
server-only access model. Local SQLite tables initialize automatically. Personal
results belong only in the private database, never in this public repository.
There is no automatic email parser or clinical diagnosis feature.

With two or more collections, Labs opens a side-by-side comparison. Choose a
baseline and comparison collection; changes are comparison minus baseline.
Tests match by explicit panel family and test key, so urine and blood tests
with the same name remain separate. Both sides retain their own ranges and
units. Missing tests remain visible. Different units, text, intervals and
inequalities do not receive a numeric change; matching units do not guarantee
identical laboratory methods. Duplicate test identities are not paired automatically.

Result and status cells are green within the supplied lab range, red above or
below it, amber for an uncertain boundary, and gray when unassessed or missing.
Text labels remain visible in both comparison and collection detail views.
Changes themselves are not colored as improvements or deterioration.


Backups include collections, panels and results in format version 2; version 1
backups remain readable. Backup format version 2 is independent of product
version 1.1.0; older backups cannot contain laboratory records added later.

Run synthetic Labs and recovery checks with:

```powershell
python -m unittest -v test_labs test_backup_data test_backup_artifact test_streamlit_v07_smoke
```
