"""Focused presentation helpers for dashboard v0.8.

One measure per chart; no mixed-units axes. Does not persist measurements,
personal goals, or credentials.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from insights_v06 import energy_window, estimate_tdee
from dashboard_v07 import rolling_calorie_frame, per_exercise_metrics, group_working_sets


def fmt(value, decimals=0):
    return f"{value:,.{decimals}f}" if pd.notna(value) else "—"


def daily_weight(weight, through=None):
    if isinstance(weight, pd.Series):
        s = weight
    elif isinstance(weight, pd.DataFrame) and "weight_lb" in weight:
        s = weight["weight_lb"]
    else:
        return pd.Series(dtype=float)
    s = pd.to_numeric(s, errors="coerce")
    s.index = pd.to_datetime(s.index).normalize()
    s = s.groupby(level=0).median().sort_index()
    if through is not None:
        s = s.loc[:pd.Timestamp(through)]
    return s.asfreq("D") if not s.empty else s


def weight_smoothed(weight, through=None):
    return daily_weight(weight, through).rolling(7, min_periods=5).mean()


def weight_chart(weight, start, end, show_daily=False):
    rolling = weight_smoothed(weight, end).loc[str(start):str(end)]
    fig = go.Figure()
    if show_daily:
        raw = daily_weight(weight, end).loc[str(start):str(end)]
        fig.add_trace(go.Scatter(x=raw.index, y=raw, mode="markers",
                                 name="Daily measurements", opacity=0.3,
                                 marker=dict(size=5)))
    fig.add_trace(go.Scatter(x=rolling.index, y=rolling, mode="lines",
                             name="7-day average", line=dict(width=3),
                             connectgaps=False))
    fig.update_layout(title="Body weight · 7-day average", xaxis_title="Date",
                      yaxis_title="Weight (lb)", hovermode="x unified",
                      margin=dict(l=5,r=5,b=5,t=50))
    return fig


def calories_chart(daily, start, end, goal=None, tolerance=100, show_band=False):
    history = rolling_calorie_frame(daily, end)
    subset = history.loc[str(start):str(end)] if not history.empty else history
    fig = go.Figure()
    if show_band and goal is not None:
        fig.add_hrect(y0=goal-tolerance, y1=goal+tolerance, line_width=0,
                      fillcolor="rgba(80,150,110,.13)",
                      annotation_text="Goal range",annotation_position="top left")
    fig.add_trace(go.Bar(x=subset.index, y=subset["calories"], name="Logged calories",
                         hovertemplate="%{x|%b %d}: %{y:,.0f} kcal<extra></extra>"))
    fig.update_layout(title="Logged calories · daily", xaxis_title="Date",
                      yaxis_title="Intake (kcal)", showlegend=False,
                      margin=dict(l=5,r=5,b=5,t=50))
    return fig


def expenditure_chart(garmin, start, end):
    if garmin is not None and not garmin.empty and "calories_burned" in garmin:
        s = pd.to_numeric(garmin["calories_burned"],errors="coerce").sort_index()
        s.index = pd.to_datetime(s.index)
        s = s.asfreq("D").rolling(7,min_periods=5).mean().loc[str(start):str(end)]
    else:
        s = pd.Series(dtype=float)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s.index,y=s,mode="lines",line=dict(width=3),
                             name="Garmin 7-day estimated expenditure",
                             connectgaps=False))
    fig.update_layout(title="Garmin expenditure · 7-day average",xaxis_title="Date",
                      yaxis_title="Estimated kcal/day",showlegend=False,
                      margin=dict(l=5,r=5,b=5,t=50))
    return fig


def summary(daily, weight, garmin, end, days=28):
    period = energy_window(daily, weight, garmin, end, days)
    return estimate_tdee(period)


def recent_logged_intake(daily, end, days):
    frame = rolling_calorie_frame(daily, end)
    if frame.empty:
        return float("nan"), 0
    recent = frame["usable"].reindex(pd.date_range(end=pd.Timestamp(end), periods=days))
    return (float(recent.mean()) if recent.notna().any() else float("nan"),
            int(recent.notna().sum()))


def recent_garmin(garmin, end, days=28):
    if garmin is None or garmin.empty or "calories_burned" not in garmin:
        return float("nan"), 0
    s = pd.to_numeric(garmin["calories_burned"],errors="coerce")
    s.index = pd.to_datetime(s.index).normalize()
    s = s.reindex(pd.date_range(end=pd.Timestamp(end),periods=days))
    return (float(s.mean()) if s.notna().any() else float("nan"),int(s.notna().sum()))


def recent_lift(sets, exercise, end):
    if sets is None or sets.empty:
        return None
    frame=sets[pd.to_datetime(sets["local_date"]).le(pd.Timestamp(end))]
    sessions=per_exercise_metrics(frame,exercise)
    if sessions.empty:
        return None
    eligible=sessions.dropna(subset=["estimated_1rm_lb"])
    if eligible.empty:
        return None
    latest=eligible.iloc[-1]
    prior=eligible.iloc[-2] if len(eligible)>1 else None
    return {
        "value":float(latest["estimated_1rm_lb"]),
        "change":float(latest["estimated_1rm_lb"]-prior["estimated_1rm_lb"]) if prior is not None else None,
        "date":pd.Timestamp(latest["local_date"]).date(),
        "sessions":len(eligible),
    }


def muscle_counts(sets, end, days=7):
    start=pd.Timestamp(end)-pd.Timedelta(days=days-1)
    data=group_working_sets(sets,start,end)
    if data is None or data.empty:
        return pd.DataFrame(columns=["group","sets"])
    return data.groupby("group").size().rename("sets").reset_index().sort_values("sets",ascending=True)


def muscle_chart(counts, title):
    fig=px.bar(counts,x="sets",y="group",orientation="h",
               title=title,labels={"sets":"Working sets","group":"Primary muscle group"})
    fig.update_layout(showlegend=False,margin=dict(l=5,r=5,b=5,t=50))
    return fig


def exercise_chart(sessions, measure, exercise):
    col={"e1rm":"estimated_1rm_lb","volume":"volume_lb"}[measure]
    title=("Estimated 1RM" if measure=="e1rm" else "Loaded volume")+" · "+exercise
    fig=px.line(sessions,x="local_date",y=col,markers=True,
                title=title,labels={"local_date":"Workout date",
                 col:"Estimated 1RM (lb)" if measure=="e1rm" else "Weight × reps (lb)"})
    fig.update_layout(margin=dict(l=5,r=5,b=5,t=50))
    return fig
