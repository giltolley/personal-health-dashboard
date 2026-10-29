"""Health Connect nutrition and weight importer with source-snapshot reconciliation.

For dates present in the newest MFP nutrition export, the export's record UUIDs
are treated as authoritative. Obsolete UUIDs from older exports are deleted,
so MyFitnessPal record recreation cannot double-count calories.

Dates without nutrition entries in the current export are preserved.
"""
import io
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from collections import Counter
from datetime import date, timedelta
from datastore import connect, read_frame
import pandas as pd

SCHEMA = '''
CREATE TABLE IF NOT EXISTS nutrition (
  record_id TEXT PRIMARY KEY, local_date TEXT NOT NULL, app TEXT NOT NULL,
  meal_type INTEGER, calories REAL, protein_g REAL, carbs_g REAL, fat_g REAL,
  fiber_g REAL, sodium_mg REAL, potassium_mg REAL
);
CREATE TABLE IF NOT EXISTS weights (
  record_id TEXT PRIMARY KEY, local_date TEXT NOT NULL, app TEXT NOT NULL, weight_lb REAL
);
CREATE TABLE IF NOT EXISTS backfill (
  local_date TEXT PRIMARY KEY, calories REAL, protein_g REAL, carbs_g REAL,
  fat_g REAL, fiber_g REAL, sodium_mg REAL, potassium_mg REAL
);
'''

MFP_APP = 'com.myfitnesspal.android'
RENPHO_APP = 'com.renpho.health'
EPOCH = date(1970, 1, 1)


def initialize(path):
    db = connect(path)
    db.executescript(SCHEMA)
    db.commit()
    return db


def _extract_records(file):
    """Read the SQLite backup and return exact exported UUIDs and values."""
    if hasattr(file, 'seek'):
        file.seek(0)
    with zipfile.ZipFile(file) as zf:
        matches = [n for n in zf.namelist() if n.endswith('.db')]
        if len(matches) != 1:
            raise ValueError('Expected exactly one SQLite database in the export')
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'export.db'
            with zf.open(matches[0]) as source, target.open('wb') as output:
                import shutil
                shutil.copyfileobj(source, output)
            sc = sqlite3.connect(f'file:{target}?mode=ro', uri=True)
            sc.row_factory = sqlite3.Row
            try:
                apps = {r['row_id']: r['package_name'] for r in
                        sc.execute('SELECT row_id, package_name FROM application_info_table')}
                meals = []
                for r in sc.execute("""SELECT uuid,local_date,app_info_id,meal_type,energy,protein,
                     total_carbohydrate,total_fat,dietary_fiber,sodium,potassium
                     FROM nutrition_record_table"""):
                    if apps.get(r['app_info_id'], '') != MFP_APP:
                        continue
                    meals.append((
                        bytes(r['uuid']).hex(), str(EPOCH + timedelta(days=r['local_date'])), MFP_APP,
                        r['meal_type'], float(r['energy'] or 0) / 1000,
                        r['protein'], r['total_carbohydrate'], r['total_fat'],
                        r['dietary_fiber'],
                        None if r['sodium'] is None else r['sodium'] * 1000,
                        None if r['potassium'] is None else r['potassium'] * 1000,
                    ))
                weights = []
                for r in sc.execute('SELECT uuid,local_date,app_info_id,weight FROM weight_record_table'):
                    if apps.get(r['app_info_id'], '') != RENPHO_APP:
                        continue
                    weights.append((
                        bytes(r['uuid']).hex(), str(EPOCH + timedelta(days=r['local_date'])),
                        RENPHO_APP, r['weight'] / 453.59237,
                    ))
                return meals, weights
            finally:
                sc.close()


def _reconciliation_plan(db, meals):
    """Inspect potential removals. All operations here are read-only."""
    if not meals:
        raise ValueError('No MyFitnessPal nutrition records in export; refusing to reconcile')

    source_ids = {row[0] for row in meals}
    if len(source_ids) != len(meals):
        raise ValueError('Export contains duplicate nutrition UUIDs; refusing to reconcile')
    source_dates = {row[1] for row in meals}
    by_date_source = Counter(row[1] for row in meals)
    earliest, latest = min(source_dates), max(source_dates)

    # Load existing IDs only, scoped to MFP. Dates missing from the export
    # (for example during a Health Connect sync gap) must not be cleared.
    existing = db.execute(
        'SELECT record_id, local_date FROM nutrition WHERE app=? AND local_date>=? AND local_date<=?',
        (MFP_APP, earliest, latest),
    ).fetchall()
    by_date_existing = Counter(row[1] for row in existing if row[1] in source_dates)
    obsolete_ids = [row[0] for row in existing
                    if row[1] in source_dates and row[0] not in source_ids]

    # Never accept a large or suspiciously incomplete snapshot silently.
    max_allowed_removals = max(25, len(meals) // 4)
    if len(obsolete_ids) > max_allowed_removals:
        raise RuntimeError(
            f'Unsafe reconciliation: {len(obsolete_ids)} older UUIDs absent from export; '
            f'limit is {max_allowed_removals}. No records changed.'
        )
    for day, previous_count in by_date_existing.items():
        current_count = by_date_source[day]
        if previous_count >= 4 and current_count * 2 < previous_count:
            raise RuntimeError(
                f'Unsafe reconciliation on {day}: old rows={previous_count}, '
                f'exported rows={current_count}. No records changed.'
            )
    affected = len({row[1] for row in existing
                    if row[1] in source_dates and row[0] not in source_ids})
    return obsolete_ids, affected, len(source_dates)


def import_health_zip(db, file, *, preview_only=False):
    """Import current source snapshot, deleting superseded MFP UUIDs atomically.

    preview_only=True runs the entire reconciliation preflight but performs
    no INSERT, UPDATE, DELETE or success-marker write.

    Returns (nutrition_source_rows, renpho_weight_source_rows) for compatibility.
    """
    meals, weights = _extract_records(file)
    obsolete_ids, affected_days, exported_days = _reconciliation_plan(db, meals)
    print('Nutrition reconciliation:', {
        'exported_meals': len(meals),
        'exported_dates': exported_days,
        'obsolete_rows': len(obsolete_ids),
        'affected_dates': affected_days,
        'mode': 'PREVIEW, no changes' if preview_only else 'IMPORT',
    })
    if preview_only:
        return len(meals), len(weights)

    # Nutrition updates, weight updates and deletion of superseded MFP UUIDs
    # succeed together or roll back together on both PostgreSQL and SQLite.
    with db:
        for row in meals:
            db.execute("""INSERT INTO nutrition VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(record_id) DO UPDATE SET
                local_date=excluded.local_date,app=excluded.app,meal_type=excluded.meal_type,
                calories=excluded.calories,protein_g=excluded.protein_g,carbs_g=excluded.carbs_g,
                fat_g=excluded.fat_g,fiber_g=excluded.fiber_g,sodium_mg=excluded.sodium_mg,
                potassium_mg=excluded.potassium_mg""", row)
        for row in weights:
            db.execute("""INSERT INTO weights VALUES (?,?,?,?)
                ON CONFLICT(record_id) DO UPDATE SET
                local_date=excluded.local_date,app=excluded.app,weight_lb=excluded.weight_lb""", row)
        for record_id in obsolete_ids:
            db.execute('DELETE FROM nutrition WHERE record_id=? AND app=?', (record_id, MFP_APP))
    return len(meals), len(weights)


def import_backfill_csv(db, file):
    # Normalized daily CSV template (not an assertion about MFP's vendor export layout).
    frame = pd.read_csv(file)
    required = {'local_date','calories'}
    if not required.issubset(frame.columns):
        raise ValueError('CSV must contain local_date and calories columns')
    fields = ['calories','protein_g','carbs_g','fat_g','fiber_g','sodium_mg','potassium_mg']
    for _, row in frame.iterrows():
        date = pd.to_datetime(row['local_date']).date().isoformat()
        values = [None if f not in frame or pd.isna(row[f]) else float(row[f]) for f in fields]
        db.execute('''INSERT INTO backfill VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(local_date) DO UPDATE SET
        calories=excluded.calories,protein_g=excluded.protein_g,carbs_g=excluded.carbs_g,
        fat_g=excluded.fat_g,fiber_g=excluded.fiber_g,sodium_mg=excluded.sodium_mg,
        potassium_mg=excluded.potassium_mg''',(date,*values))
    db.commit()
    return len(frame)

def read_daily(db):
    raw = read_frame(db, '''SELECT local_date, SUM(calories) calories, SUM(protein_g) protein_g,
       SUM(carbs_g) carbs_g, SUM(fat_g) fat_g, SUM(fiber_g) fiber_g,
       SUM(sodium_mg) sodium_mg, SUM(potassium_mg) potassium_mg, COUNT(*) meals
       FROM nutrition GROUP BY local_date''')
    bf = read_frame(db, 'SELECT * FROM backfill')
    # Explicit precedence: existing Health Connect records win. Backfill only absent dates.
    if not bf.empty:
        bf['meals'] = None
        bf['source'] = 'CSV backfill'
    if not raw.empty:
        raw['source'] = 'Health Connect'
    daily = pd.concat([raw, bf[~bf.local_date.isin(raw.local_date)]], ignore_index=True) if not raw.empty else bf.copy()
    if daily.empty: return daily
    daily['local_date'] = pd.to_datetime(daily['local_date'])
    daily = daily.sort_values('local_date').set_index('local_date')
    return daily.asfreq('D')

def read_weight(db):
    df = read_frame(db, 'SELECT local_date,weight_lb FROM weights')
    if df.empty: return df
    df['local_date'] = pd.to_datetime(df.local_date)
    return df.groupby('local_date').weight_lb.median().sort_index()
