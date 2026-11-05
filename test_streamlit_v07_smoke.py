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
                   hrv_ms,resting_hr,sleep_hours,steps,intensity_minutes)
                  VALUES(?,?,?,?,?,?,?,?,?)''',
                    (day,2500,600,1900,45,57,6.5,8000,25))
                if ago<8:
                    db.execute("INSERT INTO hc_blood_pressure VALUES (?,?,?,?,?)",
                               (f"bp-{ago}",day,"synthetic",125,82))
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
            from goals import ensure_goals,save_goal
            ensure_goals(db)
            save_goal(db,(today-timedelta(days=20)).isoformat(),'Muscle gain',2800,160)
            db.commit()
            db.close()
            original=os.environ.get('NUTRITION_DB')
            original_url=os.environ.pop('DATABASE_URL',None)
            original_goal=os.environ.get('CALORIE_GOAL')
            os.environ['CALORIE_GOAL']='2550'
            os.environ['NUTRITION_DB']=str(file)
            try:
                at=AppTest.from_file('app.py',default_timeout=45)
                at.session_state['calorie_goal']=2550  # Older widget state must not override current target.
                at.run()
                self.assertFalse(at.exception, 'Streamlit failed to render: '+str(at.exception))
                self.assertEqual([tab.label for tab in at.tabs],
                    ['Overview','Energy & Nutrition','Training','Recovery & Health','Data & Sync','Labs'])
                self.assertFalse(any('Insights' in tab.label for tab in at.tabs))
                expected=['1. Blood Pressure','2. Cardiovascular Health','3. Sleep Quality',
                          '4. Dietary Analysis','5. Intake vs. Training Heuristics']
                headings=[h.value for h in at.subheader]
                self.assertTrue(all(label in headings for label in expected))
                self.assertTrue(any('Stage 1 range' in item.value for item in at.markdown))
                self.assertTrue(any('Personal minimum met' in item.value for item in at.markdown))
                self.assertTrue(any('Intensity-minute coverage: 7/7' in item.value for item in at.caption))
                self.assertEqual(at.number_input(key='goal_calories').value,2800)
                self.assertGreaterEqual(len(at.get('plotly_chart')),7)
                at.date_input(key='goal_effective_date').set_value(today-timedelta(days=1))
                at.number_input(key='goal_calories').set_value(3000)
                at.number_input(key='goal_protein').set_value(170)
                next(button for button in at.button if button.label=='Save dated goal').click().run()
                self.assertFalse(at.exception)
                dietary=next(item.value for item in at.dataframe if 'Nutrient' in item.value.columns)
                self.assertIn('42.0',dietary.set_index('Nutrient').loc['Fiber','Reference'])
                self.assertTrue(any('3,000-kcal target' in item.value for item in at.caption))
                verify=sqlite3.connect(file)
                self.assertEqual(verify.execute('SELECT COUNT(*) FROM goal_history').fetchone()[0],2)
                verify.close()
            finally:
                if original is None: os.environ.pop('NUTRITION_DB',None)
                else: os.environ['NUTRITION_DB']=original
                if original_url is not None: os.environ['DATABASE_URL']=original_url
                if original_goal is None: os.environ.pop('CALORIE_GOAL',None)
                else: os.environ['CALORIE_GOAL']=original_goal


if __name__=='__main__':
    unittest.main()
