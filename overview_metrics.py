"""Read-only decision summaries. Missing measurements never become zero.

Windows end on a completed selected date, independently of the chart start date.
Thresholds for training are transparent coaching heuristics, not diagnoses.
"""
import numpy as np
import pandas as pd
from dashboard_v08 import summary
from dashboard_v07 import per_exercise_metrics


def window(frame, end, days):
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    result.index = pd.to_datetime(result.index).normalize()
    return result.loc[result.index.to_series().between(
        pd.Timestamp(end)-pd.Timedelta(days=days-1), pd.Timestamp(end)).values]


def measured(frame, field):
    if field not in frame:
        return pd.Series(dtype=float)
    values = pd.to_numeric(frame[field], errors='coerce')
    return values.where(np.isfinite(values)).dropna()


def metric_summary(frame, field, end, days=7, positive=False):
    values = measured(window(frame, end, days), field)
    if positive:
        values = values[values.gt(0)]
    # Daily metrics count dates, not duplicate source rows.
    values = values.groupby(level=0).mean().sort_index()
    return {'values': values, 'days': len(values),
            'mean': float(values.mean()) if len(values) else np.nan,
            'latest': values.index.max().date() if len(values) else None}


def bp_summary(bp, end):
    frame = window(bp, end, 7)
    if not {'systolic', 'diastolic'}.issubset(frame):
        valid = pd.DataFrame()
    else:
        valid = frame[['systolic','diastolic']].apply(pd.to_numeric, errors='coerce')
        valid = valid.replace([np.inf,-np.inf], np.nan).dropna()
        valid = valid[valid.systolic.gt(0) & valid.diastolic.gt(0)].groupby(level=0).mean()
    result = {'days':len(valid), 'systolic':np.nan, 'diastolic':np.nan,
              'category':'Insufficient recent readings', 'action':
              'Collect standardized readings on several days; use a validated upper-arm cuff.'}
    if valid.empty:
        return result
    s,d = valid.mean()[['systolic','diastolic']]
    category = ('Stage 2 range' if s>=140 or d>=90 else 'Stage 1 range'
                if s>=130 or d>=80 else 'Elevated range' if s>=120 else 'Normal range')
    result.update(systolic=s, diastolic=d)
    if len(valid)>=3:
        result['category']=category
        result['action']=('Discuss a persistently elevated home average with your PCP.'
                          if s>=130 or d>=80 else
                          'Continue consistent measurement; review activity and dietary habits.'
                          if s>=120 else 'Continue your current habits and periodic monitoring.')
    # Acute safety uses the latest recorded daily average, never the 7-day mean.
    # Individual readings may be higher; this is not emergency monitoring.
    if valid.iloc[-1].systolic>180 or valid.iloc[-1].diastolic>120:
        result['action']=('Latest recorded daily average is over 180 systolic or 120 diastolic. '
            'Recheck after one minute. If still this high, contact a clinician immediately; '
            'with chest pain, shortness of breath, weakness or vision changes, call 911.')
    return result


def sleep_summary(garmin, end, minimum=6):
    result = metric_summary(garmin,'sleep_hours',end,positive=True)
    values=result['values']
    result.update(below=int(values.lt(minimum).sum()),
                  recommended=int(values.ge(7).sum()))
    result['action']=('No recent sleep measurements; check Garmin sleep synchronization.' if values.empty
        else f'{result["below"]} of {len(values)} recorded nights below your {minimum:g}-hour minimum. '
             'Make more time for sleep where possible.' if values.lt(minimum).any()
        else 'Personal minimum met on recorded nights. Aim toward 7+ hours when possible.'
             if values.lt(7).any() else
             'Duration recommendation met on recorded nights; also consider daytime fatigue.')
    return result


def cardio_summary(garmin, workouts, end):
    intensity=metric_summary(garmin,'intensity_minutes',end)
    intensity['values']=intensity['values'][intensity['values'].ge(0)]
    intensity['days']=len(intensity['values'])
    total=float(intensity['values'].sum()) if intensity['days'] else np.nan
    sessions=window(workouts,end,7)
    days=int(sessions.index.nunique()) if not sessions.empty else 0
    return {'minutes':total,'coverage':intensity['days'],'strength_days':days,
            'remaining':max(0,150-total) if pd.notna(total) else np.nan,
            'steps':metric_summary(garmin,'steps',end),
            'rhr':metric_summary(garmin,'resting_hr',end,positive=True),
            'prior_steps':metric_summary(garmin,'steps',pd.Timestamp(end)-pd.Timedelta(days=7)),
            'prior_rhr':metric_summary(garmin,'resting_hr',pd.Timestamp(end)-pd.Timedelta(days=7),positive=True)}


def nutrition_summary(daily, end, calorie_goal, protein_goal=150):
    week=window(daily,end,7)
    # Same completeness proxy used by the existing TDEE helpers. Not proof of full logging.
    calories=week.get('calories',pd.Series(index=week.index,dtype=float))
    meals=week.get('meals',pd.Series(index=week.index,dtype=float))
    complete=pd.to_numeric(calories,errors='coerce').gt(0) & pd.to_numeric(meals,errors='coerce').ge(3)
    usable=week.loc[complete]
    rows=[]
    for field,label,target,direction,unit in [
        ('protein_g','Protein',protein_goal,'at least','g'),
        ('fiber_g','Fiber',14*calorie_goal/1000,'at least','g'),
        ('sodium_mg','Sodium',2300,'at most','mg')]:
        values=measured(usable,field)
        values=values[values.ge(0)]
        met=values.ge(target) if direction=='at least' else values.le(target)
        rows.append({'Nutrient':label,'Average':float(values.mean()) if len(values) else np.nan,
            'Unit':unit,'Reference':f'{direction} {target:,.1f} {unit}',
            'Days with values':len(values),'Days meeting reference':int(met.sum())})
    return pd.DataFrame(rows),int(complete.sum())


def training_summary(daily, weight, garmin, sets, end):
    energy=summary(daily,weight,garmin,end,28)
    prior=summary(daily,weight,garmin,pd.Timestamp(end)-pd.Timedelta(days=28),28)
    rows=[]
    if sets is not None and not sets.empty:
        data=sets.copy()
        data['local_date']=pd.to_datetime(data.local_date)
        for exercise in ('Bench Press (Barbell)','Deadlift (Barbell)',
                         'Overhead Press (Barbell)','Squat (Barbell)'):
            sessions=per_exercise_metrics(data,exercise)
            if sessions.empty:
                continue
            dates=pd.to_datetime(sessions.local_date)
            recent=sessions.loc[dates.between(pd.Timestamp(end)-pd.Timedelta(days=27),pd.Timestamp(end))]
            previous=sessions.loc[dates.between(pd.Timestamp(end)-pd.Timedelta(days=55),pd.Timestamp(end)-pd.Timedelta(days=28))]
            r=pd.to_numeric(recent.estimated_1rm_lb,errors='coerce').dropna()
            p=pd.to_numeric(previous.estimated_1rm_lb,errors='coerce').dropna()
            change=(r.median()/p.median()-1)*100 if len(r)>=2 and len(p)>=2 and p.median()>0 else np.nan
            rows.append({'Lift':exercise.replace(' (Barbell)',''),
                         'Recent sessions':len(r),'Prior sessions':len(p),
                         'Median e1RM change (%)':change})
    table=pd.DataFrame(rows)
    changes=table['Median e1RM change (%)'].dropna() if not table.empty else pd.Series(dtype=float)
    # Don't automate a calorie decision until BOTH windows have adequate intake/weight,
    # and at least two lifts have repeat sessions in both windows.
    if not energy['valid'] or not prior['valid'] or len(changes)<2:
        action='More consistent intake, weight and repeated lift records are needed before suggesting a change.'
    elif energy['trend_lb_week'] < -0.1:
        action='Weight is trending down. For a muscle-gain goal, review intake consistency and recovery before considering a small increase.'
    elif changes.median()>2:
        action='Performance is improving across comparable lifts. Continue intake if weight is moving at your intended pace.'
    elif energy['trend_lb_week']>0.5:
        action='Weight is rising while performance is not clearly improving. Review surplus size, technique, programming and recovery before changing intake.'
    else:
        action='Progress is unclear. Review training consistency, effort and sleep before adding calories.'
    return energy,table,action
