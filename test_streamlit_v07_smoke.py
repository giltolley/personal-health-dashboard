"""End-to-end UI smoke test with entirely synthetic in-memory-style data.

Creates a temporary SQLite database. No Supabase access or personal data.
"""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


class StreamlitUITests(unittest.TestCase):
    def test_dashboard_renders_all_tabs_with_sample_data(self):
        from importer import initialize
        from garmin_importer import ensure_schema
        from hevy_importer import ensure_hevy_schema
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/"synthetic.sqlite"
            db=initialize(file)
            ensure_schema(db)
            ensure_hevy_schema(db)
            today=datetime.now(ZoneInfo('America/New_York')).date()
            for ago in range(1,51):
                day=(today-timedelta(days=ago)).isoformat()
                for meal in range(4):
                    db.execute('''INSERT INTO nutrition
                      (record_id,local_date,app,meal_type,calories,protein_g,carbs_g,fat_g,fiber_g,sodium_mg,potassium_mg)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                        (f'demo-{ago}-{meal}',day,'synthetic',meal,625,40,75,15,8,500,900))
                db.execute('INSERT INTO weights VALUES(?,?,?,?)',
                           (f'weight-{ago}',day,'synthetic',150+ago*0.01))
                db.execute('''INSERT INTO garmin_daily
                  (local_date,calories_burned,calories_active,calories_resting,
                   hrv_ms,resting_hr,sleep_hours,steps)
                  VALUES(?,?,?,?,?,?,?,?)''',
                    (day,2500,600,1900,45,57,7.5,8000))
            workout_date=(today-timedelta(days=2)).isoformat()
            db.execute('''INSERT INTO hevy_workouts
                 (workout_id,local_date,title,start_time,end_time,updated_at,duration_minutes,raw_json)
                 VALUES (?,?,?,?,?,?,?,?)''',
                 ('synthetic-workout',workout_date,'Sample Push','2026-01-01T14:00:00Z',
                  '2026-01-01T15:00:00Z','2026-01-01T15:00:00Z',60,'{}'))
            db.execute('''INSERT INTO hevy_exercises
                 (workout_id,exercise_index,template_id,title,superset_id)
                 VALUES (?,?,?,?,?)''',
                 ('synthetic-workout',0,'sample-press','Bench Press (Barbell)',None))
            db.execute('''INSERT INTO hevy_sets
                 (workout_id,exercise_index,set_index,set_type,weight_kg,reps,rpe,
                  distance_meters,duration_seconds,custom_metric) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                 ('synthetic-workout',0,0,'normal',70,5,8,None,None,None))
            db.commit()
            db.close()
            original=os.environ.get('NUTRITION_DB')
            original_url=os.environ.pop('DATABASE_URL',None)
            os.environ['NUTRITION_DB']=str(file)
            try:
                at=AppTest.from_file('app.py',default_timeout=45).run()
                self.assertFalse(at.exception, 'Streamlit failed to render: '+str(at.exception))
                self.assertEqual([tab.label for tab in at.tabs],
                    ['Overview','Energy & Nutrition','Training','Recovery & Health','Data & Sync'])
                self.assertFalse(any('Insights' in tab.label for tab in at.tabs))
            finally:
                if original is None: os.environ.pop('NUTRITION_DB',None)
                else: os.environ['NUTRITION_DB']=original
                if original_url is not None: os.environ['DATABASE_URL']=original_url


if __name__=='__main__':
    unittest.main()
