"""Synthetic regression coverage for v0.7. No personal health data."""
import unittest
from datetime import date
import numpy as np
import pandas as pd

from dashboard_v07 import (
    default_date_range, rolling_calorie_frame, calorie_chart,
    energy_overlay_frame, energy_overlay_chart, cumulative_balance_chart,
    classify_exercise, group_working_sets, weekly_muscle_sets,
    workout_breakdown, per_exercise_metrics,
)


class V07Tests(unittest.TestCase):
    def setUp(self):
        self.idx = pd.date_range('2026-09-01', periods=55, freq='D')
        self.daily = pd.DataFrame({'calories':[2500.]*55, 'meals':[4]*55,
            'source':['Health Connect']*55},index=self.idx)
        self.weight = pd.Series([150.]*55,index=self.idx,name='weight_lb')
        self.garmin = pd.DataFrame({'calories_burned':[2450.]*55},index=self.idx)

    def test_default_date_range_ends_yesterday(self):
        a,b=default_date_range(date(2026,10,29),date(2026,7,1))
        self.assertEqual(b,date(2026,10,28))
        self.assertEqual((b-a).days+1,90)

    def test_averages_use_days_prior_to_visible_window(self):
        trend=rolling_calorie_frame(self.daily,date(2026,10,24))
        last=trend.loc['2026-10-20':'2026-10-24']
        self.assertEqual(len(last),5)
        self.assertAlmostEqual(last.avg7.iloc[0],2500)
        self.assertAlmostEqual(last.avg30.iloc[-1],2500)
        fig=calorie_chart(last,2550,100)
        self.assertGreaterEqual(len(fig.data),3)

    def test_missing_and_one_meal_dates_do_not_mean_zero(self):
        data=self.daily.copy()
        data.loc[self.idx[-1],'calories']=np.nan
        data.loc[self.idx[-2],'meals']=1
        trend=rolling_calorie_frame(data,self.idx[-1].date())
        self.assertTrue(pd.isna(trend.iloc[-1]['usable']))
        self.assertTrue(pd.isna(trend.iloc[-2]['usable']))
        self.assertNotEqual(float(trend.iloc[-1]['avg7']),0)

    def test_today_can_be_excluded_without_false_warning(self):
        today=date(2026,10,26)
        start,end=default_date_range(today,date(2026,9,1))
        self.assertEqual(end,date(2026,10,25))
        self.assertLess(end,today)

    def test_overlay_and_cumulative_chart(self):
        start=self.idx[-28].date()
        end=self.idx[-1].date()
        view=energy_overlay_frame(self.daily,self.weight,self.garmin,start,end)
        self.assertEqual(len(view),28)
        self.assertAlmostEqual(view.weight_derived_tdee28.iloc[-1],2500,delta=1)
        self.assertEqual(len(energy_overlay_chart(view,2550).data),4)
        self.assertIsNotNone(cumulative_balance_chart(view))
        view.loc[view.index[3],'usable']=np.nan
        self.assertIsNone(cumulative_balance_chart(view))

    def _sets(self):
        idx=pd.to_datetime(['2026-10-15']*3+['2026-10-22']*2)
        exercises=['Bench Press (Barbell)','Face Pull','Chest Supported Reverse Fly (Dumbbell)',
                   'Deadlift (Barbell)','Cable Crunch']
        return pd.DataFrame({'workout_id':['A']*3+['B']*2,'local_date':idx,
           'exercise':exercises,'working_set':[True,True,True,True,True],
           'weight_lb':[120,45,25,225,50],'reps':[10,12,12,5,15],
           'estimated_1rm_lb':[160,np.nan,np.nan,262.5,np.nan]})

    def test_primary_group_mapping_and_weekly_counts(self):
        self.assertEqual(classify_exercise('Bench Press (Barbell)'),'Chest')
        self.assertEqual(classify_exercise('Rear Delt Reverse Fly (Cable)'),'Shoulders')
        self.assertEqual(classify_exercise('Chest Supported Reverse Fly (Dumbbell)'),'Shoulders')
        self.assertEqual(classify_exercise('Single Arm Cable Row'),'Back / hinge')
        self.assertEqual(classify_exercise('Front Squat'),'Legs')
        self.assertEqual(classify_exercise('Weighted Russian Twist'),'Core')
        data=group_working_sets(self._sets(),date(2026,10,1),date(2026,10,31))
        weekly=weekly_muscle_sets(data)
        self.assertEqual(int(weekly['sets'].sum()),5)
        self.assertEqual(int(workout_breakdown(data,'A')['sets'].sum()),3)

    def test_e1rm_and_volume_exclude_warmups(self):
        data=self._sets()
        data.loc[len(data)] = ['A',pd.Timestamp('2026-10-15'),'Bench Press (Barbell)',False,100,10,133.3]
        sessions=per_exercise_metrics(data,'Bench Press (Barbell)')
        self.assertEqual(len(sessions),1)
        self.assertAlmostEqual(sessions.iloc[0].volume_lb,1200)
        self.assertAlmostEqual(sessions.iloc[0].estimated_1rm_lb,160)


if __name__=='__main__':
    unittest.main()
