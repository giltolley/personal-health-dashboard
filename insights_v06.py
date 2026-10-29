"""Version 0.6 analytical views for the Personal Health Dashboard.

Pure analysis helpers are intentionally separate from Streamlit presentation.
All estimates are exploratory; wearable expenditure is not measured TDEE.
"""
from __future__ import annotations

from datetime import date, timedelta
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

LB_PER_KG = 2.20462262185
KCAL_PER_LB_APPROX = 3500.0  # Short-window heuristic, not a physiological constant.


def _series(frame, column):
    if frame is None or frame.empty or column not in frame:
        return pd.Series(dtype="float64")
    data = pd.to_numeric(frame[column], errors="coerce")
    data.index = pd.to_datetime(data.index).normalize()
    return data.groupby(level=0).mean().sort_index()


def _slope_per_day(weights):
    """OLS trend in lb/day, using actual calendar-day spacing."""
    weights = weights.dropna().sort_index()
    if len(weights) < 2:
        return float("nan")
    x = (weights.index - weights.index[0]).days.to_numpy(dtype=float)
    y = weights.to_numpy(dtype=float)
    if np.ptp(x) < 1:
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])


def energy_window(daily, weight, garmin, end_date, window_days=28, min_meals=3):
    """Complete-day comparison without filling missing nutrition with zero."""
    end_date = pd.Timestamp(end_date).normalize()
    dates = pd.date_range(end=end_date, periods=window_days, freq="D")
    result = pd.DataFrame(index=dates)
    for target, source, col in [
        ("intake", daily, "calories"),
        ("meals", daily, "meals"),
        ("protein_g", daily, "protein_g"),
        ("garmin_tdee", garmin, "calories_burned"),
    ]:
        result[target] = _series(source, col).reindex(dates)
    weights = weight if isinstance(weight, pd.Series) else (
        weight["weight_lb"] if isinstance(weight, pd.DataFrame) and "weight_lb" in weight else pd.Series(dtype=float)
    )
    weights = pd.to_numeric(weights, errors="coerce")
    weights.index = pd.to_datetime(weights.index).normalize()
    result["weight_lb"] = weights.groupby(level=0).median().reindex(dates)
    result["complete_intake"] = result["intake"].gt(0) & result["meals"].ge(min_meals)
    result["usable_intake"] = result["intake"].where(result["complete_intake"])
    return result


def estimate_tdee(window):
    """Return bounded evidence and a trend-derived heuristic, or an insufficient-data reason."""
    n = len(window)
    valid_intake = window["usable_intake"].dropna()
    valid_weight = window["weight_lb"].dropna()
    coverage = len(valid_intake) / n if n else 0
    result = {
        "days": n, "intake_days": len(valid_intake), "weight_days": len(valid_weight),
        "coverage": coverage,
        "average_intake": float(valid_intake.mean()) if len(valid_intake) else float("nan"),
        "garmin_average": float(window["garmin_tdee"].mean()) if window["garmin_tdee"].notna().any() else float("nan"),
        "trend_lb_week": float("nan"), "estimated_tdee": float("nan"),
        "valid": False,
    }
    if n < 14 or coverage < 0.8 or len(valid_weight) < max(10, int(n * 0.7)):
        return result
    slope = _slope_per_day(valid_weight)
    result["trend_lb_week"] = slope * 7
    result["estimated_tdee"] = result["average_intake"] - slope * KCAL_PER_LB_APPROX
    result["valid"] = True
    return result


def nutrition_daily(daily, start, end, min_meals=3):
    dates = pd.date_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq="D")
    cols = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg", "potassium_mg", "meals"]
    frame = pd.DataFrame(index=dates)
    for col in cols:
        frame[col] = _series(daily, col).reindex(dates)
    frame["complete"] = frame["calories"].gt(0) & frame["meals"].ge(min_meals)
    frame["macro_calories"] = 4 * frame["protein_g"] + 4 * frame["carbs_g"] + 9 * frame["fat_g"]
    frame["macro_gap_pct"] = (frame["macro_calories"] - frame["calories"]).abs() / frame["calories"].replace(0, np.nan) * 100
    return frame


def training_by_week(sets, workouts, start, end):
    """Workout volume counts are sets, not muscle stimulation equivalences."""
    if sets is None or sets.empty:
        return pd.DataFrame()
    data = sets.copy()
    data["local_date"] = pd.to_datetime(data["local_date"], errors="coerce")
    data = data[data["local_date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    data = data[data["working_set"].fillna(False)].copy()
    if data.empty:
        return data
    names = data["exercise"].fillna("").str.lower()
    classification = [
        (r"bench|chest|fly|push.up", "Chest"),
        (r"deadlift|row|pulldown|pull.up|chin.up|back extension", "Back / hinge"),
        (r"squat|leg press|leg curl|leg extension|lunge|calf", "Legs"),
        (r"overhead|shoulder|lateral|face pull|reverse fly|rear delt", "Shoulders"),
        (r"bicep|curl", "Biceps"),
        (r"tricep|pushdown|skullcrush", "Triceps"),
        (r"crunch|ab|plank|knee raise|leg raise|russian twist", "Core"),
    ]
    data["group"] = "Unmapped"
    for pattern, label in classification:
        matches = names.str.contains(pattern, regex=True, na=False) & data["group"].eq("Unmapped")
        data.loc[matches, "group"] = label
    data["week"] = data["local_date"].dt.to_period("W-SUN").dt.start_time
    return data


def source_freshness(log, now=None):
    """Track last successful ingestion, distinct from latest measurement date."""
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    now = pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    rules = [("Garmin API", 12), ("Hevy API", 36), ("Health Connect Drive", 48)]
    result = []
    for source, threshold in rules:
        subset = log[log["source"].eq(source) & log["status"].eq("ok")].copy() if log is not None and not log.empty else pd.DataFrame()
        if subset.empty:
            result.append({"Source": source, "Last success (UTC)": "—", "Hours since": np.nan, "Alert after (h)": threshold, "Status": "Unknown"})
            continue
        parsed = pd.to_datetime(subset["started_at"], utc=True, errors="coerce").dropna()
        if parsed.empty:
            result.append({"Source": source, "Last success (UTC)": "—", "Hours since": np.nan, "Alert after (h)": threshold, "Status": "Unknown"})
            continue
        last = parsed.max()
        age = max(0.0, (now - last).total_seconds() / 3600)
        result.append({"Source": source, "Last success (UTC)": last.strftime("%Y-%m-%d %H:%M"),
                       "Hours since": round(age, 1), "Alert after (h)": threshold,
                       "Status": "Stale" if age > threshold else "Recent"})
    return pd.DataFrame(result)


def _fmt(value, precision=0):
    return f"{value:,.{precision}f}" if pd.notna(value) else "—"


def render_insights(daily, weight, garmin, hevy_sets, hevy_workouts, log, start, end, today):
    """Add focused decision-support panels without altering the established pages."""
    st.subheader("Insights · v0.6")
    st.caption("Exploratory comparisons across logged nutrition, Renpho, Garmin and Hevy. No data is modified.")
    energy_tab, strength_tab, recovery_tab, food_tab, quality_tab = st.tabs(
        ["Energy balance", "Strength", "Recovery", "Nutrition quality", "Sync health"]
    )

    with energy_tab:
        st.markdown("#### Weight-derived maintenance estimate")
        phase_default = max(start, min(end, date(2026, 10, 7)))
        phase_start = st.date_input("Phase start", value=phase_default, min_value=start, max_value=end, key="insight_phase")
        min_meals = st.number_input("Minimum logged meal records for a usable day", min_value=1, max_value=8, value=3,
                                    help="A heuristic for likely complete logs, not proof of complete logging.", key="insight_meals")
        cutoff = min(pd.Timestamp(end), pd.Timestamp(today) - pd.Timedelta(days=1))
        if cutoff < pd.Timestamp(phase_start):
            st.info("Choose a completed date range for this analysis.")
        else:
            phase_days = (cutoff - pd.Timestamp(phase_start)).days + 1
            full = energy_window(daily, weight, garmin, cutoff, phase_days, min_meals)
            valid = full["usable_intake"].dropna()
            wts = full["weight_lb"].dropna()
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Average logged intake", _fmt(valid.mean()) + " kcal")
            k2.metric("Weight, most recent", _fmt(wts.iloc[-1] if len(wts) else np.nan, 1) + " lb")
            k3.metric("Garmin mean expenditure", _fmt(full["garmin_tdee"].mean()) + " kcal")
            k4.metric("Usable nutrition days", f"{len(valid)}/{phase_days}")
            if len(valid) < phase_days:
                st.warning(f"{phase_days-len(valid)} dates are excluded for missing or potentially incomplete nutrition. Missing is never counted as zero.")
            st.caption("A weight regression estimates energy balance using an approximate 3,500 kcal/lb conversion. "
                       "Water, glycogen, digestion, changes in training and logging errors can materially affect short windows.")
            rows = []
            for length in (14, 21, 28, 42):
                if phase_days < length:
                    continue
                metrics = estimate_tdee(energy_window(daily, weight, garmin, cutoff, length, min_meals))
                rows.append({"Window": f"{length} days", "Intake days": metrics["intake_days"],
                             "Weight days": metrics["weight_days"], "Logged kcal/day": round(metrics["average_intake"]) if pd.notna(metrics["average_intake"]) else np.nan,
                             "Trend lb/week": round(metrics["trend_lb_week"], 2) if metrics["valid"] else np.nan,
                             "Weight-derived TDEE": round(metrics["estimated_tdee"]) if metrics["valid"] else np.nan,
                             "Garmin kcal/day": round(metrics["garmin_average"]) if pd.notna(metrics["garmin_average"]) else np.nan,
                             "Status": "Exploratory" if metrics["valid"] else "Insufficient coverage"})
            if rows:
                report = pd.DataFrame(rows)
                st.dataframe(report, use_container_width=True, hide_index=True)
                estimates = report["Weight-derived TDEE"].dropna()
                if len(estimates):
                    st.info("Short-window estimates span " + _fmt(estimates.min()) + "–" +
                            _fmt(estimates.max()) + " kcal/day. Treat this as sensitivity across windows, not a confidence interval.")
            else:
                st.info("At least 14 completed days within this phase are needed for a weight-derived estimate.")
            plot = full[["weight_lb"]].copy()
            plot["7-day weight average"] = plot["weight_lb"].rolling(7, min_periods=4).mean()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=plot.index, y=plot["weight_lb"], name="Daily weight", mode="markers+lines", opacity=0.45))
            fig.add_trace(go.Scatter(x=plot.index, y=plot["7-day weight average"], name="7-day average", mode="lines"))
            fig.update_layout(title="Weight and rolling average", xaxis_title="Date", yaxis_title="lb")
            st.plotly_chart(fig, use_container_width=True)
            kcal_plot = full[["usable_intake", "garmin_tdee"]].rename(columns={"usable_intake":"Logged calories", "garmin_tdee":"Garmin expenditure"})
            st.plotly_chart(px.line(kcal_plot, labels={"value":"kcal", "index":"Date", "variable":"Metric"}, title="Logged intake versus wearable expenditure"), use_container_width=True)

    with strength_tab:
        st.markdown("#### Strength progression and volume")
        sets = training_by_week(hevy_sets, hevy_workouts, start, end)
        if sets.empty:
            st.info("No eligible Hevy working sets in this period.")
        else:
            st.metric("Working sets in selected period", str(len(sets)))
            weekly = sets.groupby(["week", "group"]).size().reset_index(name="sets")
            st.plotly_chart(px.bar(weekly, x="week", y="sets", color="group", title="Primary-pattern sets per week",
                                   labels={"week":"Week beginning", "sets":"Recorded working sets", "group":"Pattern"}),
                            use_container_width=True)
            st.caption("Each set is assigned to one approximate movement category; compound sets are not split between muscles. "
                       "Warmups excluded, normal/failure/drop sets included. Categories are heuristic.")
            exercises = sorted(sets["exercise"].dropna().unique())
            preferred = next((x for x in exercises if "Bench Press (Barbell)" in x), exercises[0])
            exercise = st.selectbox("Progression exercise", exercises, index=exercises.index(preferred), key="insights_exercise")
            selected = sets[sets["exercise"].eq(exercise)].copy()
            selected["estimated_1rm_lb"] = pd.to_numeric(selected["estimated_1rm_lb"], errors="coerce")
            strength = selected.groupby("local_date", as_index=False).agg(
                estimated_1rm_lb=("estimated_1rm_lb", "max"),
                working_sets=("exercise", "size"),
                top_weight_lb=("weight_lb", "max"),
                volume_lb=("load_volume_lb", "sum"),
            )
            if strength["estimated_1rm_lb"].notna().any():
                st.plotly_chart(px.line(strength, x="local_date", y="estimated_1rm_lb", markers=True,
                                         title=f"{exercise}: best eligible set e1RM",
                                         labels={"local_date":"Date", "estimated_1rm_lb":"Estimated 1RM (lb)"}), use_container_width=True)
            st.dataframe(strength.sort_values("local_date", ascending=False), hide_index=True, use_container_width=True)
            st.caption("Epley 1RM estimates are limited to weighted working sets of 1–10 reps. "
                       "Trends are more informative than one estimated maximum; exercise variants remain separate.")

    with recovery_tab:
        st.markdown("#### Recovery signals")
        if garmin.empty:
            st.info("No Garmin recovery data in this period.")
        else:
            g = garmin.loc[str(start):str(end)].copy()
            columns = [c for c in ("sleep_hours", "hrv_ms", "resting_hr") if c in g]
            if not columns or g.empty:
                st.info("No recovery measurements in the selected period.")
            else:
                for col, label, unit in [("sleep_hours", "Sleep", "hours"), ("hrv_ms", "Overnight HRV", "ms"), ("resting_hr", "Resting heart rate", "bpm")]:
                    if col not in g or g[col].dropna().empty:
                        continue
                    display = pd.to_numeric(g[col], errors="coerce")
                    chart = pd.DataFrame({"Daily":display, "7-day average":display.rolling("7D", min_periods=3).mean()})
                    st.plotly_chart(px.line(chart, title=f"{label}: daily and 7-day average",
                                             labels={"index":"Date","value":unit,"variable":"Series"}), use_container_width=True)
                if hevy_workouts is not None and not hevy_workouts.empty:
                    workout_days = set(pd.to_datetime(hevy_workouts.index).normalize())
                    compare = g[[c for c in ("sleep_hours","hrv_ms","resting_hr") if c in g]].copy()
                    compare["Hevy workout logged"] = ["Workout day" if d.normalize() in workout_days else "Other day" for d in compare.index]
                    grouped = compare.groupby("Hevy workout logged").agg(["mean","count"])
                    st.markdown("**Same-day measurements grouped by recorded training**")
                    st.dataframe(grouped, use_container_width=True)
                    st.caption("This is descriptive, not an estimate of training effects. Some recovery measurements "
                               "precede the workout and groups may differ in day of week, illness, and activity.")
                st.caption("HRV and resting HR should be interpreted relative to your own longer-term baseline; "
                           "there is no clinical readiness score or diagnosis here.")

    with food_tab:
        st.markdown("#### Nutrition quality and logging coverage")
        min_meal_count = st.number_input("Minimum meal records per day", min_value=1, max_value=8, value=3, key="food_min_meals")
        food = nutrition_daily(daily, start, min(end, today - timedelta(days=1)), min_meal_count) if start <= min(end, today - timedelta(days=1)) else pd.DataFrame()
        if food.empty:
            st.info("No completed days to analyze.")
        else:
            usable = food[food["complete"]]
            prot_target = st.number_input("Daily protein goal (g)", min_value=0, max_value=300, value=160, step=5)
            fiber_target = st.number_input("Daily fiber goal (g)", min_value=0, max_value=70, value=30, step=5)
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Logged days", f"{len(usable)}/{len(food)}")
            c2.metric("Average protein", _fmt(usable["protein_g"].mean(),1)+" g")
            c3.metric("Average fiber", _fmt(usable["fiber_g"].mean(),1)+" g")
            c4.metric("Average potassium", _fmt(usable["potassium_mg"].mean())+" mg")
            if len(usable):
                st.caption(f"At least {prot_target} g protein on {int((usable['protein_g'] >= prot_target).sum())}/{len(usable)} logged days; "
                           f"at least {fiber_target} g fiber on {int((usable['fiber_g'] >= fiber_target).sum())}/{len(usable)} days.")
            weekly = usable.resample("W-SUN")[["calories","protein_g","fat_g","carbs_g","fiber_g","sodium_mg","potassium_mg"]].mean()
            st.markdown("**Weekly averages (logged days only)**")
            st.dataframe(weekly.round(1), use_container_width=True)
            anomalies = usable[usable["macro_gap_pct"].gt(25)]
            missing = food[~food["complete"]]
            if len(missing):
                st.warning(f"{len(missing)} dates have no intake or fewer than {min_meal_count} recorded meals; they are excluded from nutrition averages.")
            if len(anomalies):
                st.warning(f"{len(anomalies)} days have a greater than 25% gap between calories and the 4/4/9 macro estimate. "
                           "This can reflect alcohol, fiber conventions, inaccurate food entries or synchronization problems.")
            st.caption("Meal counts are a rough completeness proxy. Sodium and potassium are only as reliable "
                       "as their source food entries. These are personalized tracking goals, not medical thresholds.")

    with quality_tab:
        st.markdown("#### Automated synchronization and data quality")
        freshness = source_freshness(log)
        st.dataframe(freshness, use_container_width=True, hide_index=True)
        if freshness["Status"].eq("Stale").any():
            st.warning("One or more scheduled sources have not reported a successful import within the monitoring threshold.")
        st.caption("A successful import can contain unchanged historical measurements. Source freshness and measurement freshness are different.")
        if log is not None and not log.empty:
            recent = log.sort_values("run_id", ascending=False).head(20)
            st.dataframe(recent[[c for c in ("started_at","source","dataset","record_count","status","error_type") if c in recent]],
                         use_container_width=True, hide_index=True)
        st.caption("Expected maximum age: Garmin 12 hours, Hevy 36 hours, Health Connect 48 hours. "
                   "Scheduled GitHub Actions may run late. Check their logs when stale.")
