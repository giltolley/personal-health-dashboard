# Personal Health Dashboard v0.4 (cloud-portable)

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

Security: private repository, private app, environment secrets, regular backup, and no health exports in Git. The PostgreSQL path still requires an end-to-end test with a real database before considered production-ready.


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


The Overview includes BP trends with separate systolic/diastolic references,
weekly aerobic/strength progress, daily nutrient bars with reference lines, and
separate weight and lift-change charts. Unknown nutrient values and insufficient
lift comparisons remain gaps rather than zero. The current calorie widget starts
at the agreed 2,800 kcal target and can be adjusted in the sidebar. The legacy
`CALORIE_GOAL` environment setting no longer overrides this widget; prior widget
state is reset once by its new key. Changes apply across dietary references and
energy charts for that browser session and are not saved as historical goals.
