"""Personal Health Dashboard — focused v0.8 views."""
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
from insights_v06 import energy_window, estimate_tdee
from dashboard_v07 import (default_date_range, rolling_calorie_frame,
                            group_working_sets, weekly_muscle_sets, workout_breakdown,
                            per_exercise_metrics)
from dashboard_v08 import (fmt, summary, recent_logged_intake, recent_garmin,
    recent_lift, weight_smoothed, weight_chart, calories_chart, expenditure_chart,
    muscle_counts, muscle_chart, exercise_chart)
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


# Navigation follows the user's decision priorities; deep dives are opt-in.
pages=st.tabs(["Overview","Energy & Nutrition","Training","Recovery & Health","Data & Sync"])
COMPLETED_END=min(end,TODAY-timedelta(days=1))
DISPLAY_START=max(start,COMPLETED_END-timedelta(days=44))
def period_frame(data,begin_date,finish_date):
    return filtered(data,begin_date,finish_date)

with pages[0]:
    st.subheader("Overview")
    st.caption(f"Completed days through {COMPLETED_END:%b %d, %Y}. "
               "The main indicators use recent weeks ending on the selected date.")
    if start>COMPLETED_END:
        st.info("Select an earlier end date to see completed days.")
    else:
        m28=summary(daily,weight,garmin,COMPLETED_END,28)
        i7,n7=recent_logged_intake(daily,COMPLETED_END,7)
        ga28,gdays=recent_garmin(garmin,COMPLETED_END,28)
        weights7=weight_smoothed(weight,COMPLETED_END)
        w7=weights7.dropna().iloc[-1] if weights7.notna().any() else float('nan')
        a,b,c,d=st.columns(4)
        a.metric("Body weight · 7-day avg",fmt(w7,1)+" lb" if pd.notna(w7) else "—")
        b.metric("Calorie intake · 7-day avg",fmt(i7)+" kcal" if pd.notna(i7) else "—")
        c.metric("Calculated TDEE · 28 days",fmt(m28["estimated_tdee"])+" kcal"
                 if m28["valid"] else "—")
        d.metric("Garmin expenditure · 28 days",fmt(ga28)+" kcal"
                 if pd.notna(ga28) else "—")
        st.caption(f"Nutrition coverage: {n7}/7 days · Garmin: {gdays}/28 days · "
                   f"28-day weight trend: {fmt(m28['trend_lb_week'],2)} lb/week"
                   if m28["valid"] else
                   f"Nutrition coverage: {n7}/7 days · Garmin: {gdays}/28 days · "
                   "Calculated TDEE needs sufficient consistent records.")
        col_weight,col_food=st.columns(2)
        with col_weight:
            st.plotly_chart(weight_chart(weight,DISPLAY_START,COMPLETED_END),
                            use_container_width=True)
        with col_food:
            # A single smoothed intake series: the target and daily bars are
            # available separately in the Nutrition deep dive.
            history=rolling_calorie_frame(daily,COMPLETED_END)
            visible=period_frame(history,DISPLAY_START,COMPLETED_END)
            if not visible.empty and visible["avg7"].notna().any():
                fig=px.line(visible,x=visible.index,y="avg7",
                            labels={"x":"Date","avg7":"kcal/day"},
                            title="Calorie intake · 7-day average")
                fig.update_layout(showlegend=False,
                                  margin=dict(l=5,r=5,b=5,t=50))
                st.plotly_chart(fig,use_container_width=True)
            else:
                st.info("Not enough completed nutrition days for the 7-day intake trend.")
        st.caption("These charts show one smoothed measurement each. "
                   "The calculated TDEE is a rough weight-trend estimate, not a direct measurement.")

        st.subheader("Strength snapshot")
        bench=recent_lift(hevy_sets,"Bench Press (Barbell)",COMPLETED_END)
        deadlift=recent_lift(hevy_sets,"Deadlift (Barbell)",COMPLETED_END)
        count_sessions=int((hevy_workouts.index.to_series().between(
            pd.Timestamp(COMPLETED_END)-pd.Timedelta(days=27),
            pd.Timestamp(COMPLETED_END))).sum()) if not hevy_workouts.empty else 0
        a,b,c=st.columns(3)
        for slot,caption,lift in ((a,"Bench press · estimated 1RM",bench),
                                  (b,"Deadlift · estimated 1RM",deadlift)):
            if lift:
                slot.metric(caption,fmt(lift["value"])+" lb",
                            delta=fmt(lift["change"])+" lb vs previous"
                            if lift["change"] is not None else None)
                slot.caption(f"Latest eligible workout: {lift['date']:%b %d}")
            else:
                slot.metric(caption,"—")
        c.metric("Strength workouts · 28 days",str(count_sessions))
        st.caption("Estimated 1RMs use eligible Hevy working sets. "
                   "Open Training for individual lifts, weekly sets and workout breakdowns.")

        st.subheader("Recovery snapshot")
        recent_recovery=period_frame(garmin,COMPLETED_END-timedelta(days=6),COMPLETED_END)
        def recovery_mean(column):
            return pd.to_numeric(recent_recovery[column],errors='coerce').mean() \
                if column in recent_recovery else float('nan')
        a,b,c=st.columns(3)
        a.metric("Sleep · 7-day avg",fmt(recovery_mean("sleep_hours"),1)+" h")
        b.metric("Overnight HRV · 7-day avg",fmt(recovery_mean("hrv_ms"))+" ms")
        c.metric("Resting HR · 7-day avg",fmt(recovery_mean("resting_hr"))+" bpm")
        st.caption("Recovery readings are descriptive; compare longer-term trends in Recovery & Health.")

with pages[1]:
    st.subheader("Energy & Nutrition")
    if start>COMPLETED_END:
        st.info("No completed dates are selected.")
    else:
        m28=summary(daily,weight,garmin,COMPLETED_END,28)
        g28,n_garmin=recent_garmin(garmin,COMPLETED_END,28)
        m_intake,n_intake=recent_logged_intake(daily,COMPLETED_END,28)
        st.markdown("#### Maintenance and expenditure")
        a,b,c=st.columns(3)
        a.metric("Logged intake · 28-day avg",
                 fmt(m_intake)+" kcal" if pd.notna(m_intake) else "—")
        b.metric("Calculated TDEE · 28 days",
                 fmt(m28["estimated_tdee"])+" kcal" if m28["valid"] else "—")
        c.metric("Garmin expenditure · 28-day avg",
                 fmt(g28)+" kcal" if pd.notna(g28) else "—")
        st.caption(f"Data coverage: intake {n_intake}/28, Garmin {n_garmin}/28, "
                   f"weight {m28['weight_days']}/28. Calculated TDEE requires at least "
                   "80% of days with likely complete nutrition and adequate weight measurements.")
        if not m28["valid"]:
            st.info("A reliable weight-derived estimate isn't available for this 28-day window; "
                    "use the recorded calorie and weight trends while data accumulates.")
        else:
            st.write("Weight trend: **"+fmt(m28["trend_lb_week"],2)+" lb/week**. "
                     "The calculated TDEE uses a simple 3,500-kcal-per-pound approximation; "
                     "water and glycogen changes can make short windows misleading.")

        st.markdown("#### Explore one trend")
        focus=st.radio("Choose a measure",
                       ["Body weight","Logged calories","Garmin expenditure"],
                       horizontal=True,key="energy_focus")
        if focus=="Body weight":
            show_points=st.checkbox("Show individual weigh-ins",value=False,key="energy_points")
            st.plotly_chart(weight_chart(weight,start,COMPLETED_END,show_points),
                            use_container_width=True)
            st.caption("The seven-day average makes changes in body weight easier to see "
                       "without interpreting each day's fluctuation.")
        elif focus=="Logged calories":
            n7,c7=recent_logged_intake(daily,COMPLETED_END,7)
            n30,c30=recent_logged_intake(daily,COMPLETED_END,30)
            k1,k2,k3=st.columns(3)
            k1.metric("7-day average",fmt(n7)+" kcal")
            k2.metric("30-day average",fmt(n30)+" kcal")
            k3.metric("Current goal",f"{calorie_goal:,.0f} kcal")
            show_target=st.checkbox("Show goal range on daily bars",
                                    value=False,key="show_calorie_band")
            st.plotly_chart(calories_chart(daily,start,COMPLETED_END,
                calorie_goal,calorie_tolerance,show_target),use_container_width=True)
            st.caption(f"Logged days: {c7}/7 over the last week, {c30}/30 over the last month. "
                       "Averages are shown as numbers above rather than extra chart lines. "
                       "The goal is a current manual reference, not an imported historical goal.")
        else:
            st.plotly_chart(expenditure_chart(garmin,start,COMPLETED_END),
                            use_container_width=True)
            st.caption("Garmin seven-day estimated daily energy expenditure, "
                       "not independently measured TDEE.")

        with st.expander("Compare TDEE estimates across windows"):
            reports=[]
            for n in (14,21,28,42):
                m=summary(daily,weight,garmin,COMPLETED_END,n)
                reports.append({"Window":f"{n} days","Logged kcal/day":m["average_intake"],
                                "Weight trend (lb/week)":m["trend_lb_week"] if m["valid"] else None,
                                "Calculated TDEE":m["estimated_tdee"] if m["valid"] else None,
                                "Garmin kcal/day":m["garmin_average"],
                                "Intake days":m["intake_days"],"Weight days":m["weight_days"]})
            st.dataframe(pd.DataFrame(reports),hide_index=True,use_container_width=True)
            st.caption("A difference between estimates is uncertainty to investigate, "
                       "not proof that Garmin or food logging is inaccurate.")

        st.markdown("#### Nutrition quality")
        complete=period_frame(daily,start,COMPLETED_END)
        nutrients=(("protein_g","Protein","g"),("fat_g","Fat","g"),
                   ("fiber_g","Fiber","g"),("potassium_mg","Potassium","mg"))
        # Aggregate by the latest completed seven calendar days.
        week=period_frame(daily,COMPLETED_END-timedelta(days=6),COMPLETED_END)
        cells=st.columns(4)
        for card,(field,label,unit) in zip(cells,nutrients):
            v=pd.to_numeric(week[field],errors="coerce").mean() if field in week else float('nan')
            card.metric(label+" · 7-day avg",fmt(v,1 if unit=="g" else 0)+" "+unit)
        with st.expander("Detailed macronutrients, micronutrients and daily records"):
            if complete.empty:
                st.info("No nutrition records in the selected interval.")
            else:
                st.dataframe(complete.sort_index(ascending=False),use_container_width=True)
                st.download_button("Download nutrition CSV",complete.to_csv(),
                                   file_name="nutrition_by_day.csv",mime="text/csv")
        if not complete.empty:
            missing=complete.loc[complete["calories"].isna()]
            if len(missing):
                st.caption(f"{len(missing)} completed dates in the selected period lack nutrition "
                           "entries. These dates are not assumed to be zero intake.")
        with st.expander("Body-fat estimates"):
            comp=period_frame(body_fat,start,COMPLETED_END)
            if comp.empty:st.info("No body-fat records in this date range.")
            else:
                fig=px.line(comp,x=comp.index,y="body_fat_pct",title="Renpho body-fat estimate",
                            labels={"body_fat_pct":"Body fat (%)","x":"Date"})
                st.plotly_chart(fig,use_container_width=True)
                st.caption("Consumer impedance estimates vary with hydration; "
                           "interpret multiweek trends.")

with pages[2]:
    st.subheader("Training")
    if hevy_sets.empty:
        st.info("No Hevy workouts with recorded sets available.")
    else:
        relevant=hevy_sets[hevy_sets.local_date.between(
            pd.Timestamp(start),pd.Timestamp(COMPLETED_END))].copy()
        sessions=period_frame(hevy_workouts,start,COMPLETED_END)
        a,b,c=st.columns(3)
        a.metric("Workouts in period",str(len(sessions)))
        b.metric("Working sets in period",
                 str(int(relevant.working_set.sum())) if not relevant.empty else "0")
        c.metric("Exercises in period",
                 str(relevant.exercise.nunique()) if not relevant.empty else "0")
        st.markdown("#### Strength progression")
        names=sorted(relevant.exercise.dropna().unique()) if not relevant.empty else []
        if names:
            default_name=next((n for n in names if n=="Bench Press (Barbell)"),
                              names[0])
            exercise=st.selectbox("Exercise",names,index=names.index(default_name),
                                  key="training_exercise")
            series=per_exercise_metrics(relevant,exercise)
            measure=st.radio("Metric",["Estimated 1RM","Total loaded volume"],
                             horizontal=True,key="training_measure")
            if series.empty:
                st.info("No working sets for the selected exercise.")
            else:
                st.plotly_chart(exercise_chart(series,"e1rm" if measure=="Estimated 1RM" else "volume",
                                              exercise),use_container_width=True)
                st.caption("Estimated 1RM uses Epley on eligible 1–10 rep sets. "
                           "Loaded volume sums recorded weight × reps across working sets; "
                           "both metrics depend on consistent technique and exercise naming.")
                with st.expander("Session records"):
                    st.dataframe(series.sort_values("local_date",ascending=False),
                                 hide_index=True,use_container_width=True)
        else:
            st.info("No exercises in the selected period.")

        st.markdown("#### Muscle-group training balance")
        last28=muscle_counts(hevy_sets,COMPLETED_END,days=28)
        if last28.empty:
            st.info("No working sets logged in the last 28 days.")
        else:
            st.plotly_chart(muscle_chart(last28,"Working sets by primary group · last 28 days"),
                            use_container_width=True)
            st.caption("A set is assigned to one primary movement group. Secondary muscles "
                       "in compound lifts aren't counted separately, and sets aren't direct "
                       "measurements of muscle growth.")
        with st.expander("Weekly muscle-group history"):
            grouped=group_working_sets(relevant,start,COMPLETED_END)
            weeks=weekly_muscle_sets(grouped)
            if weeks.empty:
                st.info("No working-set history in this period.")
            else:
                name=st.selectbox("Muscle group",sorted(weeks["group"].unique()),
                                  key="weekly_muscle")
                choice=weeks[weeks["group"].eq(name)]
                fig=px.bar(choice,x="week",y="sets",title=f"{name} · weekly working sets",
                           labels={"week":"Week beginning","sets":"Working sets"})
                st.plotly_chart(fig,use_container_width=True)
                with st.expander("Full group-by-week table"):
                    matrix=weeks.pivot(index="week",columns="group",values="sets").fillna(0).astype(int)
                    st.dataframe(matrix,use_container_width=True)

        with st.expander("Break down an individual workout"):
            grouped=group_working_sets(relevant,start,COMPLETED_END)
            if sessions.empty or grouped.empty:
                st.info("No sessions available in this date range.")
            else:
                ids=list(sessions.workout_id)
                label_map={row.workout_id:f"{dt:%b %d, %Y} · {row.title}"
                           for dt,row in sessions.iterrows()}
                chosen=st.selectbox("Workout",ids,format_func=lambda x:label_map.get(x,x),
                                    key="workout_detail")
                breakdown=workout_breakdown(grouped,chosen)
                if not breakdown.empty:
                    st.plotly_chart(px.pie(breakdown,names="group",values="sets",hole=.35,
                        title="Working sets by primary group"),use_container_width=True)
                    each=grouped[grouped["workout_id"].eq(chosen)].groupby(
                        ["exercise","group"]).size().rename("Sets").reset_index()
                    st.dataframe(each,hide_index=True,use_container_width=True)
                else:
                    st.info("This workout has no eligible working sets.")

        with st.expander("Hevy session list"):
            if sessions.empty:
                st.info("No strength sessions in this date range.")
            else:
                st.dataframe(sessions[["title","duration_minutes"]].sort_index(ascending=False),
                             use_container_width=True)

with pages[3]:
    st.subheader("Recovery & Health")
    recent=period_frame(garmin,COMPLETED_END-timedelta(days=6),COMPLETED_END)
    def mean_measure(field):
        return pd.to_numeric(recent[field],errors="coerce").mean() \
            if field in recent else float("nan")
    a,b,c,d=st.columns(4)
    a.metric("Sleep · 7-day avg",fmt(mean_measure("sleep_hours"),1)+" h")
    b.metric("HRV · 7-day avg",fmt(mean_measure("hrv_ms"))+" ms")
    c.metric("Resting heart rate",fmt(mean_measure("resting_hr"))+" bpm")
    d.metric("Steps · daily avg",fmt(mean_measure("steps")))
    fields={
        "Sleep":"sleep_hours","Overnight HRV":"hrv_ms","Resting heart rate":"resting_hr",
        "Daily steps":"steps","Stress":"stress_score","Body Battery minimum":"body_battery_min"}
    focus=st.radio("Recovery trend",list(fields),horizontal=True,key="recovery_focus")
    selected=period_frame(garmin,start,COMPLETED_END)
    if selected.empty or fields[focus] not in selected or selected[fields[focus]].dropna().empty:
        st.info("No readings for this metric in the selected interval.")
    else:
        fig=px.line(selected,x=selected.index,y=fields[focus],title=focus,
                    labels={"x":"Date",fields[focus]:focus})
        fig.update_layout(showlegend=False,margin=dict(l=5,r=5,b=5,t=50))
        st.plotly_chart(fig,use_container_width=True)
    st.caption("Daily recovery readings are useful for personal baselines and patterns, "
               "not diagnosis or a definitive readiness score.")
    with st.expander("Blood pressure"):
        frame=period_frame(bp,start,COMPLETED_END)
        if frame.empty:st.info("No blood-pressure measurements in the period.")
        else:
            fig=px.line(frame,x=frame.index,y=["systolic","diastolic"],
                         title="Blood pressure",labels={"value":"mmHg","x":"Date"})
            st.plotly_chart(fig,use_container_width=True)
            st.dataframe(frame.sort_index(ascending=False),use_container_width=True)
            st.caption("Blood pressure requires context; daily averages may mask variation.")
    with st.expander("Garmin recorded activities"):
        acts=period_frame(activity,start,COMPLETED_END)
        if acts.empty:st.info("No Garmin activities in the period.")
        else:st.dataframe(acts.sort_index(ascending=False),use_container_width=True)
        st.caption("Garmin activities are shown separately from Hevy training; "
                   "their calories are not added to Garmin's daily expenditure.")

with pages[4]:
    st.subheader("Data & Sync")
    st.caption("Missing or stale source data is not treated as a zero measurement.")
    checks=[("MyFitnessPal nutrition","nutrition"),("Renpho weight","weights"),
            ("Renpho body fat","hc_body_fat"),("Blood pressure","hc_blood_pressure"),
            ("Garmin daily metrics","garmin_daily"),("Garmin activities","garmin_activities"),
            ("Hevy workouts","hevy_workouts")]
    records=[]
    for label,table in checks:
        n,mind,maxd=db.execute(
            f"SELECT COUNT(*),MIN(local_date),MAX(local_date) FROM {table}").fetchone()
        age=(TODAY-date.fromisoformat(maxd)).days if maxd else None
        records.append({"Source":label,"Records":n,"Earliest":mind,"Latest":maxd,
            "Age (days)":age,"Status":("No data" if not n else
                     "Potentially stale" if age is not None and age>2 else "Recent")})
    st.dataframe(pd.DataFrame(records),hide_index=True,use_container_width=True)
    state=db.execute("SELECT value FROM hevy_sync_state WHERE key='last_success_utc'").fetchone()
    st.caption("Latest successful Hevy synchronization: "+(state[0] if state else "Not recorded"))
    with st.expander("Recent import and synchronization logs"):
        log=sql("SELECT started_at,source,dataset,start_date,end_date,record_count,status,error_type "
                "FROM ingestion_log ORDER BY run_id DESC LIMIT 40")
        if not log.empty:st.dataframe(log,hide_index=True,use_container_width=True)
        else:st.info("No ingestion log records.")
    with st.expander("Garmin measurement availability"):
        metrics=[("Daily expenditure","calories_burned"),("Steps","steps"),
                 ("Resting HR","resting_hr"),("HRV","hrv_ms"),("Sleep","sleep_hours"),
                 ("Stress","stress_score"),("Body Battery","body_battery_min")]
        rows=[]
        for label,col in metrics:
            n,first,last=db.execute(f"SELECT COUNT({col}),"
                    f"MIN(CASE WHEN {col} IS NOT NULL THEN local_date END),"
                    f"MAX(CASE WHEN {col} IS NOT NULL THEN local_date END) FROM garmin_daily").fetchone()
            rows.append({"Metric":label,"Days":n,"First":first,"Last":last})
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
