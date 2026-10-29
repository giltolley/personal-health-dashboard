"""Regression tests for v0.6 analytical calculations (no database or secrets)."""
import unittest
import numpy as np
import pandas as pd
from insights_v06 import energy_window, estimate_tdee, nutrition_daily, source_freshness


class InsightsTests(unittest.TestCase):
    def sample(self, n=28, delta_lb=0):
        idx = pd.date_range("2026-10-01", periods=n, freq="D")
        ndata = pd.DataFrame({"calories":[2600.0]*n, "meals":[4]*n, "protein_g":[170]*n},index=idx)
        weight = pd.Series([145+delta_lb*i/7 for i in range(n)],index=idx)
        garmin = pd.DataFrame({"calories_burned":[2490.0]*n},index=idx)
        return energy_window(ndata,weight,garmin,idx[-1],n)

    def test_stable_weight_tdee_tracks_intake(self):
        result=estimate_tdee(self.sample())
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["estimated_tdee"],2600,delta=1)

    def test_loss_increases_estimated_tdee(self):
        result=estimate_tdee(self.sample(delta_lb=-0.2))
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["trend_lb_week"],-0.2,delta=0.001)
        self.assertAlmostEqual(result["estimated_tdee"],2700,delta=1)

    def test_missing_or_incomplete_intake_not_zero(self):
        df=self.sample()
        df.loc[df.index[:8],"meals"]=np.nan
        df.loc[df.index[:8],"usable_intake"]=np.nan
        df.loc[df.index[:8],"complete_intake"]=False
        result=estimate_tdee(df)
        self.assertFalse(result["valid"])
        self.assertEqual(result["intake_days"],20)

    def test_macro_gap_and_absent_days(self):
        idx=pd.date_range("2026-10-01",periods=2)
        src=pd.DataFrame({"calories":[2000.],"protein_g":[150.],"carbs_g":[200.],
           "fat_g":[60.],"fiber_g":[20.],"sodium_mg":[2000.],"potassium_mg":[3000.],"meals":[4]},index=idx[:1])
        day=nutrition_daily(src,idx[0],idx[1])
        self.assertTrue(day["complete"].iloc[0])
        self.assertFalse(day["complete"].iloc[1])
        self.assertTrue(pd.isna(day["calories"].iloc[1]))

    def test_sync_freshness(self):
        now=pd.Timestamp("2026-10-29T18:00:00Z")
        log=pd.DataFrame([{"source":"Health Connect Drive","status":"ok","started_at":"2026-10-29T04:00:00Z"}])
        status=source_freshness(log,now)
        hc=status.set_index("Source").loc["Health Connect Drive"]
        self.assertEqual(hc["Status"],"Recent")
        self.assertEqual(hc["Hours since"],14)


if __name__=="__main__":
    unittest.main()
