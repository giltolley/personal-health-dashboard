"""Decision thresholds, missing-data behavior and calendar-window regression tests."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from overview_metrics import (bp_summary, sleep_summary, cardio_summary,
                              nutrition_summary, training_summary)


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.end=pd.Timestamp('2026-11-03')
        self.idx=pd.date_range(end=self.end,periods=7)

    def test_bp_uses_either_component_and_requires_several_days(self):
        bp=pd.DataFrame({'systolic':[118]*7,'diastolic':[85]*7},index=self.idx)
        self.assertEqual(bp_summary(bp,self.end)['category'],'Stage 1 range')
        self.assertEqual(bp_summary(bp.iloc[-1:],self.end)['category'],'Insufficient recent readings')
        self.assertEqual(bp_summary(bp,self.end+pd.Timedelta(days=14))['days'],0)
        bp.iloc[-1]=[185,85]
        self.assertIn('Recheck',bp_summary(bp,self.end)['action'])

    def test_sleep_boundaries_and_missing_are_distinct(self):
        g=pd.DataFrame({'sleep_hours':[5.99,6,6.99,7,np.nan,0,8]},index=self.idx)
        s=sleep_summary(g,self.end)
        self.assertEqual(s['days'],5)
        self.assertEqual(s['below'],1)
        self.assertEqual(s['recommended'],2)
        self.assertTrue(np.isnan(sleep_summary(pd.DataFrame(),self.end)['mean']))

    def test_intensity_already_weighted_no_activity_addition(self):
        g=pd.DataFrame({'intensity_minutes':[30,30,np.nan,30,30,30,0]},index=self.idx)
        workouts=pd.DataFrame({'workout_id':['one','two','three']},
                              index=[self.idx[1],self.idx[1],self.idx[3]])
        r=cardio_summary(g,workouts,self.end)
        self.assertEqual(r['minutes'],150)
        self.assertEqual(r['coverage'],6)
        self.assertEqual(r['strength_days'],2)
        self.assertEqual(r['remaining'],0)
        self.assertTrue(np.isnan(cardio_summary(pd.DataFrame(),pd.DataFrame(),self.end)['minutes']))

    def test_nutrient_coverage_and_personal_goal(self):
        daily=pd.DataFrame({'calories':[2800]*7,'meals':[4]*6+[1],
            'fiber_g':[40,40,40,40,40,np.nan,100],
            'protein_g':[155]*7,'sodium_mg':[2200]*7},index=self.idx)
        table,days=nutrition_summary(daily,self.end,2800,160)
        self.assertEqual(days,6)
        fiber=table.set_index('Nutrient').loc['Fiber']
        self.assertEqual(fiber['Days with values'],5)
        self.assertEqual(fiber['Average'],40)
        self.assertIn('39.2',fiber['Reference'])
        self.assertEqual(table.set_index('Nutrient').loc['Protein','Days meeting reference'],0)

    def test_null_meal_nutrients_do_not_become_partial_daily_totals(self):
        from importer import initialize,read_daily
        with tempfile.TemporaryDirectory() as temp:
            db=initialize(Path(temp)/'test.sqlite')
            for i,fiber in enumerate([10,None,0]):
                db.execute('INSERT INTO nutrition (record_id,local_date,app,calories,fiber_g) VALUES (?,?,?,?,?)',
                           (str(i),'2026-11-03','synthetic',600,fiber))
            db.commit()
            daily=read_daily(db)
            self.assertEqual(daily.iloc[0].calories,1800)
            self.assertTrue(pd.isna(daily.iloc[0].fiber_g))
            db.close()

    def test_empty_inputs_and_no_stale_training_advice(self):
        table,days=nutrition_summary(pd.DataFrame(),self.end,2800)
        self.assertEqual(days,0)
        self.assertTrue(table.Average.isna().all())
        energy,lifts,action=training_summary(pd.DataFrame(),pd.Series(dtype=float),
                                           pd.DataFrame(),pd.DataFrame(),self.end)
        self.assertFalse(energy['valid'])
        self.assertIn('needed',action)

    def test_calorie_review_requires_two_windows_and_repeated_lifts(self):
        idx=pd.date_range(end=self.end,periods=56)
        daily=pd.DataFrame({'calories':2800,'meals':4},index=idx)
        weight=pd.Series(150+np.arange(56)*.1,index=idx)
        rows=[]
        for name in ['Bench Press (Barbell)','Deadlift (Barbell)']:
            for i in [3,10,35,42]:
                rows.append({'workout_id':f'{name}-{i}','local_date':idx[i],
                    'exercise':name,'weight_lb':100.,'reps':5,'set_type':'normal',
                    'working_set':True,'load_volume_lb':500.,'estimated_1rm_lb':100*(1+5/30)})
        sets=pd.DataFrame(rows)
        _,table,action=training_summary(daily,weight,pd.DataFrame(),sets,self.end)
        self.assertEqual(len(table),2)
        self.assertIn('surplus',action)
        _,_,action=training_summary(daily.iloc[-28:],weight,pd.DataFrame(),sets,self.end)
        self.assertIn('needed',action)


class EmptyOverviewUITests(unittest.TestCase):
    def test_all_sections_render_without_recent_measurements(self):
        from streamlit.testing.v1 import AppTest
        at=AppTest.from_string("""
import pandas as pd
from datetime import date
from overview import render_overview
render_overview(pd.DataFrame(),pd.Series(dtype=float),pd.DataFrame(),
                pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),date(2026,11,3),2800)
""").run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.subheader),5)
        self.assertTrue(any('No recent sleep measurements' in x.value for x in at.markdown))


if __name__=='__main__':
    unittest.main()
