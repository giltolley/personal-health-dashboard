"""Regression tests for the observed Hevy events->workouts mismatch, no network or credentials."""
import sqlite3
from unittest.mock import patch
from hevy_importer import ensure_hevy_schema, sync_hevy, HevyApiError


def workout(wid, weight=50.0):
    return {
        'id': wid, 'title': 'Strength', 'start_time': '2026-10-24T10:00:00-04:00',
        'end_time': '2026-10-24T11:00:00-04:00', 'updated_at': '2026-10-24T11:00:00-04:00',
        'exercises': [{'title': 'Bench', 'exercise_template_id': 'B1',
                       'sets': [{'type': 'normal', 'weight_kg': weight, 'reps': 5}]}]
    }


def count(db):
    return db.execute('SELECT count(*) FROM hevy_workouts').fetchone()[0]


def checkpoint(db):
    return db.execute("SELECT value FROM hevy_sync_state WHERE key='last_success_utc'").fetchone()[0]


def main():
    db = sqlite3.connect(':memory:')
    ensure_hevy_schema(db)
    current = [workout('a'), workout('b')]
    calls=[]

    def api(path, key, params):
        calls.append((path, params['page']))
        if path == '/v1/workouts/events':
            return {'page': 1, 'page_count': 1, 'workouts': [current[0]]}
        if path == '/v1/workouts':
            # Paginate so that a fallback must request *every* page.
            page = params['page']
            return {'page': page, 'page_count': len(current), 'workouts': [current[page - 1]]}
        raise AssertionError(path)

    with patch('hevy_importer.resolve_hevy_key', return_value='not-a-real-key'):
        initial = sync_hevy(db, getter=api)
        assert initial['mode'] == 'full' and initial['new'] == 2
        assert count(db) == 2
        calls.clear()
        again = sync_hevy(db, getter=api)
        assert again['mode'] == 'full-fallback' and again['unchanged'] == 2, again
        assert calls == [('/v1/workouts/events',1), ('/v1/workouts',1), ('/v1/workouts',2)], calls
        assert count(db) == 2

        # Updated workouts applied once, without creating duplicates.
        current[0] = workout('a',75)
        changed = sync_hevy(db, getter=api)
        assert changed['mode'] == 'full-fallback' and changed['updated'] == 1, changed
        assert db.execute("SELECT weight_kg FROM hevy_sets WHERE workout_id='a'").fetchone()[0] == 75
        assert count(db) == 2

        # Snapshot reconciliation picks up deletions despite no event feed.
        current[:] = [workout('a',75)]
        removed = sync_hevy(db, getter=api)
        assert removed['mode'] == 'full-fallback' and removed['deleted'] == 1, removed
        assert count(db) == 1

        # A failed full fallback must leave DB and watermark untouched.
        previous = checkpoint(db)
        def failed(path, key, params):
            if path == '/v1/workouts/events':
                return {'page':1,'page_count':1,'workouts':[]}
            raise HevyApiError('Simulated full history failure')
        try:sync_hevy(db, getter=failed)
        except HevyApiError:pass
        else:raise AssertionError('Failed fallback unexpectedly succeeded')
        assert count(db) == 1 and checkpoint(db) == previous

        # An unrecognized structure must fail closed, not silently mark success.
        def unknown(path, key, params):
            return {'page':1,'page_count':1,'mystery':[]}
        try:sync_hevy(db, getter=unknown)
        except HevyApiError:pass
        else:raise AssertionError('Unknown payload accepted')
        assert checkpoint(db) == previous

        # Normal event format still works and does not require full fallback.
        def normal(path, key, params):
            assert path == '/v1/workouts/events'
            return {'page':1,'page_count':1,'events':[{'type':'updated','workout':workout('a',80)}]}
        regular=sync_hevy(db, getter=normal)
        assert regular['mode'] == 'incremental' and regular['updated'] == 1
        assert count(db) == 1
    print('PASS: real-world workouts payload fallback, pagination, idempotency, updates, deletions, rollback, normal events')

if __name__ == '__main__': main()
