"""Dashboard v0.9: coordinated energy explorer and 5/3/1 cycle planner.

No individual health data or hard-coded personal Training Maxes.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard_v07 import energy_overlay_frame, rolling_calorie_frame

LIFTS = {
    "Bench press": ("Bench Press (Barbell)", 5),
    "Overhead press": ("Overhead Press (Barbell)", 5),
    "Squat": ("Squat (Barbell)", 10),
    "Deadlift": ("Deadlift (Barbell)", 10),
}

# Percentages of Training Max; only the final set is AMRAP (+).
WEEKS = (
    ("Week 1 · 5+", ((.65,"5"), (.75,"5"), (.85,"5+"))),
    ("Week 2 · 3+", ((.70,"3"), (.80,"3"), (.90,"3+"))),
    ("Week 3 · 1+", ((.75,"5"), (.85,"3"), (.95,"1+"))),
)

ENERGY_SERIES = (
    "7-day logged calories",
    "7-day Garmin expenditure",
    "28-day weight-derived TDEE",
    "Daily logged calories",
    "7-day body weight",
)
DEFAULT_ENERGY_SERIES = (
    "7-day logged calories",
    "7-day Garmin expenditure",
    "7-day body weight",
)


def round_plate(value, increment=5.0):
    """Round half-up to the nearest loadable increment; do not use banker's rounding."""
    if increment <= 0 or value < 0:
        raise ValueError("Weight and plate increment must be nonnegative/positive")
    return float(math.floor(value / increment + 0.5 + 1e-10) * increment)


def prescription(training_max, increment=5.0):
    """One cycle with three working sets per week, excluding optional back-off work."""
    if training_max <= 0:
        raise ValueError("Training Max must be positive")
    output = []
    for week, sets in WEEKS:
        for index, (fraction, reps) in enumerate(sets, 1):
            output.append({
                "Week":week,"Set":index,"TM %":f"{round(fraction*100):d}%",
                "Reps":reps,"Weight (lb)":round_plate(training_max*fraction, increment),
            })
    return pd.DataFrame(output)


def detect_week3_training_max(sets, exercise, through=None, increment=5.0):
    """Recognize a 5/3/1+ 5/3/1 sequence in the *first* 3 working sets.

    This excludes warmups and optional later back-offs. It does not reverse
    engineer training maxes from a one-rep maximum or the heaviest set alone.
    Because plate rounding is non-injective, results remain suggested values
    that the user reviews before following prescriptions.
    """
    if sets is None or sets.empty:
        return None
    required = {"exercise","local_date","workout_id","set_index","set_type","weight_lb","reps"}
    if not required.issubset(set(sets.columns)):
        return None
    frame = sets[sets["exercise"].eq(exercise)].copy()
    frame["local_date"] = pd.to_datetime(frame["local_date"],errors="coerce")
    if through is not None:
        frame = frame[frame["local_date"].le(pd.Timestamp(through))]
    frame = frame[frame["set_type"].isin(("normal","failure"))]
    if frame.empty:
        return None
    frame["reps"]=pd.to_numeric(frame["reps"],errors="coerce")
    frame["weight_lb"]=pd.to_numeric(frame["weight_lb"],errors="coerce")
    frame=frame.sort_values(["local_date","workout_id","set_index"],
                            ascending=[False,True,True])
    candidates=[]
    for workout_id,workout in frame.groupby("workout_id",sort=False):
        workout=workout.sort_values("set_index")
        if len(workout)<3:
            continue
        first=workout.iloc[:3]
        weights=first["weight_lb"].to_numpy(dtype=float)
        reps=first["reps"].to_numpy(dtype=float)
        if not np.all(np.isfinite(weights)) or not np.all(np.isfinite(reps)):
            continue
        # The 5/3/1+ week starts exactly 5,3 and ends with 1 or more.
        if not (int(reps[0])==5 and int(reps[1])==3 and reps[2]>=1):
            continue
        if not (weights[0]<weights[1]<weights[2]):
            continue
        # Search discrete, loadable TM values; rounded percentages must fit
        # *all three* working sets, not just the heavy set.
        nominal=weights[2]/.95
        lower=max(increment,round_plate(nominal-20,increment))
        upper=round_plate(nominal+20,increment)
        for tm in np.arange(lower,upper+increment/2,increment):
            expected=np.array([round_plate(tm*p,increment) for p in (.75,.85,.95)])
            observed=np.array([round_plate(w,increment) for w in weights])
            errors=np.abs(expected-observed)
            if float(np.max(errors))>increment+1e-5:
                continue
            score=float(np.sum(errors))+abs(tm-nominal)*.01
            candidates.append((pd.Timestamp(first.iloc[0]["local_date"]),score,
                               tm,int(reps[2]),tuple(float(w) for w in weights)))
    if not candidates:
        return None
    latest=max(row[0] for row in candidates)
    best=min((r for r in candidates if r[0]==latest),key=lambda item:item[1])
    return {
        "tm":float(best[2]),"date":best[0].date(),"last_plus_reps":int(best[3]),
        "weights":best[4],"source":"Hevy 5/3/1+ set pattern",
    }


def summarize_next_cycle(sets, through=None, increment=5.0):
    """Discovered current and next Training Max for each lift, or unresolved."""
    rows=[]
    discoveries={}
    for label,(exercise,increase) in LIFTS.items():
        detected=detect_week3_training_max(sets,exercise,through,increment)
        discoveries[label]=detected
        rows.append({
            "Lift":label,
            "Last detected 1+":str(detected["date"]) if detected else "Not detected",
            "Current TM (lb)":detected["tm"] if detected else np.nan,
            "Increase (lb)":increase,
            "Next TM (lb)":detected["tm"]+increase if detected else np.nan,
            "1+ reps":detected["last_plus_reps"] if detected else np.nan,
        })
    return pd.DataFrame(rows),discoveries


def display_energy_frame(daily, weight, garmin, start, end):
    """Prepare linked measurements with all historical context for rolling means."""
    df=energy_overlay_frame(daily,weight,garmin,start,end)
    history=rolling_calorie_frame(daily,end)
    ix=df.index
    df["intake7"]=history["usable"].rolling(7,min_periods=5).mean().reindex(ix) \
        if not history.empty else np.nan
    # The existing frame already preserves historical context for Garmin 7-day,
    # body-weight 7-day and 28-day weight-derived energy estimates.
    return df


def interactive_energy_figure(frame, selected):
    """Energy in kcal/day and weight in lb: shared dates but distinct panels.

    Plotly legend items also support clicks to hide/show any selected trace.
    Missing values remain gaps. TDEE(28) is a smoothed *lagged* estimate.
    """
    chosen=[s for s in ENERGY_SERIES if s in set(selected)]
    if not chosen:
        return go.Figure()
    energy=any(label!="7-day body weight" for label in chosen)
    with_weight="7-day body weight" in chosen
    two=energy and with_weight
    fig=make_subplots(rows=2 if two else 1,cols=1,shared_xaxes=True,
        vertical_spacing=.10 if two else 0,
        row_heights=[.65,.35] if two else None,
        subplot_titles=("Energy · kcal/day","Body weight · lb") if two else None)
    def add(series,name,kind="line",row=1,visible=True):
        if kind=="bar":
            tr=go.Bar(x=frame.index,y=frame[series],name=name,opacity=.36,
                hovertemplate="%{x|%b %d}: %{y:,.0f} kcal<extra>"+name+"</extra>",
                visible=visible)
        else:
            unit=" lb" if name=="7-day body weight" else " kcal"
            tr=go.Scatter(x=frame.index,y=frame[series],mode="lines",
                name=name,line={"width":2.7,"dash":"dot" if "weight-derived" in name else "solid"},
                connectgaps=False,visible=visible,
                hovertemplate="%{x|%b %d}: %{y:,.1f}"+unit+"<extra>"+name+"</extra>")
        fig.add_trace(tr,row=row,col=1)

    mappings={
        "7-day logged calories":("intake7","line"),
        "7-day Garmin expenditure":("garmin7","line"),
        "28-day weight-derived TDEE":("weight_derived_tdee28","line"),
        "Daily logged calories":("calories","bar"),
    }
    for name in chosen:
        if name in mappings:
            col,kind=mappings[name]
            add(col,name,kind)
    if with_weight:
        add("weight7","7-day body weight",row=2 if two else 1)
    if two:
        fig.update_yaxes(title_text="kcal/day",row=1,col=1)
        fig.update_yaxes(title_text="lb",row=2,col=1)
    elif energy:
        fig.update_yaxes(title_text="kcal/day")
    else:
        fig.update_yaxes(title_text="lb")
    fig.update_layout(
        title="Energy balance · selectable comparisons",
        hovermode="x unified",height=560 if two else 360,
        barmode="overlay",legend=dict(orientation="h",y=-.13,x=0),
        margin=dict(l=10,r=10,b=55,t=85),
        uirevision="energy-v09",
    )
    fig.update_xaxes(title_text="Date",row=2 if two else 1,col=1)
    return fig
