"""Garmin Personal API responses -> local SQLite. Read-only; no credentials stored here."""
from __future__ import annotations
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DATASETS = ('daily_summaries','steps','hrv_summaries','sleep_summaries','body_battery','stress','activities')
METRICS = ('steps','distance_km','calories_burned','calories_resting','calories_active','resting_hr',
 'intensity_minutes','hrv_ms','hrv_weekly_ms','hrv_status','sleep_hours','deep_hours',
 'rem_hours','sleep_score','stress_score','body_battery_min','body_battery_max',
 'body_battery_charged','body_battery_drained')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS garmin_daily (local_date TEXT PRIMARY KEY,
 steps REAL, distance_km REAL, calories_burned REAL, calories_resting REAL,
 calories_active REAL, resting_hr REAL, intensity_minutes REAL, hrv_ms REAL,
 hrv_weekly_ms REAL, hrv_status TEXT, sleep_hours REAL, deep_hours REAL,
 rem_hours REAL, sleep_score REAL, stress_score REAL, body_battery_min REAL,
 body_battery_max REAL, body_battery_charged REAL, body_battery_drained REAL);
CREATE TABLE IF NOT EXISTS garmin_activities (
 activity_id TEXT PRIMARY KEY, local_date TEXT, activity_name TEXT,
 activity_type TEXT, duration_minutes REAL, distance_km REAL, calories REAL,
 average_hr REAL, training_load REAL);
CREATE TABLE IF NOT EXISTS ingestion_log (
 run_id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
 dataset TEXT NOT NULL, started_at TEXT NOT NULL,
 start_date TEXT, end_date TEXT, record_count INTEGER, status TEXT NOT NULL,
 error_type TEXT);
CREATE TABLE IF NOT EXISTS hc_body_fat (record_id TEXT PRIMARY KEY,
 local_date TEXT NOT NULL, app TEXT NOT NULL, body_fat_pct REAL);
CREATE TABLE IF NOT EXISTS hc_blood_pressure (record_id TEXT PRIMARY KEY,
 local_date TEXT NOT NULL, app TEXT NOT NULL, systolic REAL, diastolic REAL);
'''

def ensure_schema(db):
    db.executescript(SCHEMA)
    db.commit()

def nest(d,*keys):
    for k in keys:
        if not isinstance(d,dict): return None
        d=d.get(k)
    return d

def numeric(v,scale=1):
    try: return None if v is None else float(v)/scale
    except (ValueError,TypeError): return None

def meaningful_date(v):
    if not isinstance(v,str):return None
    try: return date.fromisoformat(v[:10]).isoformat()
    except ValueError: return None

def save_metrics(db,dt,**kw):
    dt=meaningful_date(dt)
    if dt is None: return False
    kw={k:v for k,v in kw.items() if k in METRICS and v is not None}
    if not kw:return False
    columns=list(kw)
    sql=(f"INSERT INTO garmin_daily (local_date,{','.join(columns)}) "
         f"VALUES ({','.join(['?']*(len(columns)+1))}) "
         f"ON CONFLICT(local_date) DO UPDATE SET "+','.join(f'{k}=excluded.{k}' for k in columns))
    db.execute(sql,[dt]+[kw[k] for k in columns]);return True

def _list_payload(data,name):
    if name=='daily_summaries':
        if isinstance(data,dict): return data.get('data') or []
    if name=='hrv_summaries':
        if isinstance(data,dict): return data.get('hrvSummaries') or []
    return data if isinstance(data,list) else []

def log_import(db,source,dataset,amount,status='ok',start=None,end=None,error=None):
    db.execute('INSERT INTO ingestion_log(source,dataset,started_at,start_date,end_date,record_count,status,error_type) VALUES(?,?,?,?,?,?,?,?)',
      (source,dataset,datetime.now().astimezone().isoformat(timespec='seconds'),start,end,amount,status,error))
    db.commit()

def import_dataset(db,name,data,source='Garmin JSON',start=None,end=None):
    ensure_schema(db)
    if name not in DATASETS: raise ValueError(f'Unknown dataset {name}')
    rows=_list_payload(data,name)
    if not isinstance(rows,list): raise ValueError(f'{name}: expected JSON list')
    count=0
    with db:
        for r in rows:
            if not isinstance(r,dict):continue
            if name=='daily_summaries':
                count += save_metrics(db,r.get('calendarDate'),
                  steps=numeric(nest(r,'movement','steps','value')),
                  distance_km=numeric(nest(r,'movement','steps','distanceInMeters'),1000),
                  calories_burned=numeric(nest(r,'calories','burnedTotal')),
                  calories_resting=numeric(nest(r,'calories','burnedResting')),
                  calories_active=numeric(nest(r,'calories','burnedActive')),
                  resting_hr=numeric(nest(r,'heartRate','restingValue')),
                  intensity_minutes=(numeric(nest(r,'intensityMinutes','moderate')) or 0)+2*(numeric(nest(r,'intensityMinutes','vigorous')) or 0)
                    if isinstance(r.get('intensityMinutes'),dict) else None,
                  stress_score=numeric(nest(r,'stress','avgLevel')),
                  body_battery_min=numeric(nest(r,'bodyBattery','minValue')),
                  body_battery_max=numeric(nest(r,'bodyBattery','maxValue')),
                  body_battery_charged=numeric(nest(r,'bodyBattery','chargedValue')),
                  body_battery_drained=numeric(nest(r,'bodyBattery','drainedValue')))
            elif name=='steps':
                count += save_metrics(db,r.get('calendarDate'),steps=numeric(r.get('totalSteps')),
                                      distance_km=numeric(r.get('totalDistance'),1000))
            elif name=='hrv_summaries':
                count += save_metrics(db,r.get('calendarDate'), hrv_ms=numeric(r.get('lastNightAvg')),
                  hrv_weekly_ms=numeric(r.get('weeklyAvg')),hrv_status=r.get('status'))
            elif name=='sleep_summaries':
                count += save_metrics(db,r.get('calendarDate'),
                  sleep_hours=numeric(r.get('sleepTimeSeconds'),3600),
                  deep_hours=numeric(r.get('deepSleepSeconds'),3600),
                  rem_hours=numeric(r.get('remSleepSeconds'),3600),
                  sleep_score=numeric(nest(r,'sleepScores','overall','value')))
            elif name=='stress':
                count += save_metrics(db,r.get('calendarDate'),
                  stress_score=numeric(nest(r,'values','overallStressLevel')))
            elif name=='body_battery':
                count += save_metrics(db,r.get('date'),
                  body_battery_charged=numeric(r.get('charged')),
                  body_battery_drained=numeric(r.get('drained')))
            elif name=='activities':
                act_id=r.get('activityId')
                dt=meaningful_date(r.get('startTimeLocal'))
                if act_id is None or not dt:continue
                db.execute('''INSERT INTO garmin_activities VALUES(?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(activity_id) DO UPDATE SET
                  local_date=excluded.local_date,activity_name=excluded.activity_name,
                  activity_type=excluded.activity_type,duration_minutes=excluded.duration_minutes,
                  distance_km=excluded.distance_km,calories=excluded.calories,
                  average_hr=excluded.average_hr,training_load=excluded.training_load''',
                  (str(act_id),dt,r.get('activityName'),nest(r,'activityType','typeKey'),
                   numeric(r.get('duration'),60),numeric(r.get('distance'),1000),
                   numeric(r.get('calories')),numeric(r.get('averageHR')),
                   numeric(r.get('activityTrainingLoad'))))
                count+=1
    log_import(db,source,name,count,start=start,end=end)
    return count

def import_garmin_zip(db,file):
    """Import JSON fixtures generated by the earlier Garmin test; no API key needed."""
    import zipfile
    if hasattr(file,'seek'):file.seek(0)
    with zipfile.ZipFile(file) as archive:
        names=[n for n in archive.namelist() if n.lower().endswith('.json')]
        result={}
        for dataset in DATASETS:
            matches=[n for n in names if Path(n).stem==dataset]
            if not matches:continue
            data=json.loads(archive.read(matches[0]).decode('utf8'))
            result[dataset]=import_dataset(db,dataset,data)
        if not result:raise ValueError('No recognized Garmin JSON files found in ZIP')
        return result

def _ranges(start,end,days=14):
    cur=start
    while cur<=end:
        finish=min(end,cur+timedelta(days=days-1))
        yield cur.isoformat(),finish.isoformat()
        cur=finish+timedelta(days=1)

def sync_garmin(db,start,end,progress=None,batch_days=14):
    """Fetch live data using the official Garmin Python package installed on user's computer."""
    from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator, resolve_api_key
    ensure_schema(db)
    if start>end:raise ValueError('Start date must be before end date')
    total=(end-start).days+1
    if total>366:raise ValueError('Limit one sync run to 366 days; use multiple runs for older history')
    if not 1 <= batch_days <= 14:raise ValueError('batch_days must be between 1 and 14')
    key=resolve_api_key()
    with PersonalApiAuthenticator() as auth:
        token=auth.obtain_token(key)
    getters={
      'daily_summaries': lambda cl,a,b:cl.get_daily_summaries(a,b),
      'steps':lambda cl,a,b:cl.get_daily_steps(a,b),
      'hrv_summaries':lambda cl,a,b:cl.get_daily_hrv_summaries(a,b),
      'sleep_summaries':lambda cl,a,b:cl.get_daily_sleep_summaries(a,b),
      'body_battery':lambda cl,a,b:cl.get_daily_body_battery(a,b),
      'stress':lambda cl,a,b:cl.get_daily_stress(a,b),
    }
    result={};errors=[]
    with GarminPersonalApiClient(token.access_token) as client:
        for a,b in _ranges(start,end,days=batch_days):
            for name,fn in getters.items():
                if progress:progress(f'{name}: {a} to {b}')
                try:
                    count=import_dataset(db,name,fn(client,a,b),source='Garmin API',start=a,end=b)
                    result[name]=result.get(name,0)+count
                except Exception as ex:
                    status=getattr(getattr(ex,'response',None),'status_code',None) or getattr(ex,'status_code',None)
                    kind=f'{type(ex).__name__} (HTTP {status})' if isinstance(status,int) else type(ex).__name__
                    errors.append(f'{name} ({a} to {b}): {kind}')
                    log_import(db,'Garmin API',name,0,'error',a,b,kind)
            # Pagination for activities; range boundaries are inclusive.
            offset=0
            while True:
                if progress:progress(f'activities: {a} to {b} (offset {offset})')
                try:
                    page=client.search_activities(start=offset,limit=100,start_date=a,end_date=b)
                    count=import_dataset(db,'activities',page,source='Garmin API',start=a,end=b)
                    result['activities']=result.get('activities',0)+count
                    if not isinstance(page,list) or len(page)<100:break
                    offset+=100
                    if offset>10000:
                        errors.append(f'activities {a} to {b}: pagination safety limit exceeded')
                        break
                except Exception as ex:
                    status=getattr(getattr(ex,'response',None),'status_code',None) or getattr(ex,'status_code',None)
                    kind=f'{type(ex).__name__} (HTTP {status})' if isinstance(status,int) else type(ex).__name__
                    errors.append(f'activities ({a} to {b}): {kind}')
                    log_import(db,'Garmin API','activities',0,'error',a,b,kind)
                    break
    return result,errors
