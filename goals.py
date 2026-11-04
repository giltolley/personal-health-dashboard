"""Append-only, dated goal snapshots. Personal history belongs in the database."""
from datetime import date, datetime, timezone
import math
import uuid
import pandas as pd
from datastore import read_frame

PHASES=['Unspecified','Fat loss','Maintenance','Muscle gain']
SCHEMA='''CREATE TABLE IF NOT EXISTS goal_history (
 event_id TEXT PRIMARY KEY,
 effective_date TEXT,
 known_before_date TEXT,
 phase TEXT NOT NULL,
 calories REAL NOT NULL CHECK (calories BETWEEN 500 AND 10000),
 protein_g REAL CHECK (protein_g BETWEEN 0 AND 500),
 recorded_at TEXT NOT NULL,
 CHECK ((effective_date IS NOT NULL AND known_before_date IS NULL)
     OR (effective_date IS NULL AND known_before_date IS NOT NULL))
);'''


def ensure_goals(db):
    # Hosted tables are provisioned separately with RLS; do not create exposed tables in UI.
    if getattr(db,'backend',None)!='postgresql':
        db.executescript(SCHEMA)
        db.commit()


def read_goals(db):
    return read_frame(db,'SELECT * FROM goal_history ORDER BY recorded_at,event_id')


def save_goal(db,effective_date,phase,calories,protein_g=None,known_before_date=None):
    if phase not in PHASES:
        raise ValueError('Choose a supported phase.')
    if (effective_date is None)==(known_before_date is None):
        raise ValueError('Provide either an effective date or a known-before date.')
    for value in (effective_date,known_before_date):
        if value is not None:
            date.fromisoformat(str(value))
    if not math.isfinite(float(calories)) or not 500<=float(calories)<=10000:
        raise ValueError('Calorie target must be between 500 and 10,000.')
    if protein_g is not None and (not math.isfinite(float(protein_g)) or not 0<=float(protein_g)<=500):
        raise ValueError('Protein reference must be between 0 and 500.')
    event=str(uuid.uuid4())
    db.execute('INSERT INTO goal_history VALUES (?,?,?,?,?,?,?)',
        (event,str(effective_date) if effective_date else None,
         str(known_before_date) if known_before_date else None,phase,float(calories),
         float(protein_g) if protein_g is not None else None,datetime.now(timezone.utc).isoformat()))
    db.commit()
    return event


def resolved_history(history):
    if history is None or history.empty:
        return pd.DataFrame()
    dated=history[history.effective_date.notna()].copy()
    return dated.sort_values(['recorded_at','event_id']).drop_duplicates('effective_date',keep='last').sort_values('effective_date')


def targets_for_dates(history,dates):
    dates=pd.DatetimeIndex(pd.to_datetime(dates)).normalize()
    result=pd.DataFrame(index=dates,columns=['calories','protein_g','phase','effective_date'])
    for _,row in resolved_history(history).iterrows():
        mask=dates>=pd.Timestamp(row.effective_date)
        result.loc[mask,['calories','protein_g','phase','effective_date']]=[
            row.calories,row.protein_g,row.phase,row.effective_date]
    for field in ['calories','protein_g']:
        result[field]=pd.to_numeric(result[field],errors='coerce')
    return result


def goal_at(history,day):
    return targets_for_dates(history,[day]).iloc[0]


def window_context(history,end,days=28):
    dates=pd.date_range(end=pd.Timestamp(end),periods=days)
    targets=targets_for_dates(history,dates)
    changes=targets[['calories','protein_g','phase']].fillna('Unknown').drop_duplicates()
    current=goal_at(history,end)
    known_date=current.effective_date
    return {'mixed':len(changes)>1,'unknown_days':int(targets.calories.isna().sum()),
            'days_on_target':int((targets.effective_date==known_date).sum()) if pd.notna(known_date) else 0,
            'target':current}
