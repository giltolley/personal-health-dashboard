"""Synthetic checks for the selectable energy plot and 5/3/1 planning logic."""
import unittest
import numpy as np
import pandas as pd
from dashboard_v09 import (
    WEEKS, LIFTS, ENERGY_SERIES, round_plate, prescription,
    detect_week3_training_max, summarize_next_cycle,
    display_energy_frame, interactive_energy_figure,
)


def mock_lift_sets(name, tm, day, include_backoff=True):
    steps=[.75,.85,.95]
    rows=[]
    for i,ratio in enumerate(steps):
        rows.append({
            "workout_id":f"{name}-{day}",
            "local_date":pd.Timestamp(day),"exercise":name,
            "set_index":i+1,"set_type":"normal",
            "weight_lb":round_plate(tm*ratio),"reps":[5,3,7][i]
        })
    if include_backoff:
        for i in range(2):
            rows.append({
                "workout_id":f"{name}-{day}",
                "local_date":pd.Timestamp(day),"exercise":name,
                "set_index":4+i,"set_type":"normal",
                "weight_lb":round_plate(tm*.80),"reps":8
            })
    return rows


class TrainingCycleTests(unittest.TestCase):
    def setUp(self):
        self.inputs=[
            ("Bench Press (Barbell)",165,"2025-06-18"),
            ("Overhead Press (Barbell)",115,"2025-06-17"),
            ("Squat (Barbell)",205,"2025-06-19"),
            ("Deadlift (Barbell)",315,"2025-06-20"),
        ]
        rows=[]
        for exercise,tm,day in self.inputs:
            rows+=mock_lift_sets(exercise,tm,day)
        self.log=pd.DataFrame(rows)

    def test_rounding_and_all_weeks(self):
        self.assertEqual(round_plate(82.5,5),85)
        self.assertEqual(round_plate(104,5),105)
        p=prescription(175)
        self.assertEqual(len(p),9)
        self.assertEqual(p["Reps"].to_list(),["5","5","5+","3","3","3+","5","3","1+"])
        self.assertEqual(p["Weight (lb)"].to_list(),
            [115.,130.,150.,125.,140.,160.,130.,150.,165.])

    def test_infer_four_fictional_cycle_maxes(self):
        expected={"Bench press":(165,170),"Overhead press":(115,120),
                  "Squat":(205,215),"Deadlift":(315,325)}
        table,discovered=summarize_next_cycle(self.log,through="2025-07-01")
        self.assertEqual(len(table),4)
        for label,(current,next_tm) in expected.items():
            observed=table[table.Lift.eq(label)].iloc[0]
            self.assertEqual(observed["Current TM (lb)"],current)
            self.assertEqual(observed["Next TM (lb)"],next_tm)
            self.assertEqual(discovered[label]["last_plus_reps"],7)

    def test_week2_pattern_is_not_mistaken_for_week3(self):
        data=pd.DataFrame([
            {"workout_id":"w2","local_date":pd.Timestamp("2025-06-10"),
             "exercise":"Bench Press (Barbell)","set_index":i,
             "set_type":"normal","weight_lb":w,"reps":r}
            for i,(w,r) in enumerate([(115,3),(130,3),(150,8)],1)
        ])
        self.assertIsNone(detect_week3_training_max(data,"Bench Press (Barbell)"))

    def test_warmups_backoffs_and_missing_workouts(self):
        warm=pd.DataFrame([{
            "workout_id":"later","local_date":pd.Timestamp("2025-07-02"),
            "exercise":"Bench Press (Barbell)","set_index":j,
            "set_type":"warmup","weight_lb":w,"reps":r}
            for j,(w,r) in enumerate([(125,5),(140,3),(155,6)])])
        combined=pd.concat([self.log,warm],ignore_index=True)
        inferred=detect_week3_training_max(combined,"Bench Press (Barbell)")
        self.assertEqual(inferred["tm"],165)
        self.assertIsNone(detect_week3_training_max(
            combined,"Unrecognized Lift",through="2025-07-03"))
        self.assertRaises(ValueError,prescription,0)

    def test_custom_plate_increment(self):
        self.assertEqual(round_plate(101.25,2.5),102.5)
        self.assertEqual(len(prescription(110,2.5)),9)


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        idx=pd.date_range("2026-09-01",periods=60)
        self.daily=pd.DataFrame({
            "calories":[2500.]*60,"meals":[4]*60,
            "source":["Health Connect"]*60},index=idx)
        self.garmin=pd.DataFrame({"calories_burned":[2450.]*60},index=idx)
        self.weight=pd.Series([145.]*60,index=idx,name="weight_lb")
        self.frame=display_energy_frame(
            self.daily,self.weight,self.garmin,idx[30],idx[-1])

    def test_energy_weight_grouped_into_two_axes(self):
        selected=["7-day logged calories","7-day Garmin expenditure",
                  "7-day body weight"]
        fig=interactive_energy_figure(self.frame,selected)
        self.assertEqual(len(fig.data),3)
        self.assertEqual(fig.data[-1].yaxis,"y2")
        self.assertEqual(fig.layout.yaxis.title.text,"kcal/day")
        self.assertEqual(fig.layout.yaxis2.title.text,"lb")
        self.assertEqual(fig.data[-1].name,"7-day body weight")

    def test_tdee_is_optional_and_legend_can_toggle(self):
        fig=interactive_energy_figure(self.frame,
            ["7-day logged calories","28-day weight-derived TDEE"])
        self.assertEqual(len(fig.data),2)
        self.assertTrue(np.isfinite(self.frame["weight_derived_tdee28"].iloc[-1]))
        self.assertEqual(fig.data[1].name,"28-day weight-derived TDEE")
        self.assertEqual(fig.layout.yaxis.title.text,"kcal/day")

    def test_single_weight_axis(self):
        fig=interactive_energy_figure(self.frame,["7-day body weight"])
        self.assertEqual(len(fig.data),1)
        self.assertEqual(fig.layout.yaxis.title.text,"lb")
        self.assertEqual(len(interactive_energy_figure(self.frame,[]).data),0)

    def test_missing_nutrition_does_not_make_zero(self):
        self.daily.loc[self.daily.index[-3:],"calories"]=np.nan
        f=display_energy_frame(self.daily,self.weight,self.garmin,
                              self.daily.index[-28],self.daily.index[-1])
        self.assertTrue(pd.isna(f["intake7"].iloc[-1]) or
                        f["intake7"].iloc[-1]>0)


if __name__=="__main__":
    unittest.main()
