"""Read-only Hevy API connector: complete backfill + incremental update/delete events.

API credentials are read from HEVY_API_KEY or a local key file and never persisted.
All workouts, exercises, and sets are stored locally in the dashboard SQLite database.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API_ROOT = 'https://api.hevyapp.com'
LOCAL_TIMEZONE = ZoneInfo('America/New_York')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS hevy_workouts (
 workout_id TEXT PRIMARY KEY, local_date TEXT NOT NULL,
 title TEXT NOT NULL, start_time TEXT, end_time TEXT,
 updated_at TEXT, duration_minutes REAL, raw_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_hevy_workouts_date ON hevy_workouts(local_date);
CREATE TABLE IF NOT EXISTS hevy_exercises (
 workout_id TEXT NOT NULL, exercise_index INTEGER NOT NULL,
 template_id TEXT, title TEXT NOT NULL, superset_id INTEGER,
 PRIMARY KEY(workout_id, exercise_index));
CREATE INDEX IF NOT EXISTS idx_hevy_exercise_template ON hevy_exercises(template_id);
CREATE TABLE IF NOT EXISTS hevy_sets (
 workout_id TEXT NOT NULL, exercise_index INTEGER NOT NULL,
 set_index INTEGER NOT NULL, set_type TEXT,
 weight_kg REAL, reps INTEGER, rpe REAL, distance_meters REAL,
 duration_seconds REAL, custom_metric REAL,
 PRIMARY KEY(workout_id,exercise_index,set_index));
CREATE TABLE IF NOT EXISTS hevy_sync_state (
 key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def ensure_hevy_schema(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)


def resolve_hevy_key() -> str:
    """Only local environment or user's home directory; never the dashboard directory."""
    env = os.environ.get('HEVY_API_KEY', '').strip()
    if env:
        return env
    key_path = Path.home() / '.config' / 'hevy' / 'api-key'
    if not key_path.is_file():
        raise FileNotFoundError(f'Hevy key not found. Create {key_path} or set HEVY_API_KEY.')
    key = key_path.read_text(encoding='utf-8-sig').strip()
    if not key:
        raise ValueError('Hevy key file is empty')
    return key


def _date_local(s: str) -> str:
    # Hevy timestamps contain a timezone, and the calendar date must reflect the user's zone.
    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Workout timestamp lacks timezone')
    return dt.astimezone(LOCAL_TIMEZONE).date().isoformat()


def _duration(start: str, end: str | None):
    if not end:
        return None
    try:
        a = datetime.fromisoformat(start.replace('Z', '+00:00'))
        b = datetime.fromisoformat(end.replace('Z', '+00:00'))
        return max(0, (b - a).total_seconds() / 60)
    except (ValueError, TypeError):
        return None


def upsert_workout(db: sqlite3.Connection, workout: dict) -> str:
    """Insert/update a complete workout and its children; return new/updated/unchanged."""
    workout_id = workout.get('id')
    started = workout.get('start_time')
    exercises = workout.get('exercises')
    if not isinstance(workout_id, str) or not workout_id or not isinstance(started, str) or not isinstance(exercises, list):
        raise ValueError('Malformed Hevy workout response')
    raw = json.dumps(workout, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    existing = db.execute('SELECT raw_json FROM hevy_workouts WHERE workout_id=?', (workout_id,)).fetchone()
    if existing and existing[0] == raw:
        return 'unchanged'
    db.execute('''INSERT INTO hevy_workouts(workout_id,local_date,title,start_time,end_time,updated_at,duration_minutes,raw_json)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(workout_id) DO UPDATE SET local_date=excluded.local_date,
          title=excluded.title,start_time=excluded.start_time,end_time=excluded.end_time,
          updated_at=excluded.updated_at,duration_minutes=excluded.duration_minutes,raw_json=excluded.raw_json''',
        (workout_id, _date_local(started), workout.get('title') or '(Untitled)',
         started, workout.get('end_time'), workout.get('updated_at'),
         _duration(started, workout.get('end_time')), raw))
    db.execute('DELETE FROM hevy_sets WHERE workout_id=?', (workout_id,))
    db.execute('DELETE FROM hevy_exercises WHERE workout_id=?', (workout_id,))
    for i, ex in enumerate(exercises):
        if not isinstance(ex, dict):
            continue
        idx = i  # array order determines stable identity; do not depend on optional index fields
        db.execute('''INSERT INTO hevy_exercises(workout_id,exercise_index,template_id,title,superset_id)
            VALUES(?,?,?,?,?)''',
            (workout_id, idx, ex.get('exercise_template_id'), ex.get('title') or '(Unnamed exercise)',
             ex.get('superset_id', ex.get('supersets_id'))))
        for j, set_ in enumerate(ex.get('sets') or []):
            if not isinstance(set_, dict):
                continue
            db.execute('''INSERT INTO hevy_sets(workout_id,exercise_index,set_index,set_type,weight_kg,reps,rpe,
                distance_meters,duration_seconds,custom_metric) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (workout_id, idx, j, set_.get('type'), set_.get('weight_kg'), set_.get('reps'),
                 set_.get('rpe'), set_.get('distance_meters'), set_.get('duration_seconds'),
                 set_.get('custom_metric')))
    return 'updated' if existing else 'new'


def _delete_workout(db, workout_id):
    prior = db.execute('SELECT 1 FROM hevy_workouts WHERE workout_id=?', (workout_id,)).fetchone()
    db.execute('DELETE FROM hevy_sets WHERE workout_id=?', (workout_id,))
    db.execute('DELETE FROM hevy_exercises WHERE workout_id=?', (workout_id,))
    db.execute('DELETE FROM hevy_workouts WHERE workout_id=?', (workout_id,))
    return bool(prior)


class HevyApiError(Exception):
    pass


class HevyEventSchemaMismatch(HevyApiError):
    """Events endpoint returned a workout snapshot instead of change events.

    This response cannot safely represent deletions, so the caller must
    reconcile against the real full-workout endpoint instead.
    """
    pass


def get_json(path, key, params=None, session=None):
    """Read-only GET with limited retry for transient errors. No key in query/exception output."""
    import requests
    connection = session if session is not None else requests
    response = None
    for attempt in range(3):
        try:
            response = connection.get(
                API_ROOT + path, params=params, headers={'api-key': key, 'Accept': 'application/json'}, timeout=30)
        except requests.RequestException as exc:
            if attempt == 2:
                raise HevyApiError(f'Hevy connection failed ({type(exc).__name__}); no data changed') from None
            time.sleep(1.5 * (attempt + 1)); continue
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(1.5 * (attempt + 1)); continue
        if response.status_code != 200:
            raise HevyApiError(f'Hevy request failed: HTTP {response.status_code} on {path}; no API key was logged')
        try:
            return response.json()
        except ValueError:
            raise HevyApiError(f'Hevy returned invalid JSON from {path}') from None
    raise HevyApiError(f'Hevy request failed: HTTP {response.status_code} on {path}')


def fetch_pages(path: str, key: str, field: str, params=None, progress=None, getter=get_json):
    """Fetch complete pages before mutating database.

    Hevy documents ``events`` in its OpenAPI schema, while some SDKs report
    ``workout_events``. Accept either, including a zero-page empty change feed.
    Fail clearly for other schemas instead of treating an unknown payload as
    zero events (which could silently skip workouts or deletions).
    """
    rows = []
    page = 1
    while True:
        q = dict(params or {}, page=page, pageSize=10)
        payload = getter(path, key, q)
        if not isinstance(payload, dict):
            raise HevyApiError(f'Unexpected Hevy payload for {path}: expected an object')
        raw_pages = payload.get('page_count', 1)
        if type(raw_pages) is not int or raw_pages < 0 or raw_pages > 10000:
            raise HevyApiError(f'Invalid Hevy page count for {path}')
        pages = raw_pages
        candidates = (field, 'workout_events') if field == 'events' else (field,)
        collection = next((payload[k] for k in candidates if isinstance(payload.get(k), list)), None)
        if collection is None:
            if field == 'events' and isinstance(payload.get('workouts'), list):
                # Observed on the live Hevy events endpoint: a workout-list
                # envelope instead of documented updated/deleted events.
                # Never interpret it as an empty event feed or as events.
                raise HevyEventSchemaMismatch(
                    'Hevy events endpoint returned a workouts list; full reconciliation required')
            # A server may represent an empty incremental feed as zero pages
            # with no collection field; this is unambiguous only when page_count=0.
            if field == 'events' and pages == 0 and page == 1:
                collection = []
            else:
                keys = ', '.join(sorted(str(k) for k in payload))
                raise HevyApiError(
                    f'Unexpected Hevy payload for {path}: expected {" or ".join(candidates)} '
                    f'as a list; response fields: [{keys}]; page_count={pages}')
        rows.extend(collection)
        if progress: progress(f'Hevy {field}: page {page}/{pages} · {len(rows)} records')
        if pages == 0 or page >= pages:
            break
        page += 1
    return rows


def sync_hevy(db: sqlite3.Connection, full=False, progress=None, getter=get_json):
    """First run loads every workout; later runs apply ordered updated/deleted events.

    The sync watermark records the *start* of the run, with a 2-minute overlap.
    This avoids silently skipping edits that occur while pagination is running.
    """
    ensure_hevy_schema(db)
    key=resolve_hevy_key()
    prior=db.execute("SELECT value FROM hevy_sync_state WHERE key='last_success_utc'").fetchone()
    full = full or prior is None
    started=datetime.now(timezone.utc)
    result={'mode':'full' if full else 'incremental','new':0,'updated':0,'unchanged':0,'deleted':0}
    if full:
        records=fetch_pages('/v1/workouts',key,'workouts',progress=progress,getter=getter)
        # Reject a suspiciously empty full snapshot when local workouts already
        # exist. Otherwise a transient API anomaly could delete the entire cache.
        if not records and db.execute('SELECT 1 FROM hevy_workouts LIMIT 1').fetchone():
            raise HevyApiError('Hevy returned an empty full workout list, so existing local records were preserved')
        ids=set()
        with db:
            for workout in records:
                if not isinstance(workout,dict) or not isinstance(workout.get('id'),str):
                    raise HevyApiError('Malformed full workout page; changes rolled back')
                ids.add(workout['id'])
                result[upsert_workout(db,workout)]+=1
            # A fully successful snapshot represents the complete account, including deletions.
            for (wid,) in db.execute('SELECT workout_id FROM hevy_workouts').fetchall():
                if wid not in ids:
                    result['deleted']+=int(_delete_workout(db,wid))
            db.execute("INSERT INTO hevy_sync_state(key,value) VALUES('last_success_utc',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (started.isoformat().replace('+00:00','Z'),))
    else:
        last=datetime.fromisoformat(prior[0].replace('Z','+00:00'))
        since=(last-timedelta(minutes=2)).isoformat().replace('+00:00','Z')
        try:
            events=fetch_pages('/v1/workouts/events',key,'events',params={'since':since},
                               progress=progress,getter=getter)
        except HevyEventSchemaMismatch:
            # No local records or sync checkpoint have been changed. Fetch the
            # complete authoritative workout listing, which includes edits and
            # allows deletions to be detected by absence. The full path is
            # transactional and refuses a suspicious empty snapshot.
            if progress:
                progress('Hevy returned workouts instead of events; reconciling full history safely…')
            fallback = sync_hevy(db, full=True, progress=progress, getter=getter)
            fallback['mode'] = 'full-fallback'
            return fallback
        with db:
            # Hevy returns newest first. Replay oldest to newest to handle successive edits.
            for event in reversed(events):
                if not isinstance(event,dict):raise HevyApiError('Malformed event')
                if event.get('type')=='updated':
                    result[upsert_workout(db,event.get('workout') or {})]+=1
                elif event.get('type')=='deleted' and isinstance(event.get('id'),str):
                    result['deleted']+=int(_delete_workout(db,event['id']))
                else:
                    raise HevyApiError('Unexpected workout event type; no data committed')
            db.execute("INSERT INTO hevy_sync_state(key,value) VALUES('last_success_utc',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (started.isoformat().replace('+00:00','Z'),))
    return result
