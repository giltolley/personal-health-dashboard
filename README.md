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
