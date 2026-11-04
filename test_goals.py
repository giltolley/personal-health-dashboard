"""Synthetic goal persistence, revisions and historical boundary checks."""
import sqlite3
import unittest
import pandas as pd
from goals import ensure_goals,read_goals,save_goal,goal_at,targets_for_dates,window_context
from goals_ui import editor_allowed
from overview_charts import nutrient_figure
from dashboard_v08 import calories_chart


class GoalsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        ensure_goals(self.db)
        save_goal(self.db,None,'Unspecified',2100,known_before_date='2025-03-01')
        save_goal(self.db,'2025-03-01','Maintenance',2400)
        save_goal(self.db,'2025-03-15','Maintenance',2500)
        save_goal(self.db,'2025-04-01','Muscle gain',2700,155)
        self.history=read_goals(self.db)

    def tearDown(self):
        self.db.close()

    def test_unknown_start_is_retained_without_inventing_dates(self):
        self.assertEqual(len(self.history),4)
        self.assertTrue(pd.isna(goal_at(self.history,'2025-02-28').calories))
        self.assertEqual(self.history[self.history.effective_date.isna()].iloc[0].calories,2100)

    def test_date_boundaries_and_unknown_historical_protein(self):
        for dt,kcal in [('2025-03-01',2400),('2025-03-14',2400),
                        ('2025-03-15',2500),('2025-03-31',2500),('2025-04-01',2700)]:
            self.assertEqual(goal_at(self.history,dt).calories,kcal)
        self.assertTrue(pd.isna(goal_at(self.history,'2025-03-31').protein_g))
        self.assertEqual(goal_at(self.history,'2025-04-01').protein_g,155)

    def test_revisions_are_append_only_and_future_targets_not_used_early(self):
        save_goal(self.db,'2025-04-01','Muscle gain',2750,160)
        save_goal(self.db,'2025-05-01','Maintenance',2600)
        h=read_goals(self.db)
        self.assertEqual(len(h),6)
        self.assertEqual(goal_at(h,'2025-04-01').calories,2750)
        self.assertEqual(goal_at(h,'2025-03-31').calories,2500)

    def test_persistence_across_reopen(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'goals.sqlite'
            db=sqlite3.connect(path);ensure_goals(db)
            save_goal(db,'2025-01-01','Maintenance',2400);db.close()
            db=sqlite3.connect(path)
            self.assertEqual(goal_at(read_goals(db),'2025-01-02').calories,2400)
            db.close()

    def test_phase_window_context(self):
        ctx=window_context(self.history,'2025-04-02')
        self.assertTrue(ctx['mixed'])
        self.assertEqual(ctx['days_on_target'],2)
        self.assertFalse(window_context(self.history,'2025-04-30')['mixed'])

    def test_invalid_values_and_editor_gate(self):
        for kcal in [float('nan'),float('inf'),0]:
            with self.assertRaises(ValueError):save_goal(self.db,'2025-01-01','Maintenance',kcal)
        self.assertFalse(editor_allowed(True,'',''))
        self.assertFalse(editor_allowed(True,'owner-secret','wrong'))
        self.assertTrue(editor_allowed(True,'owner-secret','owner-secret'))
        self.assertTrue(editor_allowed(False,'',''))

    def test_charts_follow_dated_targets(self):
        dates=pd.date_range('2025-03-30',periods=4)
        daily=pd.DataFrame({'calories':2700.,'meals':4,'fiber_g':40.},index=dates)
        fig=nutrient_figure(daily,dates[-1],'fiber_g','Fiber',37.8,'at least','g',self.history)
        references=pd.Series(fig.data[1].y,index=fig.data[1].x)
        self.assertEqual(references.loc['2025-03-31'],35)
        self.assertAlmostEqual(references.loc['2025-04-01'],37.8)
        fig=calories_chart(daily,dates[0],dates[-1],2700,100,True,self.history)
        target=next(t for t in fig.data if t.name=='Saved calorie target')
        self.assertEqual(list(target.y),[2500,2500,2700,2700])

    def test_nutrition_does_not_score_unknown_protein_references_as_failures(self):
        from overview_metrics import nutrition_summary
        dates=pd.date_range(end='2025-04-02',periods=7)
        daily=pd.DataFrame({'calories':2700.,'meals':4,'fiber_g':40.,'protein_g':160.,'sodium_mg':2200.},index=dates)
        table,_=nutrition_summary(daily,dates[-1],2700,155,self.history)
        protein=table.set_index('Nutrient').loc['Protein']
        self.assertEqual(protein['Days with values'],7)
        self.assertEqual(protein['Days with reference'],2)
        self.assertEqual(protein['Days meeting reference'],2)
