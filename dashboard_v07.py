"""Display-friendly trend and training calculations for dashboard v0.7.

The repository contains no patient records or secrets. Goals are supplied in
the Streamlit UI; neither Garmin nor Health Connect supplies calorie goals here.
"""
from __future__ import annotations

from datetime import date, timedelta
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px


def default_date_range(today: date, oldest: date, days: int = 90):
    """End at yesterday to avoid treating an in-progress day as missing."""
    end = max(oldest, today - timedelta(days=1))
    return max(oldest, end - timedelta(days=days - 1)), end


def rolling_calorie_frame(daily: pd.DataFrame, end_date: date, min_meals: int = 3):
    """Use full history for moving averages, not just the visible chart slice.

    Averages require at least 5/7 and 21/30 likely complete days respectively.
    Source-derived meal counts are imperfect completeness proxies.
    """
    if daily is None or daily.empty or 'calories' not in daily:
        return pd.DataFrame(columns=['calories', 'usable', 'avg7', 'avg30'])
    data = daily.copy()
    data.index = pd.to_datetime(data.index).normalize()
    data = data[~data.index.duplicated(keep='last')].sort_index()
    data = data.loc[:pd.Timestamp(end_date)].asfreq('D')
    calories = pd.to_numeric(data['calories'], errors='coerce').where(lambda x: x.gt(0))
    meals = pd.to_numeric(data.get('meals', pd.Series(index=data.index, dtype=float)), errors='coerce')
    source = data.get('source', pd.Series(index=data.index, dtype='object'))
    # Manual backfills are daily aggregates without a per-meal count.
    complete = meals.ge(min_meals) | source.eq('CSV backfill')
    usable = calories.where(complete)
    return pd.DataFrame({
        'calories': calories,
        'usable': usable,
        'avg7': usable.rolling(7, min_periods=5).mean(),
        'avg30': usable.rolling(30, min_periods=21).mean(),
    })


def calorie_chart(data: pd.DataFrame, target: float, tolerance: float):
    fig = go.Figure()
    fig.add_hrect(y0=target - tolerance, y1=target + tolerance,
                  fillcolor='rgba(80,155,110,0.10)', line_width=0,
                  annotation_text='Target range', annotation_position='top left')
    fig.add_trace(go.Bar(x=data.index, y=data['calories'], name='Daily logged intake',
                         opacity=0.45, hovertemplate='%{x|%b %d}: %{y:,.0f} kcal<extra></extra>'))
    for column, name, dash in [('avg7','7-day average','solid'),('avg30','30-day average','dash')]:
        fig.add_trace(go.Scatter(x=data.index, y=data[column], name=name, mode='lines',
                                 line=dict(width=2.5, dash=dash), connectgaps=False,
                                 hovertemplate='%{x|%b %d}: %{y:,.0f} kcal<extra></extra>'))
    fig.add_hline(y=target, line_dash='dot', annotation_text=f'Goal {target:,.0f} kcal',
                  annotation_position='bottom right')
    fig.update_layout(title='Daily logged calories and longer-term averages',
                      xaxis_title='Date', yaxis_title='Calories (kcal/day)',
                      barmode='overlay', hovermode='x unified', legend=dict(orientation='h'),
                      margin=dict(l=5, r=5, b=5, t=50))
    return fig


def _daily_series(df, col, method='mean'):
    if df is None or df.empty or col not in df:
        return pd.Series(dtype=float)
    s = pd.to_numeric(df[col], errors='coerce')
    s.index = pd.to_datetime(s.index).normalize()
    if method == 'median':
        return s.groupby(level=0).median().sort_index()
    return s.groupby(level=0).mean().sort_index()


def _regression_tdee(weight_lb, calories, min_coverage=0.8):
    """28-day trend estimate; require date coverage, never fill absent values."""
    complete = calories.dropna()
    weights = weight_lb.dropna()
    n = len(calories)
    if n < 14 or len(complete) < max(10, int(np.ceil(min_coverage*n))) or len(weights) < max(10, int(np.ceil(min_coverage*n))):
        return float('nan')
    x = (weights.index - weights.index[0]).days.to_numpy(dtype=float)
    if len(x) < 2 or not np.ptp(x):
        return float('nan')
    slope = np.polyfit(x, weights.to_numpy(dtype=float), 1)[0]
    return float(complete.mean() - slope*3500)


def energy_overlay_frame(daily, weight, garmin, start_date, end_date):
    """Complete dates only, preserving earlier context for rolling estimates."""
    ix = pd.date_range(start_date, end_date, freq='D')
    all_nutrition = rolling_calorie_frame(daily, end_date)
    w = _daily_series(weight.to_frame('weight_lb') if isinstance(weight,pd.Series) else weight,
                      'weight_lb', method='median')
    g = _daily_series(garmin, 'calories_burned')
    weight7 = w.reindex(pd.date_range(min(ix.min(),w.index.min()) if len(w) else ix.min(),ix.max(),freq='D')).rolling(7,min_periods=5).mean()
    calendar = pd.date_range(min(ix.min(),all_nutrition.index.min()) if len(all_nutrition) else ix.min(),ix.max(),freq='D')
    allc = all_nutrition['usable'].reindex(calendar) if not all_nutrition.empty else pd.Series(index=calendar,dtype=float)
    allw = w.reindex(calendar)
    # At each date estimate TDEE from the latest 28 *calendar days*, avoiding
    # inflated estimates that treat missing nutrition as zero intake.
    rolling_tdee = pd.Series(np.nan,index=ix,dtype=float)
    for day in ix:
        lookback = pd.date_range(end=day,periods=28,freq='D')
        rolling_tdee.loc[day] = _regression_tdee(allw.reindex(lookback), allc.reindex(lookback))
    return pd.DataFrame({
        'calories': all_nutrition['calories'].reindex(ix) if not all_nutrition.empty else pd.Series(index=ix,dtype=float),
        'usable': allc.reindex(ix),
        'garmin': g.reindex(ix),
        'garmin7': g.reindex(calendar).rolling(7,min_periods=5).mean().reindex(ix),
        'weight': w.reindex(ix),
        'weight7': weight7.reindex(ix),
        'weight_derived_tdee28': rolling_tdee,
    },index=ix)


def energy_overlay_chart(frame, target):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=frame.index,y=frame['calories'],name='Logged calories',
                         opacity=0.36, yaxis='y'))
    fig.add_trace(go.Scatter(x=frame.index,y=frame['garmin7'],mode='lines',
                             name='Garmin 7-day kcal',line=dict(width=2),yaxis='y'))
    fig.add_trace(go.Scatter(x=frame.index,y=frame['weight_derived_tdee28'],mode='lines',
                             name='Weight-derived TDEE (28-day)',line=dict(width=2,dash='dot'),yaxis='y'))
    fig.add_trace(go.Scatter(x=frame.index,y=frame['weight7'],mode='lines',
                             name='Weight 7-day avg',line=dict(width=3),yaxis='y2'))
    fig.add_hline(y=target,line_dash='dash',annotation_text=f'Intake goal {target:,.0f}')
    fig.update_layout(
        title='Daily intake, expenditure estimates and weight trend',
        xaxis=dict(title='Date'), yaxis=dict(title='kcal/day'),
        yaxis2=dict(title='Body weight (lb)',overlaying='y',side='right',showgrid=False),
        hovermode='x unified', legend=dict(orientation='h'),
        margin=dict(l=10,r=10,b=10,t=45))
    return fig


def cumulative_balance_chart(frame):
    """Only graph if all dates are complete; don't infer changes across gaps."""
    recent = frame.tail(28).copy()
    if recent.empty or recent[['usable','garmin']].isna().any().any() or recent['weight7'].notna().sum() < 7:
        return None
    cumulative_lb = (recent['usable']-recent['garmin']).cumsum()/3500
    trend = recent['weight7']
    baseline = trend.dropna().iloc[0]
    # The calculated surplus starts at the end of the first day; align the
    # first day to zero for comparison to weight change.
    cumulative_lb = cumulative_lb - cumulative_lb.iloc[0]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=recent.index,y=cumulative_lb,name='Cumulative intake − Garmin (lb equivalent)',mode='lines'))
    fig.add_trace(go.Scatter(x=recent.index,y=trend-baseline,name='7-day scale weight change (lb)',mode='lines'))
    fig.add_hline(y=0,line_dash='dot')
    fig.update_layout(title='Cumulative energy estimate versus smoothed weight change (last 28 days)',
                      xaxis_title='Date',yaxis_title='Change in pounds',hovermode='x unified',
                      legend=dict(orientation='h'),margin=dict(l=10,r=10,b=10,t=50))
    return fig


# Primary-target only. A compound exercise also trains other muscles, which is
# intentionally not double-counted in these simple per-session/weekly charts.
_GROUP_PATTERNS = [
    ('Core',r'crunch|ab wheel|\bplank\b|knee raise|leg raise|russian twist|cable twist|hanging'),
    ('Shoulders',r'overhead press|shoulder press|lateral raise|face pull|rear delt|reverse fly|front raise'),
    ('Legs',r'squat|leg press|leg curl|leg extension|lunge|calf|split squat'),
    ('Triceps',r'triceps|tricep|pushdown|skullcrush'),
    ('Biceps',r'bicep|\bcurl\b|hammer curl|ez bar'),
    ('Back / hinge',r'deadlift|\brow\b|pulldown|pull.?up|chin.?up|back extension|hyperextension|pullover'),
    ('Chest',r'bench|chest fly|cable fly|fly crossover|push.?up'),
]


def classify_exercise(name):
    if not isinstance(name,str):
        return 'Unmapped'
    label = name.casefold()
    for group,pattern in _GROUP_PATTERNS:
        if re.search(pattern,label):
            return group
    return 'Unmapped'


def group_working_sets(sets, start_date, end_date):
    if sets is None or sets.empty or 'working_set' not in sets:
        return pd.DataFrame()
    frame = sets.copy()
    frame['local_date'] = pd.to_datetime(frame['local_date'],errors='coerce').dt.normalize()
    frame = frame[frame['local_date'].between(pd.Timestamp(start_date), pd.Timestamp(end_date))]
    frame = frame[frame['working_set'].fillna(False)].copy()
    if frame.empty:
        return frame
    frame['group'] = frame['exercise'].apply(classify_exercise)
    frame['week'] = frame['local_date'].dt.to_period('W-SUN').dt.start_time
    return frame


def weekly_muscle_sets(grouped_sets):
    if grouped_sets is None or grouped_sets.empty:
        return pd.DataFrame(columns=['week','group','sets'])
    return grouped_sets.groupby(['week','group'],as_index=False).size().rename(columns={'size':'sets'})


def per_exercise_metrics(sets, exercise):
    """Session volume includes all weighted working sets; Epley eligible only."""
    if sets is None or sets.empty:
        return pd.DataFrame()
    selected = sets[(sets['exercise']==exercise) & sets['working_set'].fillna(False)].copy()
    if selected.empty:
        return pd.DataFrame()
    selected['local_date'] = pd.to_datetime(selected['local_date'],errors='coerce')
    selected['weight_lb'] = pd.to_numeric(selected['weight_lb'],errors='coerce')
    selected['reps'] = pd.to_numeric(selected['reps'],errors='coerce')
    selected['estimated_1rm_lb'] = pd.to_numeric(selected['estimated_1rm_lb'],errors='coerce')
    selected['weighted_volume'] = (selected['weight_lb']*selected['reps']).where(
        selected['weight_lb'].gt(0) & selected['reps'].gt(0))
    result = selected.groupby(['workout_id','local_date'],as_index=False).agg(
        estimated_1rm_lb=('estimated_1rm_lb','max'),
        volume_lb=('weighted_volume',lambda x:x.sum(min_count=1)),
        working_sets=('exercise','size'),
        top_weight_lb=('weight_lb','max'),
    )
    return result.sort_values('local_date')


def workout_breakdown(grouped_sets, workout_id):
    if grouped_sets is None or grouped_sets.empty:
        return pd.DataFrame(columns=['group','sets'])
    session = grouped_sets[grouped_sets['workout_id']==workout_id]
    return session.groupby('group',as_index=False).size().rename(columns={'size':'sets'})
