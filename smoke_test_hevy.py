"""Offline tests for Hevy import, UTC/local date, idempotence, edits and deletions."""
import sqlite3
from unittest.mock import patch
from hevy_importer import ensure_hevy_schema, sync_hevy, fetch_pages, HevyApiError


def workout(id_, date, weight):
    return {'id':id_, 'title':'Day 1 - Push', 'start_time':date+'T01:00:00Z',
            'end_time':date+'T02:00:00Z', 'updated_at':date+'T03:00:00Z',
            'exercises':[{'title':'Bench Press (Barbell)', 'exercise_template_id':'05293BCA',
                'index':0,'sets':[
                    {'index':0,'type':'warmup','weight_kg':20,'reps':10},
                    {'index':1,'type':'normal','weight_kg':weight,'reps':5}]}]}


def main():
    db=sqlite3.connect(':memory:')
    ensure_hevy_schema(db)
    w1=workout('a','2026-10-24',80)
    w2=workout('b','2026-10-23',90)
    calls=[]
    def initial(path,key,params):
        calls.append((path,params['page']))
        if path != '/v1/workouts':raise AssertionError(path)
        page=params['page']
        return {'page':page,'page_count':2,'workouts':[w1] if page==1 else [w2]}
    with patch('hevy_importer.resolve_hevy_key',return_value='fake-key'):
        r=sync_hevy(db,getter=initial)
        assert r == {'mode':'full','new':2,'updated':0,'unchanged':0,'deleted':0}, r
        # UTC 01:00 is previous evening in US Eastern
        assert db.execute("SELECT local_date FROM hevy_workouts WHERE workout_id='a'").fetchone()[0]=='2026-10-23'
        assert db.execute('SELECT COUNT(*) FROM hevy_sets').fetchone()[0]==4
        assert db.execute('SELECT COUNT(*) FROM hevy_workouts').fetchone()[0]==2
        assert calls==[('/v1/workouts',1),('/v1/workouts',2)]
        # repeated full sync doesn't duplicate anything
        r=sync_hevy(db,full=True,getter=initial)
        assert r['unchanged']==2 and r['new']==0
        assert db.execute('SELECT COUNT(*) FROM hevy_sets').fetchone()[0]==4
        new_w1=workout('a','2026-10-24',85)
        def delta(path,key,params):
            assert path=='/v1/workouts/events'
            assert 'since' in params
            return {'page':1,'page_count':1,'events':[
                {'type':'deleted','id':'b','deleted_at':'2026-10-28T00:00:00Z'},
                {'type':'updated','workout':new_w1}]}
        r=sync_hevy(db,getter=delta)
        assert r['updated']==1 and r['deleted']==1, r
        assert db.execute('SELECT COUNT(*) FROM hevy_workouts').fetchone()[0]==1
        assert db.execute("SELECT weight_kg FROM hevy_sets WHERE workout_id='a' AND set_index=1").fetchone()[0]==85
        assert db.execute('SELECT COUNT(*) FROM hevy_sets').fetchone()[0]==2
        oldmark=db.execute("SELECT value FROM hevy_sync_state WHERE key='last_success_utc'").fetchone()[0]
        def fails(path,key,params):
            raise HevyApiError('simulated HTTP 503')
        try:sync_hevy(db,getter=fails)
        except HevyApiError:pass
        else:raise AssertionError('Expected an API error')
        assert db.execute("SELECT value FROM hevy_sync_state WHERE key='last_success_utc'").fetchone()[0]==oldmark
        assert db.execute('SELECT COUNT(*) FROM hevy_workouts').fetchone()[0]==1
    print('PASS: pagination, local dates, idempotence, updated/deleted events and failure safety')

if __name__=='__main__': main()
