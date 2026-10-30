"""Unified Personal Health Dashboard — v0.7 analytics."""
import os
import sqlite3
from datetime import date,timedelta
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from importer import initialize, import_health_zip, import_backfill_csv, read_daily, read_weight
from datastore import read_frame
from insights_v06 import render_insights
from dashboard_v07 import (default_date_range, rolling_calorie_frame, calorie_chart,
                            group_working_sets, weekly_muscle_sets, workout_breakdown,
                            per_exercise_metrics)
from health_extra import import_health_extras
from garmin_importer import ensure_schema, import_garmin_zip, sync_garmin
from hevy_importer import ensure_hevy_schema, sync_hevy

st.set_page_config(page_title='Personal Health Analytics',layout='wide')
HOSTED=bool(os.environ.get('DATABASE_URL'))
DB=Path(os.environ.get('NUTRITION_DB',str(Path(__file__).resolve().parent / 'nutrition_analytics.sqlite')))
db=initialize(DB)
ensure_schema(db)
ensure_hevy_schema(db)
TODAY=pd.Timestamp.now(tz='America/New_York').date()

def sql(query,params=()):return read_frame(db, query, params)

def daily_table(query):
    frame=sql(query)
    if 'local_date' in frame:
        frame['local_date']=pd.to_datetime(frame.local_date)
        frame=frame.set_index('local_date').sort_index()
    return frame

def filtered(df,start,end):
    return df.loc[str(start):str(end)] if not df.empty else df

def line_chart(df,columns,title,ylabel=''):
    candidates=[x for x in columns if x in df and df[x].notna().any()]
    if not candidates:
        st.info(f'No measurements available for {title.lower()} in the selected period.')
        return
    melted=df[candidates].reset_index().melt(id_vars='local_date',var_name='Metric',value_name='Value').dropna()
    fig=px.line(melted,x='local_date',y='Value',color='Metric',labels={'local_date':'Date','Value':ylabel},title=title)
    fig.update_layout(margin=dict(l=0,r=0,b=0,t=50),legend_title_text='')
    st.plotly_chart(fig,use_container_width=True)

def metric_or_dash(v,fmt=',.0f'):
    return f'{v:{fmt}}' if pd.notna(v) else '—'

def last_value(df,col):
    if df.empty or col not in df:return float('nan')
    x=df[col].dropna()
    return x.iloc[-1] if not x.empty else float('nan')

st.title('Personal Health Analytics')
st.caption('Personal dashboard · Source-aware metrics · Missing records are not zero')

with st.sidebar:
    st.header('Calorie goal')
    # Set these optionally through private Streamlit Secrets, never source.
    calorie_goal=st.number_input('Current daily calorie target (kcal)',
        min_value=1000,max_value=6000,step=25,
        value=int(os.environ.get('CALORIE_GOAL','2500')),key='calorie_goal')
    calorie_tolerance=st.number_input('Goal range (± kcal)',
        min_value=0,max_value=500,step=25,
        value=int(os.environ.get('CALORIE_TOLERANCE','100')),key='calorie_tolerance')
    st.caption('Manual reference target; not imported from Garmin or MyFitnessPal. '
               'The current goal line is shown across the selected period, even if your historical goal differed.')
    st.divider()
    st.header('Data integrations')
    if HOSTED:
        st.info('Cloud mode: Garmin and Hevy sync through scheduled jobs. Upload raw Health Connect backups only in your local installation; migrate the selected records to PostgreSQL.')
        st.caption('Database: PostgreSQL (hosted)')
    else:
        with st.expander('Health Connect import',expanded=False):
            hc_upload=st.file_uploader('Health Connect ZIP',type='zip',key='hc')
            if hc_upload is not None and st.button('Import snapshot',use_container_width=True):
                try:
                    with st.spinner('Reading Health Connect database…'):
                        nutrition,weights=import_health_zip(db,hc_upload)
                        extras=import_health_extras(db,hc_upload)
                    st.success(f'{nutrition} meal records, {weights} weight records, {extras["body_fat"]} body-fat, {extras["blood_pressure"]} BP imported or updated.')
                    st.rerun()
                except Exception as ex:st.error(f'Import error: {type(ex).__name__}: {str(ex)[:180]}')
            backfill=st.file_uploader('Normalized nutrition CSV',type='csv',key='csv')
            if backfill is not None and st.button('Import nutrition backfill'):
                try:
                    n=import_backfill_csv(db,backfill);st.success(f'{n} date rows imported.');st.rerun()
                except Exception as ex:st.error(f'Backfill error: {type(ex).__name__}: {str(ex)[:180]}')
        with st.expander('Garmin import / sync',expanded=True):
            garmin_zip=st.file_uploader('Garmin JSON output ZIP (offline)',type='zip',key='garmin')
            if garmin_zip is not None and st.button('Import Garmin JSON',use_container_width=True):
                try:
                    result=import_garmin_zip(db,garmin_zip)
                    st.success('Imported / updated: '+', '.join(f'{k} {v}' for k,v in result.items()))
                    st.rerun()
                except Exception as ex:st.error(f'Garmin ZIP error: {type(ex).__name__}: {str(ex)[:180]}')
            with st.form('garmin_sync'):
                from_date=st.date_input('Sync from',value=TODAY-timedelta(days=30),max_value=TODAY,key='gs')
                to_date=st.date_input('Sync through',value=TODAY,max_value=TODAY,key='ge')
                trigger=st.form_submit_button('Sync Garmin now',use_container_width=True)
            if trigger:
                status=st.empty()
                try:
                    with st.spinner('Retrieving Garmin data…'):
                        result,errors=sync_garmin(db,from_date,to_date,progress=status.caption)
                    status.empty()
                    st.success('Imported / updated: '+', '.join(f'{k} {v}' for k,v in result.items()))
                    if errors:st.warning(f'{len(errors)} dataset requests failed; see diagnostic log. '+', '.join(errors[:3]))
                    if not errors:st.rerun()
                except Exception as ex:
                    status.empty()
                    st.error(f'Garmin synchronization failed ({type(ex).__name__}). Confirm Python 3.12+, installed dependencies and local API key file.')
        with st.expander('Hevy strength training sync',expanded=True):
            st.caption('Read-only Hevy Pro API. Key from a local file or HEVY_API_KEY environment variable.')
            st.code(r'%USERPROFILE%\.config\hevy\api-key',language=None)
            hevy_full=st.checkbox('Force full Hevy history reconciliation',value=False,
                help='First sync always imports all history. Later syncs process only updates and deletions.')
            if st.button('Sync Hevy now',use_container_width=True):
                progress_box=st.empty()
                try:
                    with st.spinner('Retrieving Hevy workouts…'):
                        outcome=sync_hevy(db,full=hevy_full,progress=progress_box.caption)
                    progress_box.empty()
                    st.success('Hevy '+outcome['mode']+' sync complete: '+
                       ', '.join(f'{key} {outcome[key]}' for key in ('new','updated','unchanged','deleted')))
                    st.rerun()
                except Exception as ex:
                    progress_box.empty()
                    # Avoid dumping exception tracebacks or URL headers into visible logs.
                    st.error(f'Hevy sync failed ({type(ex).__name__}): {str(ex)[:180]}')
        st.caption('Database: PostgreSQL' if os.environ.get('DATABASE_URL') else f'Local database: `{DB.resolve()}`')

daily=read_daily(db)
weight=read_weight(db)
if not isinstance(weight,pd.Series):weight=pd.Series(dtype='float64',name='weight_lb')
weight.index.name='local_date'
garmin=daily_table('SELECT * FROM garmin_daily')
bp=daily_table('''SELECT local_date,AVG(systolic) AS systolic,AVG(diastolic) AS diastolic,COUNT(*) AS readings
 FROM hc_blood_pressure GROUP BY local_date''')
body_fat=daily_table('''SELECT local_date,AVG(body_fat_pct) AS body_fat_pct
 FROM hc_body_fat GROUP BY local_date''')
activity=daily_table('''SELECT local_date,activity_name,activity_type,duration_minutes,distance_km,calories,average_hr,training_load
 FROM garmin_activities ORDER BY local_date DESC''')
hevy_workouts=daily_table('''SELECT workout_id,local_date,title,duration_minutes,start_time
 FROM hevy_workouts ORDER BY local_date DESC''')
hevy_sets=sql('''SELECT w.workout_id,w.local_date,w.title AS workout_title,e.title AS exercise,
 e.template_id,e.exercise_index,s.set_index,s.set_type,s.weight_kg,s.reps,s.rpe
 FROM hevy_workouts w JOIN hevy_exercises e ON w.workout_id=e.workout_id
 JOIN hevy_sets s ON s.workout_id=e.workout_id AND s.exercise_index=e.exercise_index''')
if not hevy_sets.empty:
    hevy_sets['local_date']=pd.to_datetime(hevy_sets['local_date'])
    hevy_sets['weight_lb']=hevy_sets['weight_kg']*2.20462262185
    hevy_sets['load_volume_lb']=hevy_sets['weight_lb']*hevy_sets['reps']
    hevy_sets['working_set']=hevy_sets['set_type'].isin(['normal','failure','dropset'])
    hevy_sets['estimated_1rm_lb']=hevy_sets['weight_lb']*(1+hevy_sets['reps']/30)
    hevy_sets.loc[~hevy_sets['working_set'] | ~hevy_sets['reps'].between(1,10) |
       ~hevy_sets['weight_lb'].gt(0),'estimated_1rm_lb']=float('nan')
frames=[x for x in [daily,garmin,bp,body_fat,hevy_workouts] if not x.empty]
if not weight.empty:frames.append(weight.to_frame())
if not frames:
    st.info('No data yet. Import your existing Health Connect ZIP and Garmin JSON ZIP using the sidebar.')
    st.stop()
oldest=min(frame.index.min().date() for frame in frames)
latest=max(frame.index.max().date() for frame in frames)
start_default,end_default=default_date_range(TODAY,oldest)
a,b=st.columns(2)
start=a.date_input('Start date',value=start_default,min_value=oldest,max_value=TODAY)
end=b.date_input('End date',value=end_default,min_value=oldest,max_value=TODAY)
if start>end:st.error('Start date must be before end date.');st.stop()

def f(df):return filtered(df,start,end)
nd=f(daily);g=f(garmin);w=f(weight.to_frame());hrv=g if not g.empty else pd.DataFrame()

pages=st.tabs(['Overview','Nutrition','Body composition','Garmin & recovery','Training & strength','Blood pressure','Data quality','Insights'])
with pages[0]:
    st.subheader('At a glance')
    last30_start=max(start,end-timedelta(days=29))
    n30=filtered(daily,last30_start,end)
    g30=filtered(garmin,last30_start,end)
    k1,k2,k3,k4=st.columns(4)
    k1.metric('Last Renpho weight',metric_or_dash(last_value(w,'weight_lb'),',.1f')+' lb' if not w.empty else '—')
    k2.metric('Avg logged intake',metric_or_dash(n30.calories.mean() if 'calories' in n30 else float('nan'))+' kcal')
    k3.metric('Avg Garmin expenditure',metric_or_dash(g30.calories_burned.mean() if 'calories_burned' in g30 else float('nan'))+' kcal')
    k4.metric('Latest overnight HRV',metric_or_dash(last_value(g,'hrv_ms'))+' ms')
    c1,c2=st.columns(2)
    with c1:
        if not w.empty:
            wt=w.copy();wt['7-day rolling avg']=wt.weight_lb.rolling('7D',min_periods=3).mean()
            line_chart(wt,['weight_lb','7-day rolling avg'],'Body weight','lb')
        else:st.info('No Renpho weight available in selected period.')
    with c2:
        if not g.empty:line_chart(g,['calories_burned'],'Garmin estimated daily expenditure','kcal')
        else:st.info('Import Garmin data to show expenditure.')
    st.caption('Garmin expenditure is a wearable estimate, not directly measured TDEE. Use Energy balance Insights for weight-derived estimates and coverage checks.')

with pages[1]:
    st.subheader('Nutrition')
    if daily.empty:st.info('Import a Health Connect archive to populate nutrition.');
    else:
        # Ignore an in-progress current date even when manually selected.
        completed_end=min(end,TODAY-timedelta(days=1))
        if start>completed_end:
            st.info('No completed days in the selected range. Try ending at yesterday.')
        else:
            complete=filtered(daily,start,completed_end).reindex(pd.date_range(start,completed_end,freq='D'))
            complete.index.name='local_date'
            missing=complete.index[complete.calories.isna()]
            # Build averages from historical context before the visible range.
            nutrition_history=rolling_calorie_frame(daily,completed_end)
            trends=filtered(nutrition_history,start,completed_end)
            c1,c2,c3,c4=st.columns(4)
            c1.metric('Mean logged intake',metric_or_dash(complete.calories.mean())+' kcal')
            c2.metric('7-day average',metric_or_dash(trends.avg7.iloc[-1])+' kcal' if not trends.empty else '—')
            c3.metric('30-day average',metric_or_dash(trends.avg30.iloc[-1])+' kcal' if not trends.empty else '—')
            c4.metric('Days with nutrition',f'{int(complete.calories.notna().sum())}/{len(complete)}')
            if len(missing):
                st.warning(f'Completed dates without nutrition records ({len(missing)}): '+
                    ', '.join(x.strftime('%b %d') for x in missing[:14])+
                    (' …' if len(missing)>14 else '')+
                    '. Missing dates are not treated as zero calories.')
            if not trends.empty:
                st.plotly_chart(calorie_chart(trends,calorie_goal,calorie_tolerance),
                                use_container_width=True)
                st.caption('The 7-day average requires at least five likely complete logs; '
                    'the 30-day average requires at least 21. Today is excluded. '
                    'Goal and acceptable range are configured in the sidebar, not read from either app.')
            line_chart(complete,['protein_g','carbs_g','fat_g'],'Macronutrients','grams')
            with st.expander('Fiber, sodium and potassium'):
                for col,label,unit in [('fiber_g','Fiber','g'),('sodium_mg','Sodium','mg'),('potassium_mg','Potassium','mg')]:
                    line_chart(complete,[col],label,unit)
            st.dataframe(complete.sort_index(ascending=False),use_container_width=True)
            st.download_button('Download nutrition CSV',complete.to_csv(),file_name='nutrition_by_day.csv',mime='text/csv')

with pages[2]:
    st.subheader('Weight and body composition')
    if w.empty:st.info('No Renpho weight measurements in selected period.')
    else:
        wt=w.copy();wt['7-day rolling avg']=wt.weight_lb.rolling('7D',min_periods=3).mean()
        line_chart(wt,['weight_lb','7-day rolling avg'],'Renpho weight trend','lb')
    bf=f(body_fat)
    if not bf.empty:
        line_chart(bf,['body_fat_pct'],'Renpho body-fat estimates','%')
        st.caption('Bioelectrical impedance values vary with hydration and measurement conditions. Interpret multiweek trends rather than individual readings.')
    else:st.info('Reimport the Health Connect ZIP in this version to load Renpho body-fat records.')

with pages[3]:
    st.subheader('Garmin activity and recovery')
    if g.empty:st.info('Import Garmin JSON or use Sync Garmin now in the sidebar.')
    else:
        cols=st.columns(4)
        cols[0].metric('Last resting HR',metric_or_dash(last_value(g,'resting_hr'))+' bpm')
        cols[1].metric('Avg overnight HRV',metric_or_dash(g.hrv_ms.mean(),'.1f')+' ms')
        cols[2].metric('Avg sleep',metric_or_dash(g.sleep_hours.mean(),'.1f')+' h')
        cols[3].metric('Avg daily steps',metric_or_dash(g.steps.mean()))
        line_chart(g,['hrv_ms','hrv_weekly_ms'],'Overnight HRV and Garmin 7-day HRV average','ms')
        line_chart(g,['sleep_hours','deep_hours','rem_hours'],'Sleep duration and stages','hours')
        line_chart(g,['steps'],'Daily steps','steps')
        line_chart(g,['resting_hr'],'Resting heart rate','bpm')
        line_chart(g,['stress_score'],'Garmin stress score','score')
        line_chart(g,['body_battery_min','body_battery_max'],'Body Battery daily range','score')
        line_chart(g,['calories_burned','calories_resting','calories_active'],'Garmin calorie expenditure','kcal')
    st.subheader('Garmin activities')
    if activity.empty:st.info('No Garmin activities imported.')
    else:
        acts=f(activity)
        if acts.empty:st.info('No Garmin activities in the date range.')
        else:st.dataframe(acts.sort_index(ascending=False),use_container_width=True)
    st.caption('Garmin activity records may overlap with Hevy strength sessions. They are not added to Hevy workout counts. Physiological metrics are wellness indicators, not diagnostic tests.')

with pages[4]:
    st.subheader('Training & strength (Hevy)')
    st.caption('Hevy is the source of truth for strength sessions and their recorded sets. Garmin activities are presented separately, never added to Hevy counts.')
    if hevy_workouts.empty:
        st.info('Sync Hevy using the sidebar. The first successful sync imports your full workout history.')
    else:
        sessions=filtered(hevy_workouts,start,end)
        sets=hevy_sets[hevy_sets.local_date.between(pd.Timestamp(start),pd.Timestamp(end))].copy() if not hevy_sets.empty else pd.DataFrame()
        k1,k2,k3,k4=st.columns(4)
        k1.metric('Workout sessions',str(len(sessions)))
        k2.metric('Working sets',str(int(sets.working_set.sum())) if not sets.empty else '0')
        k3.metric('Exercises recorded',str(sets.exercise.nunique()) if not sets.empty else '0')
        k4.metric('Last Hevy session',sessions.index.max().strftime('%b %d, %Y') if not sessions.empty else '—')
        if not sessions.empty:
            weekly=sessions.groupby(sessions.index.to_period('W-SUN').start_time).size().rename('Sessions')
            weekly.index.name='Week'
            st.plotly_chart(px.bar(weekly.reset_index(),x='Week',y='Sessions',title='Strength sessions per week'),use_container_width=True)
        if not sets.empty:
            grouped=group_working_sets(sets,start,end)
            weekly_groups=weekly_muscle_sets(grouped)
            st.subheader('Weekly working sets by primary muscle group')
            if not weekly_groups.empty:
                st.plotly_chart(px.bar(weekly_groups,x='week',y='sets',color='group',
                    barmode='stack',title='Primary-muscle working sets per week',
                    labels={'week':'Week starting','sets':'Working sets','group':'Primary group'}),
                    use_container_width=True)
                with st.expander('Weekly sets by muscle group (table)'):
                    table=weekly_groups.pivot(index='week',columns='group',values='sets').fillna(0).astype(int)
                    table['Total']=table.sum(axis=1)
                    st.dataframe(table,use_container_width=True)
            st.caption('Each working set counts once toward the exercise\'s primary group; compound sets '
                'are not split across secondary muscles. Warmups excluded; normal, failure, and drop sets included.')

            st.subheader('Workout muscle-group breakdown')
            if not sessions.empty and not grouped.empty:
                options_sessions=list(sessions.workout_id)
                labels={row.workout_id:f'{idx:%b %d, %Y} — {row.title}' for idx,row in sessions.iterrows()}
                workout_id=st.selectbox('Choose a workout',options_sessions,
                    format_func=lambda item:labels.get(item,item),key='training_workout_pie')
                distribution=workout_breakdown(grouped,workout_id)
                if not distribution.empty:
                    c_pie,c_table=st.columns([2,3])
                    with c_pie:
                        st.plotly_chart(px.pie(distribution,names='group',values='sets',hole=0.4,
                            title='Working sets by primary group'),use_container_width=True)
                    with c_table:
                        session_sets=grouped[grouped.workout_id==workout_id]
                        breakdown=(session_sets.groupby(['exercise','group']).size()
                            .rename('Working sets').reset_index().sort_values('Working sets',ascending=False))
                        st.dataframe(breakdown,use_container_width=True,hide_index=True)
                else:
                    st.info('No eligible working sets in this workout.')
                st.caption('This summarizes set allocation, not measured muscle activation or '
                    'hypertrophy-equivalent sets. Back-off sets are included.')

            st.subheader('Strength progression and volume by exercise')
            options=sorted(sets.exercise.dropna().unique())
            if options:
                defaults=[x for x in options if x in ('Bench Press (Barbell)','Deadlift (Barbell)')]
                preferred=defaults[0] if defaults else options[0]
                exercise=st.selectbox('Exercise',options,index=options.index(preferred))
                selected=sets[sets.exercise==exercise].copy()
                day_best=per_exercise_metrics(sets,exercise)
                if not day_best.empty:
                    c_strength,c_volume=st.columns(2)
                    with c_strength:
                        if day_best.estimated_1rm_lb.notna().any():
                            st.plotly_chart(px.line(day_best,x='local_date',y='estimated_1rm_lb',markers=True,
                                title='Estimated 1RM by workout',labels={'local_date':'Date','estimated_1rm_lb':'e1RM (lb)'}),
                                use_container_width=True)
                        else:
                            st.info('No eligible 1–10 rep sets to estimate 1RM.')
                    with c_volume:
                        if day_best.volume_lb.notna().any():
                            st.plotly_chart(px.bar(day_best,x='local_date',y='volume_lb',
                                title='Total loaded volume by workout',labels={'local_date':'Date','volume_lb':'Weight × reps (lb)'}),
                                use_container_width=True)
                        else:
                            st.info('No weighted sets available for the volume calculation.')
                    st.dataframe(day_best.sort_values('local_date',ascending=False),use_container_width=True,hide_index=True)
                st.caption('Volume sums weight × reps for weighted working sets, including back-off and drop sets; '
                    'it excludes warmups and cannot estimate bodyweight or assistance-machine resistance. '
                    'Epley 1RM is estimated from eligible 1–10 rep sets and is not a tested maximum.')
                columns=['local_date','workout_title','set_type','weight_lb','reps','rpe','estimated_1rm_lb']
                st.dataframe(selected[columns].sort_values('local_date',ascending=False),
                             use_container_width=True,hide_index=True)
                with st.expander('Top exercises by recorded working sets'):
                    st.dataframe(grouped.groupby('exercise').size().sort_values(ascending=False)
                                 .rename('Sets').to_frame(),use_container_width=True)
        st.subheader('Hevy sessions')
        if not sessions.empty:
            st.dataframe(sessions[['title','duration_minutes']].sort_index(ascending=False),use_container_width=True)
        else:st.info('No sessions in this date range.')

with pages[5]:
    st.subheader('Blood pressure')
    if bp.empty:st.info('Reimport Health Connect ZIP to load available blood-pressure records.')
    else:
        daybp=f(bp)
        line_chart(daybp,['systolic','diastolic'],'Blood pressure (daily average)','mmHg')
        st.dataframe(daybp.sort_index(ascending=False),use_container_width=True)
        st.caption('Imported from Health Connect. Daily averages may conceal within-day variation; do not use this chart alone to diagnose or change medication.')

with pages[6]:
    st.subheader('Sources and data freshness')
    st.caption('Latest stored dates indicate data freshness, not whether an account is currently connected. Today may be incomplete.')
    checks=[('MyFitnessPal nutrition','nutrition','local_date','date'),('Renpho weight','weights','local_date','date'),
            ('Renpho body fat','hc_body_fat','local_date','date'),('Blood pressure','hc_blood_pressure','local_date','date'),
            ('Garmin daily metrics','garmin_daily','local_date','date'),('Garmin activities','garmin_activities','local_date','date'),
            ('Hevy strength workouts','hevy_workouts','local_date','date')]
    report=[]
    for label,table,col,_ in checks:
        cnt,mind,maxd=db.execute(f'SELECT COUNT(*),MIN({col}),MAX({col}) FROM {table}').fetchone()
        age=(TODAY-date.fromisoformat(maxd)).days if maxd else None
        report.append({'Source':label,'Records':cnt,'Earliest':mind,'Latest':maxd,'Days since latest':age,'Status':('No data' if not cnt else 'Potentially stale' if age is not None and age>2 else 'Recent')})
    st.dataframe(pd.DataFrame(report),use_container_width=True,hide_index=True)
    last_hevy=db.execute("SELECT value FROM hevy_sync_state WHERE key='last_success_utc'").fetchone()
    st.caption('Last successful Hevy API synchronization: '+(last_hevy[0] if last_hevy else 'Not yet synced'))
    st.subheader('Garmin metric availability')
    metrics=[('Daily energy','calories_burned'),('Steps','steps'),('Resting HR','resting_hr'),('HRV','hrv_ms'),('Sleep','sleep_hours'),('Stress','stress_score'),('Body Battery','body_battery_min')]
    summaries=[]
    for label,col in metrics:
        count,earliest,latest=db.execute(f'SELECT COUNT({col}),MIN(CASE WHEN {col} IS NOT NULL THEN local_date END),MAX(CASE WHEN {col} IS NOT NULL THEN local_date END) FROM garmin_daily').fetchone()
        summaries.append({'Metric':label,'Days recorded':count,'First date':earliest,'Latest date':latest})
    st.dataframe(pd.DataFrame(summaries),use_container_width=True,hide_index=True)
    st.subheader('Recent ingestion results')
    log=sql('SELECT started_at,source,dataset,start_date,end_date,record_count,status,error_type FROM ingestion_log ORDER BY run_id DESC LIMIT 40')
    if not log.empty:st.dataframe(log,use_container_width=True,hide_index=True)
    else:st.info('No Garmin imports yet.')
    st.caption('Nutrition backfills only fill absent dates; when Health Connect records exist, they take precedence. Run an explicit date reconciliation before using calorie balance for clinical decisions.')


with pages[7]:
    insight_log=sql('SELECT run_id,started_at,source,dataset,record_count,status,error_type FROM ingestion_log ORDER BY run_id DESC LIMIT 1000')
    hevy_sync_row=db.execute("SELECT value FROM hevy_sync_state WHERE key='last_success_utc'").fetchone()
    render_insights(daily,weight,garmin,hevy_sets,hevy_workouts,insight_log,start,end,TODAY,
                    hevy_last_success=hevy_sync_row[0] if hevy_sync_row else None,
                    calorie_goal=calorie_goal)
