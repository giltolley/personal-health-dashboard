"""Chart contracts: units, reference direction, unknown values and date windows."""
import unittest
import numpy as np
import pandas as pd
from overview_charts import (bp_figure,activity_figure,nutrient_figure,
                             lift_change_figure,training_weight_figure,TEAL,AMBER)


class OverviewChartTests(unittest.TestCase):
    def setUp(self):
        self.end=pd.Timestamp('2026-11-03')
        self.dates=pd.date_range(end=self.end,periods=7)

    def test_bp_separate_components_and_gaps(self):
        frame=pd.DataFrame({'systolic':[125,135],'diastolic':[75,85]},
                           index=[self.dates[0],self.dates[-1]])
        fig=bp_figure(frame,self.end)
        self.assertEqual(len(fig.data),2)
        self.assertEqual(fig.data[0].yaxis,'y')
        self.assertEqual(fig.data[1].yaxis,'y2')
        self.assertEqual(sum(pd.notna(fig.data[0].y)),2)
        self.assertEqual(sorted(s.y0 for s in fig.layout.shapes),[80,130])
        self.assertFalse(fig.data[0].connectgaps)

    def test_activity_targets_and_axes_are_not_clipped_at_goal(self):
        fig=activity_figure({'minutes':225,'coverage':7,'strength_days':3})
        self.assertEqual(fig.data[0].x[0],225)
        self.assertEqual(fig.data[1].x[0],3)
        self.assertGreater(fig.layout.xaxis.range[1],225)
        self.assertEqual(fig.layout.xaxis.title.text,'minutes')
        self.assertEqual(fig.layout.xaxis2.title.text,'days')
        self.assertEqual(sorted(s.x0 for s in fig.layout.shapes),[2,150])
        missing=activity_figure({'minutes':np.nan,'coverage':0,'strength_days':0})
        self.assertEqual(len(missing.data),1)  # Only recorded Hevy days; no invented aerobic zero.

    def test_nutrient_missing_incomplete_and_zero_are_distinct(self):
        frame=pd.DataFrame({'calories':[2800]*7,'meals':[4,4,1,4,4,4,4],
                            'fiber_g':[40,np.nan,100,0,30,40,40]},index=self.dates)
        fig=nutrient_figure(frame,self.end,'fiber_g','Fiber',39.2,'at least','g')
        self.assertTrue(pd.isna(fig.data[0].y[1]))
        self.assertTrue(pd.isna(fig.data[0].y[2]))
        self.assertEqual(fig.data[0].y[3],0)
        self.assertEqual(fig.layout.shapes[0].y0,39.2)
        self.assertEqual(fig.data[0].marker.color[0],TEAL)
        self.assertEqual(fig.data[0].marker.color[4],AMBER)
        sodium=frame.rename(columns={'fiber_g':'sodium_mg'})
        sodium['sodium_mg']=[2200,2400,2200,0,2200,2200,2200]
        fig=nutrient_figure(sodium,self.end,'sodium_mg','Sodium',2300,'at most','mg')
        self.assertEqual(fig.data[0].marker.color[0],TEAL)
        self.assertEqual(fig.data[0].marker.color[1],AMBER)
        self.assertEqual(fig.layout.yaxis.title.text,'mg')

    def test_lifts_do_not_plot_unknown_change_as_zero(self):
        lifts=pd.DataFrame({'Lift':['Bench','Deadlift'],
                            'Median e1RM change (%)':[3,np.nan]})
        fig=lift_change_figure(lifts)
        self.assertEqual(list(fig.data[0].y),['Bench'])
        self.assertEqual(list(fig.data[0].x),[3])
        self.assertIsNone(lift_change_figure(lifts.iloc[1:]))
        self.assertIsNone(lift_change_figure(pd.DataFrame()))

    def test_weight_chart_does_not_carry_old_data_to_window(self):
        w=pd.Series(150.,index=self.dates-pd.Timedelta(days=60))
        self.assertIsNone(training_weight_figure(w,self.end))
        w=pd.Series(150.,index=self.dates)
        fig=training_weight_figure(w,self.end)
        self.assertEqual(len(fig.data[0].x),28)
        self.assertEqual(fig.layout.yaxis.title.text,'Weight (lb)')


if __name__=='__main__':
    unittest.main()
