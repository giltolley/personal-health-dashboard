"""Five questions for the Overview; deeper charts remain on their existing tabs."""
from datetime import timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dashboard_v08 import fmt
from overview_charts import (bp_figure, activity_figure, nutrient_figure,
                             lift_change_figure, training_weight_figure)
from overview_metrics import (window, bp_summary, cardio_summary, sleep_summary,
                              nutrition_summary, training_summary)


def decision(text):
    st.write('**Next step:** '+text)


def render_overview(daily, weight, garmin, bp, workouts, sets, end, calorie_goal, goal_history=None):
    protein_goal=160
    goal_context=None
    if goal_history is not None and not goal_history.empty:
        from goals import goal_at,window_context
        selected_goal=goal_at(goal_history,end)
        calorie_goal=selected_goal.calories
        protein_goal=selected_goal.protein_g
        goal_context=window_context(goal_history,end)
    st.caption(f'Reviewing completed days through {end:%b %d, %Y}. '
               'Weekly cards use the last 7 calendar days; training uses 28-day windows. '
               'Earlier chart start dates do not change these windows.')

    with st.container(border=True):
        st.subheader('1. Blood Pressure')
        st.caption('Question: Is my measured blood pressure consistently elevated?')
        report=bp_summary(bp,end)
        a,b,c=st.columns(3)
        a.metric('Systolic · daily-average mean',fmt(report['systolic'])+' mmHg')
        b.metric('Diastolic · daily-average mean',fmt(report['diastolic'])+' mmHg')
        c.metric('Days with paired readings',f'{report["days"]}/7')
        st.write('**'+report['category']+'**')
        decision(report['action'])
        st.caption('Averages weight each measured day equally. Three days is a dashboard '
                   'display minimum, not a diagnostic protocol. Use two readings one minute '
                   'apart after five minutes seated rest. Daily averages can hide individual highs. '
                   'Medication timing and morning/evening readings are not available in this import.')
        history=window(bp,end,28)
        if not history.empty and {'systolic','diastolic'}.issubset(history):
            st.plotly_chart(bp_figure(bp,end),use_container_width=True)
            st.caption('Reference lines apply separately: either component may be elevated. Missing dates remain gaps.')
            with st.expander('Recent blood-pressure readings'):
                st.dataframe(history.sort_index(ascending=False),use_container_width=True)
        elif not bp.empty:
            st.caption('Latest imported BP date: '+str(pd.Timestamp(bp.index.max()).date())+
                       '. No recent measurement is carried forward.')
        st.markdown('[Measurement and BP categories · American Heart Association](https://www.heart.org/en/health-topics/high-blood-pressure/understanding-blood-pressure-readings/monitoring-your-blood-pressure-at-home)')

    with st.container(border=True):
        st.subheader('2. Cardiovascular Health')
        st.caption('Question: Am I getting enough aerobic activity and maintaining everyday movement?')
        report=cardio_summary(garmin,workouts,end)
        a,b,c,d=st.columns(4)
        a.metric('Aerobic minutes · recorded',fmt(report['minutes']))
        b.metric('Strength-training days',str(report['strength_days']))
        c.metric('Steps · daily average',fmt(report['steps']['mean']))
        d.metric('Resting heart rate · average',fmt(report['rhr']['mean'])+' bpm')
        st.plotly_chart(activity_figure(report),use_container_width=True)
        if pd.isna(report['minutes']):
            decision('No recent intensity-minute values. Check Garmin coverage; activity duration alone does not establish aerobic intensity.')
        elif report['remaining']>0:
            decision(f'{report["remaining"]:,.0f} moderate-equivalent minutes remain to reach 150 in this rolling week. '
                     'Add manageable brisk walks or other aerobic activity; missing records may understate the total.')
        else:
            decision('At least 150 moderate-equivalent minutes recorded. Maintain a sustainable routine.')
        if report['strength_days']<2:
            st.write('Strength frequency: fewer than two recorded days. Plan sessions that cover all major muscle groups.')
        st.caption(f'Intensity-minute coverage: {report["coverage"]}/7 days · '
                   f'Steps: {report["steps"]["days"]}/7 · Resting HR: {report["rhr"]["days"]}/7. '
                   'Garmin already counts vigorous minutes twice; activities are not added again. '
                   'Hevy days indicate attendance, not confirmed full-body coverage.')
        if report['prior_steps']['days']>=5 and report['steps']['days']>=5:
            st.caption('Steps vs previous 7 days: '+fmt(report['steps']['mean']-report['prior_steps']['mean'])+
                       '/day. Use your own baseline; no universal 10,000-step requirement.')
        st.caption('Resting HR provides context, not a cardiovascular diagnosis. Lipid results can be added when available.')
        st.markdown('[Adult activity recommendations · CDC](https://www.cdc.gov/physical-activity-basics/guidelines/adults.html)')

    with st.container(border=True):
        st.subheader('3. Sleep Quality')
        st.caption('Question: Am I meeting my personal minimum, and do I feel rested?')
        report=sleep_summary(garmin,end)
        a,b,c=st.columns(3)
        a.metric('Sleep · recorded-night average',fmt(report['mean'],1)+' h')
        b.metric('Nights under 6 hours',str(report['below']) if report['days'] else '—')
        c.metric('Nights at least 7 hours',str(report['recommended']) if report['days'] else '—')
        decision(report['action'])
        st.caption(f'{report["days"]}/7 nights recorded. Six hours is your personal alert threshold; '
                   'the adult duration recommendation remains 7+ hours. Duration alone does not measure '
                   'sleep quality. Consider daytime fatigue; persistent sleepiness deserves clinical review.')
        values=report['values']
        if len(values):
            fig=go.Figure(go.Bar(x=values.index,y=values,
                marker_color=['#dc6b61' if x<6 else '#c69b46' if x<7 else '#548c77' for x in values],
                hovertemplate='%{x|%b %d}: %{y:.1f} hours<extra></extra>'))
            fig.add_hline(y=6,line_dash='dash',annotation_text='Personal minimum · 6 h')
            fig.add_hline(y=7,line_dash='dot',annotation_text='General recommendation · 7 h')
            fig.update_layout(height=260,showlegend=False,yaxis_title='Hours',
                              margin=dict(l=5,r=5,b=5,t=25))
            st.plotly_chart(fig,use_container_width=True)
        st.markdown('[Adult sleep duration · AASM consensus](https://pmc.ncbi.nlm.nih.gov/articles/PMC4434546/)')

    with st.container(border=True):
        st.subheader('4. Dietary Analysis')
        st.caption('Question: Which recurring dietary gap should I address?')
        table,days=nutrition_summary(daily,end,calorie_goal,protein_goal,goal_history)
        st.write('**Target on selected end date: '+fmt(calorie_goal)+' kcal/day** · edit saved goals in the sidebar.')
        columns=st.columns(3)
        for column,(field,label,target,direction,unit) in zip(columns,[
            ('protein_g','Protein',protein_goal,'at least','g'),
            ('fiber_g','Fiber',14*calorie_goal/1000,'at least','g'),
            ('sodium_mg','Sodium',2300,'at most','mg')]):
            with column:
                if int(table.set_index('Nutrient').loc[label,'Days with values']):
                    st.plotly_chart(nutrient_figure(daily,end,field,label,target,direction,unit,goal_history),
                                    use_container_width=True)
                else:
                    st.info(f'{label}: no usable values in the last 7 days.')
        st.caption('Teal bars meet the displayed reference; amber bars fall outside it. '
                   'Missing or incomplete days remain blank. Sodium uses an upper reference; '
                   'protein and fiber use lower references. Blue bars have no dated reference. '
                   'Dotted lines follow the goal saved for each date.')
        st.dataframe(table.style.format({'Average':'{:,.1f}'},na_rep='—'),
                     hide_index=True,use_container_width=True)
        messages=[]
        for _,row in table.iterrows():
            if row['Days with reference']>=5 and row['Days meeting reference']<row['Days with reference']/2:
                messages.append({'Fiber':'Add a regular fiber source such as oats, beans, fruit or vegetables.',
                    'Protein':'Review protein portions or add a convenient protein source.',
                    'Sodium':'Review recurring high-sodium foods, particularly if BP is elevated.'}[row['Nutrient']])
        decision(' '.join(messages) if messages else
                 'Maintain current habits where references are met; collect more complete records for uncertain nutrients.')
        st.caption(f'{days}/7 days pass the existing logging proxy (positive calories and 3+ meal records). '
                   'This is not proof of full logging. Each nutrient has its own coverage. '
                   'Any NULL meal nutrient makes that day unknown; numeric zeros supplied by a food entry '
                   'cannot be distinguished from omitted nutrient information. Food-entry quality still matters.')
        st.caption(f'Fiber reference: 14 g/1,000 kcal × {fmt(calorie_goal)}-kcal target on the selected end date. '
                   'Protein uses its saved dated reference, not a medical minimum. '
                   'Sodium reference: 2,300 mg/day; individual targets may differ. '
                   'These are intake references, not conclusions from blood electrolyte levels.')
        st.markdown('[Fiber reference · NIH](https://www.niddk.nih.gov/health-information/digestive-diseases/hemorrhoids/eating-diet-nutrition) · '
                    '[DASH dietary guidance · NIH](https://www.nhlbi.nih.gov/health/dash-eating-plan)')

    with st.container(border=True):
        st.subheader('5. Intake vs. Training Heuristics')
        phase=goal_context['target'].phase if goal_context else 'Muscle gain'
        st.caption('Question: Is intake supporting the selected phase? Phase: '+
                   (phase if pd.notna(phase) else 'Unknown'))
        energy,lifts,action=training_summary(daily,weight,garmin,sets,end)
        a,b,c=st.columns(3)
        a.metric('Logged intake · 28-day average',fmt(energy['average_intake'])+' kcal')
        b.metric('Weight trend · 28 days',fmt(energy['trend_lb_week'],2)+' lb/week' if energy['valid'] else '—')
        c.metric('Target on selected end date',fmt(calorie_goal)+' kcal')
        if goal_context and goal_context['mixed']:
            action=('This 28-day window spans goal changes. Only '
                    f'{goal_context["days_on_target"]} completed days use the target on the selected end date. '
                    'Allow several weeks on the new target before changing calories based on this comparison.')
        elif goal_context and (pd.isna(phase) or phase!='Muscle gain'):
            action=('This period is not recorded as muscle gain. Review the weight trend against '
                    'your intended phase; muscle-gain calorie suggestions are withheld.')
        decision(action)
        st.caption(f'28-day intake coverage: {energy["intake_days"]}/28 · Weight: {energy["weight_days"]}/28. '
                   'Lift comparisons use median eligible estimated 1RM in the latest 28 days '
                   'versus the preceding 28 days, with at least two sessions per lift in each window.')
        weight_plot=training_weight_figure(weight,end)
        lift_plot=lift_change_figure(lifts)
        weight_column,lift_column=st.columns(2)
        with weight_column:
            if weight_plot is not None:
                st.plotly_chart(weight_plot,use_container_width=True)
            else:
                st.info('Not enough recent weigh-ins for a smoothed weight chart.')
        with lift_column:
            if lift_plot is not None:
                st.plotly_chart(lift_plot,use_container_width=True)
            else:
                st.info('Lift comparison needs at least two eligible sessions in each 28-day window.')
        if not lifts.empty:
            st.dataframe(lifts.style.format({'Median e1RM change (%)':'{:+.1f}'},na_rep='—'),
                         hide_index=True,use_container_width=True)
        st.caption('Coaching heuristics, not validated medical thresholds: changes over 2% indicate '
                   'possible performance improvement; weight trends below −0.1 or above +0.5 lb/week '
                   'prompt review, not an automatic calorie adjustment. Suggestions require adequate '
                   'records in both windows and two comparable lifts. Technique, effort, rep ranges, '
                   'illness and recent changes in calories can confound these comparisons. '
                   'After changing calorie intake, allow several weeks before judging the new target. '
                   'Optional waist measurements every 2–4 weeks can add context; they are not required. '
                   'No precise muscle/fat split or daily surplus is inferred.')
        st.caption('Use Energy & Nutrition for calorie, weight and TDEE charts; Training for individual lifts. '
                   'Targets follow saved effective dates; unknown starting dates are not extrapolated.')
