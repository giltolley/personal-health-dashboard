"""Unit-specific decision charts. Unknown measurements stay as gaps."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dashboard_v08 import weight_smoothed
from overview_metrics import window, measured, usable_nutrition

TEAL='#548c77'
AMBER='#c69b46'
BLUE='#537da3'


def layout(fig, title, height=280):
    fig.update_layout(title=title,height=height,showlegend=False,
                      margin=dict(l=10,r=20,b=15,t=60),hovermode='x unified')
    return fig


def bp_figure(bp,end):
    frame=window(bp,end,28)
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.16,
                      subplot_titles=['Systolic','Diastolic'])
    dates=pd.date_range(end=pd.Timestamp(end),periods=28)
    for row,(field,reference) in enumerate([('systolic',130),('diastolic',80)],1):
        values=measured(frame,field)
        values=values[values.gt(0)].groupby(level=0).mean().reindex(dates)
        fig.add_trace(go.Scatter(x=dates,y=values,mode='lines+markers',connectgaps=False,
            name=field.title(),line_color=BLUE,
            hovertemplate='%{x|%b %d}: %{y:.0f} mmHg<extra></extra>'),row=row,col=1)
        fig.add_hline(y=reference,line_dash='dot',line_color=AMBER,
            annotation_text=f'{reference} mmHg · stage 1 boundary',row=row,col=1)
        fig.update_yaxes(title_text='mmHg',row=row,col=1)
    return layout(fig,'Blood pressure · daily averages · 28 days',350)


def activity_figure(report):
    fig=make_subplots(rows=2,cols=1,vertical_spacing=.42,
                      subplot_titles=['Aerobic activity · moderate-equivalent minutes',
                                      'Strength training · recorded days'])
    for row,(value,target,unit,coverage) in enumerate([
        (report['minutes'],150,'minutes',report['coverage']),
        (report['strength_days'],2,'days',7)],1):
        # Strength value means days logged in Hevy, not verified training exposure.
        if pd.notna(value):
            fig.add_trace(go.Bar(x=[value],y=['Recorded'],orientation='h',
                marker_color=TEAL if value>=target else BLUE,
                text=[f'{value:,.0f} / {target} {unit}'],textposition='auto',
                hovertemplate=f'%{{x:.0f}} {unit}<extra></extra>'),row=row,col=1)
        else:
            fig.add_annotation(text='No intensity-minute measurements',x=.02,y=.9,
                               xref='paper',yref='paper',showarrow=False)
        fig.add_vline(x=target,line_dash='dot',line_color=AMBER,
                      annotation_text=f'Reference: {target}',row=row,col=1)
        fig.update_xaxes(range=[0,max(target*1.3,value*1.15 if pd.notna(value) else 0)],
                         title_text=unit,row=row,col=1)
        fig.update_yaxes(showticklabels=False,row=row,col=1)
    return layout(fig,'Weekly activity · recorded progress',310)


def nutrient_figure(daily,end,field,label,target,direction,unit,goal_history=None):
    values=measured(usable_nutrition(daily,end),field)
    values=values[values.ge(0)].groupby(level=0).mean()
    dates=pd.date_range(end=pd.Timestamp(end),periods=7)
    values=values.reindex(dates)
    references=pd.Series(target,index=dates,dtype=float)
    if goal_history is not None and not goal_history.empty and field!='sodium_mg':
        from goals import targets_for_dates
        dated=targets_for_dates(goal_history,dates)
        references=dated.protein_g if field=='protein_g' else dated.calories*14/1000
    colors=[BLUE if pd.isna(ref) else TEAL if pd.notna(v) and
            (v>=ref if direction=='at least' else v<=ref) else AMBER
            for v,ref in zip(values,references)]
    fig=go.Figure(go.Bar(x=dates,y=values,marker_color=colors,
        hovertemplate=f'%{{x|%b %d}}: %{{y:,.1f}} {unit}<extra></extra>'))
    if goal_history is None:
        if pd.notna(target):
            fig.add_hline(y=target,line_dash='dot',line_color=BLUE,
                          annotation_text=f'{direction} {target:,.1f} {unit}')
    elif references.notna().any():
        fig.add_trace(go.Scatter(x=dates,y=references,mode='lines',connectgaps=False,
            line=dict(color=BLUE,dash='dot',shape='hv'),name=f'{direction} reference',
            hovertemplate=f'%{{x|%b %d}}: reference %{{y:.1f}} {unit}<extra></extra>'))
    fig.update_yaxes(title_text=unit,rangemode='tozero')
    fig.update_xaxes(tickformat='%b %d',dtick=86400000)
    return layout(fig,label+' · daily',260)


def lift_change_figure(lifts):
    if lifts.empty:
        return None
    valid=lifts.dropna(subset=['Median e1RM change (%)']).copy()
    if valid.empty:
        return None
    fig=go.Figure(go.Bar(x=valid['Median e1RM change (%)'],y=valid['Lift'],orientation='h',
        marker_color=[TEAL if v>2 else AMBER if v< -2 else BLUE
                      for v in valid['Median e1RM change (%)']],
        text=[f'{v:+.1f}%' for v in valid['Median e1RM change (%)']],textposition='auto',
        hovertemplate='%{y}: %{x:+.1f}%<extra></extra>'))
    fig.add_vline(x=0,line_color=BLUE)
    fig.update_xaxes(title_text='Change in median estimated 1RM (%)',zeroline=False)
    fig.update_yaxes(autorange='reversed')
    return layout(fig,'Lift performance · latest vs prior 28 days',300)


def training_weight_figure(weight,end):
    dates=pd.date_range(end=pd.Timestamp(end),periods=28)
    values=weight_smoothed(weight,end).reindex(dates)
    if not values.notna().any():
        return None
    fig=go.Figure(go.Scatter(x=dates,y=values,mode='lines',connectgaps=False,
        line=dict(color=BLUE,width=3),
        hovertemplate='%{x|%b %d}: %{y:.1f} lb<extra></extra>'))
    fig.update_yaxes(title_text='Weight (lb)')
    return layout(fig,'Body weight · 7-day average',300)
