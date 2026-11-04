"""Source freshness is independent of the selected historical analysis dates.

Sync timestamps describe successful requests, not proof that a device exported
new measurements. Hevy/BP/activity dates are not expected to change every day.
Thresholds are operational grace periods, not health recommendations.
"""
import pandas as pd
from datastore import read_frame

GARMIN_DATASETS=('daily_summaries','steps','hrv_summaries','sleep_summaries',
                 'body_battery','stress','activities')


def timestamp(value):
    return pd.to_datetime(value,errors='coerce',utc=True)


def sync_status(label,logs,now,grace_hours):
    records=logs.copy()
    if 'started_at' not in records:
        records=pd.DataFrame(columns=['started_at','status'])
    records['time']=pd.to_datetime(records.started_at,errors='coerce',utc=True)
    records=records.dropna(subset=['time']).sort_values('time')
    success=records[records.status.eq('ok')]
    last=success.time.max() if len(success) else pd.NaT
    checked=records.time.max() if len(records) else pd.NaT
    status='Not recorded'
    detail='No successful check recorded; inspect scheduled jobs.'
    if len(records) and checked>now+pd.Timedelta(minutes=5):
        status='Clock mismatch';detail='A recorded check is in the future; verify timestamps.'
    elif len(records) and records.iloc[-1].status=='error':
        status='Latest check failed';detail='Latest recorded request failed; a later successful check clears this notice.'
    elif pd.notna(last):
        if now-last>pd.Timedelta(hours=grace_hours):
            status='Check overdue';detail=f'No successful check within {grace_hours:g} hours.'
        else:
            status='Recent check';detail='Successful request recorded; measurement coverage is checked separately.'
    def display(t):
        return t.tz_convert('America/New_York').strftime('%b %d, %Y %I:%M %p %Z') if pd.notna(t) else 'Not recorded'
    return {'Source':label,'Status':status,'Last successful check':display(last),
            'Last recorded check':display(checked),'Expectation':f'Within {grace_hours:g} h','Detail':detail}


def sync_health(logs,hevy_last,now):
    now=timestamp(now)
    if logs is None or logs.empty:
        logs=pd.DataFrame(columns=['source','dataset','started_at','status'])
    rows=[]
    for dataset in GARMIN_DATASETS:
        selected=logs[logs.source.eq('Garmin API') & logs.dataset.eq(dataset)]
        rows.append(sync_status('Garmin · '+dataset.replace('_',' '),selected,now,18))
    selected=logs[logs.source.eq('Health Connect Drive') &
                  (logs.dataset.str.startswith('drive_zip:',na=False) | logs.dataset.eq('drive_check'))]
    row=sync_status('Health Connect Drive',selected,now,36)
    if not selected.dataset.eq('drive_check').any():
        row['Detail']+=' Older runs record completed imports only, not unchanged-export checks.'
    row['Detail']+=' Failed pre-import attempts must be checked in GitHub Actions.'
    rows.append(row)
    hevy=pd.DataFrame([{'started_at':hevy_last,'status':'ok'}]) if hevy_last else pd.DataFrame()
    row=sync_status('Hevy',hevy,now,36)
    row['Detail']+=' Failed Hevy attempts are not logged here; consult GitHub Actions.'
    rows.append(row)
    return pd.DataFrame(rows)


def measurement_health(daily,weight,garmin,bp,body_fat,workouts,today):
    today=pd.Timestamp(today).normalize()
    dates=pd.date_range(end=today-pd.Timedelta(days=1),periods=7)
    rows=[]
    def add(label,values,grace=None,positive=False):
        values=pd.to_numeric(values,errors='coerce').replace([float('inf'),float('-inf')],float('nan')).dropna()
        values.index=pd.to_datetime(values.index).normalize()
        values=values[(values.index<=today) & (values.gt(0) if positive else values.ge(0))]
        latest=values.index.max() if len(values) else pd.NaT
        days=int(values.index.intersection(dates).nunique())
        if grace is None:
            status='On demand';expectation='When measured or trained'
        elif pd.isna(latest):
            status='No measurements';expectation=f'Within {grace} calendar days'
        else:
            status='Measurement lag' if (today-latest).days>grace else 'Recent measurements'
            expectation=f'Within {grace} calendar days'
        rows.append({'Measurement':label,'Status':status,
            'Latest date':latest.date().isoformat() if pd.notna(latest) else 'Not recorded',
            'Days measured · last 7 completed':days,'Expectation':expectation})
    def field(frame,name):
        return frame[name] if frame is not None and name in frame else pd.Series(dtype=float)
    calories=field(daily,'calories')
    meals=field(daily,'meals')
    usable=calories.where(pd.to_numeric(meals,errors='coerce').ge(3))
    add('Nutrition · logging proxy',usable,2,True)
    add('Body weight',weight if isinstance(weight,pd.Series) else field(weight,'weight_lb'),3,True)
    for name,label,positive in [('calories_burned','Garmin expenditure',True),
        ('steps','Garmin steps',False),('intensity_minutes','Garmin intensity minutes',False),
        ('sleep_hours','Garmin sleep',True),('hrv_ms','Garmin HRV',True),
        ('resting_hr','Garmin resting HR',True)]:
        add(label,field(garmin,name),2,positive)
    # Event-driven measurements are displayed but never treated as a failed pipeline.
    add('Blood pressure',field(bp,'systolic'),None,True)
    add('Body fat',field(body_fat,'body_fat_pct'),None,True)
    add('Hevy workout',pd.Series(1.,index=workouts.index) if workouts is not None else pd.Series(dtype=float))
    return pd.DataFrame(rows)


def load_sync_health(db,now):
    logs=read_frame(db,'SELECT source,dataset,started_at,status FROM ingestion_log ORDER BY run_id DESC LIMIT 500')
    state=db.execute("SELECT value FROM hevy_sync_state WHERE key='last_success_utc'").fetchone()
    return sync_health(logs,state[0] if state else None,now)


def render_freshness(sync,measurements):
    import streamlit as st
    sync_bad=sync[~sync.Status.isin(['Recent check','Not recorded'])]
    data_bad=measurements[measurements.Status.isin(['Measurement lag','No measurements'])]
    unknown=int(sync.Status.eq('Not recorded').sum())
    count=len(sync_bad)+len(data_bad)
    if count:
        labels=list(sync_bad.Source)+list(data_bad.Measurement)
        st.warning(f'Data freshness: {count} item(s) need review · '+', '.join(labels[:3])+
                   (' · see source details below' if count>3 else ''))
    elif unknown:
        st.info(f'Data freshness: no measurement-lag flags; {unknown} sync check(s) are not recorded.')
    else:
        st.success('Data freshness: recent sync checks and measurements. Coverage may still be incomplete.')
    with st.expander('Source freshness and coverage'):
        st.caption('Live source status uses today in America/New_York, independently of the selected chart dates. '
                   'Coverage counts the last seven completed days, excluding today. '
                   'These are database check records, not a live GitHub status feed.')
        st.dataframe(sync,hide_index=True,use_container_width=True)
        st.dataframe(measurements,hide_index=True,use_container_width=True)
        st.caption('Grace periods: Garmin checks 18 h; Health Connect and Hevy 36 h; '
                   'daily measurements 2 calendar days; weight 3. These allow scheduling/export delays. '
                   'Missing workouts, BP or body-fat readings do not imply failed syncing. '
                   'Three meal records are only a logging proxy, not proof of complete food logging.')
