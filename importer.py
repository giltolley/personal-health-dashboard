import io
import sqlite3
import tempfile
import zipfile
from pathlib import Path
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

def initialize(path):
    db = connect(path)
    db.executescript(SCHEMA)
    db.commit()
    return db

def import_health_zip(db, file):
    # Health Connect's SQLite export is a backup format, not a guaranteed stable API.
    zf = zipfile.ZipFile(file)
    matches = [n for n in zf.namelist() if n.endswith('.db')]
    if len(matches) != 1:
        raise ValueError('Expected exactly one SQLite database in the export')
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / 'export.db'
        with zf.open(matches[0]) as src, target.open('wb') as dst:
            import shutil
            shutil.copyfileobj(src, dst)
        srcdb = sqlite3.connect(str(target))
        srcdb.row_factory = sqlite3.Row
        apps = {r['row_id']: r['package_name'] for r in srcdb.execute('SELECT row_id, package_name FROM application_info_table')}
        n = w = 0
        for r in srcdb.execute('SELECT uuid,local_date,app_info_id,meal_type,energy,protein,total_carbohydrate,total_fat,dietary_fiber,sodium,potassium FROM nutrition_record_table'):
            app = apps.get(r['app_info_id'], '')
            if app != 'com.myfitnesspal.android':
                continue
            db.execute('''INSERT INTO nutrition VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(record_id) DO UPDATE SET
                local_date=excluded.local_date,app=excluded.app,meal_type=excluded.meal_type,
                calories=excluded.calories,protein_g=excluded.protein_g,carbs_g=excluded.carbs_g,
                fat_g=excluded.fat_g,fiber_g=excluded.fiber_g,sodium_mg=excluded.sodium_mg,
                potassium_mg=excluded.potassium_mg''',
                (bytes(r['uuid']).hex(), str(pd.Timestamp('1970-01-01') + pd.Timedelta(days=r['local_date']))[:10], app,
                 r['meal_type'], float(r['energy'] or 0)/1000, r['protein'], r['total_carbohydrate'],r['total_fat'],
                 r['dietary_fiber'], None if r['sodium'] is None else r['sodium']*1000,
                 None if r['potassium'] is None else r['potassium']*1000))
            n += 1
        for r in srcdb.execute('SELECT uuid,local_date,app_info_id,weight FROM weight_record_table'):
            app = apps.get(r['app_info_id'], '')
            if app != 'com.renpho.health':
                continue
            db.execute('''INSERT INTO weights VALUES (?,?,?,?) ON CONFLICT(record_id) DO UPDATE SET
                local_date=excluded.local_date,app=excluded.app,weight_lb=excluded.weight_lb''',
                (bytes(r['uuid']).hex(),str(pd.Timestamp('1970-01-01') + pd.Timedelta(days=r['local_date']))[:10], app, r['weight']/453.59237))
            w += 1
        srcdb.close()
        db.commit()
        return n,w

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
