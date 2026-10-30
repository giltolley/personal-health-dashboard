"""Synthetic tests for v0.8's one-question-per-chart layout."""
import unittest
import pandas as pd

from dashboard_v08 import (
    summary, recent_logged_intake, recent_garmin, recent_lift,
    daily_weight, weight_smoothed, weight_chart,
    calories_chart, expenditure_chart, muscle_counts, muscle_chart,
)


class FocusedDashboardTests(unittest.TestCase):
    def setUp(self):
        dates=pd.date_range("2026-09-01",periods=60,freq="D")
        self.end=dates[-1].date()
        self.daily=pd.DataFrame({"calories":[2500.]*60,"meals":[4]*60,
                                 "source":["Health Connect"]*60},index=dates)
        self.weight=pd.Series([150.]*60,index=dates,name="weight_lb")
        self.garmin=pd.DataFrame({"calories_burned":[2450.]*60},index=dates)

    def test_overview_estimates_only_complete_days(self):
        m=summary(self.daily,self.weight,self.garmin,self.end,28)
        self.assertTrue(m["valid"])
        self.assertAlmostEqual(m["estimated_tdee"],2500,delta=1)
        avg,n=recent_logged_intake(self.daily,self.end,7)
        self.assertEqual(n,7)
        self.assertEqual(avg,2500)
        avg,n=recent_garmin(self.garmin,self.end,28)
        self.assertEqual((avg,n),(2450,28))

    def test_summary_refuses_low_coverage(self):
        food=self.daily.copy()
        food.iloc[-12:,food.columns.get_loc("meals")]=0
        m=summary(food,self.weight,self.garmin,self.end,28)
        self.assertFalse(m["valid"])

    def test_calories_graph_has_only_daily_bars_by_default(self):
        fig=calories_chart(self.daily,self.end-pd.Timedelta(days=29),self.end)
        self.assertEqual(len(fig.data),1)
        self.assertEqual(fig.data[0].type,"bar")
        self.assertEqual(len(fig.layout.shapes or ()),0)
        shaded=calories_chart(self.daily,self.end-pd.Timedelta(days=29),self.end,
                              goal=2500,tolerance=100,show_band=True)
        self.assertEqual(len(shaded.data),1)
        self.assertGreaterEqual(len(shaded.layout.shapes),1)

    def test_weight_and_garmin_are_separate_one_series_charts(self):
        start=self.end-pd.Timedelta(days=29)
        self.assertEqual(len(weight_chart(self.weight,start,self.end).data),1)
        self.assertEqual(len(weight_chart(self.weight,start,self.end,True).data),2)
        self.assertEqual(len(expenditure_chart(self.garmin,start,self.end).data),1)
        self.assertAlmostEqual(weight_smoothed(self.weight,self.end).dropna().iloc[-1],150)

    def test_lift_and_primary_work_sets(self):
        day=pd.Timestamp(self.end)
        records=pd.DataFrame({
            "local_date":[day-pd.Timedelta(days=5),day],
            "workout_id":["a","b"],
            "exercise":["Bench Press (Barbell)"]*2,
            "working_set":[True,True],
            "weight_lb":[130.,135.],
            "reps":[5,5],
            "estimated_1rm_lb":[130*(1+5/30),135*(1+5/30)],
        })
        lift=recent_lift(records,"Bench Press (Barbell)",self.end)
        self.assertAlmostEqual(lift["change"],5*(1+5/30))
        muscles=muscle_counts(records,self.end,days=14)
        self.assertEqual(muscles.sets.sum(),2)
        self.assertEqual(muscles.group.iloc[0],"Chest")
        self.assertEqual(len(muscle_chart(muscles,"Test").data),1)


if __name__=="__main__":
    unittest.main()
