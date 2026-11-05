"""Laboratory panel viewer; collection history is independent of daily filters."""
import pandas as pd
import streamlit as st
from labs import read_labs, range_status
from lab_comparison import comparison_frame, style_results, OUTSIDE


def render_comparison(frame, collections):
    ids = collections.index.tolist()
    label = lambda key: f'{collections.loc[key,"collected_on"]} · {collections.loc[key,"source"]}'
    a, b = st.columns(2)
    baseline = a.selectbox('Baseline collection', ids, index=1, format_func=label,
                          key='lab_baseline')
    candidates = [key for key in ids if key != baseline]
    comparison = b.selectbox('Comparison collection', candidates, format_func=label,
                            key='lab_comparison')
    st.caption(f'Baseline: {label(baseline)}. Comparison: {label(comparison)}. '
               'Change = comparison minus baseline; a positive or negative change does not by itself mean better or worse.')
    table = comparison_frame(frame, baseline, comparison)
    st.caption('Each side uses its own lab reference range. Matching units permit a numeric difference, '
               'but testing methods may differ. Missing tests are kept visible; text, intervals and inequalities have no numeric change.')
    outside_only = st.checkbox('Show only tests outside range in either collection', key='lab_comparison_outside')
    if outside_only:
        table = table[table['Baseline status'].isin(OUTSIDE) | table['Comparison status'].isin(OUTSIDE)]
    if table.empty:
        st.info('No results match this filter.')
    for name, panel in table.groupby('Panel', sort=False):
        with st.expander(name, expanded=True):
            display = panel.drop(columns='Panel').reset_index(drop=True)
            st.dataframe(style_results(display, [('Baseline result','Baseline status'),
                         ('Comparison result','Comparison status')]), hide_index=True, use_container_width=True)


def render_labs(db):
    st.subheader('Labs')
    st.caption('Collection history is independent of the dashboard date filters. '
               'Results are compared with the normal ranges supplied by the lab.')
    frame = read_labs(db)
    if frame.empty:
        st.info('No laboratory results recorded yet.')
        return
    collections = frame.drop_duplicates('collection_id').set_index('collection_id')
    st.caption('Colors: green = within lab range; red = above or below lab range; '
               'amber = boundary uncertain; gray = missing range, unassessed result or missing test. '
               'Colors describe the lab range comparison, not a diagnosis.')
    if len(collections) > 1:
        view = st.radio('Lab view', ['Compare collections','Collection details'], horizontal=True, key='lab_view')
        if view == 'Compare collections':
            render_comparison(frame, collections)
            return
    selected = st.selectbox('Collection', collections.index.tolist(),
        format_func=lambda key: f'{collections.loc[key,"collected_on"]} · {collections.loc[key,"source"]}',
        key='lab_collection')
    rows = frame[frame.collection_id == selected].copy()
    rows['status'] = [range_status(r.result_text, r.reference_text) for r in rows.itertuples()]
    first = rows.iloc[0]
    fasting = 'Yes' if first.fasting == 1 else 'No' if first.fasting == 0 else 'Not reported'
    st.caption(f'Collected: {first.collected_on} · Fasting: {fasting} · {first.performing_lab}')
    a, b, c = st.columns(3)
    a.metric('Panels', rows.panel_id.nunique())
    b.metric('Results', len(rows))
    c.metric('Outside lab range', rows.status.isin(['Above lab range', 'Below lab range']).sum())
    st.caption('Range status is calculated from the supplied result and lab range. '
               '“Boundary uncertain” preserves an inequality that crosses a range boundary. '
               'Blank source fields are not counted as results. “Not assessed” means '
               'a range comparison could not be determined from the supplied text.')
    abnormal_only = st.checkbox('Show only results outside the lab range', key='lab_abnormal_only')
    for _, panel in rows.groupby('panel_id', sort=False):
        first = panel.iloc[0]
        shown = panel[panel.status.isin(['Above lab range', 'Below lab range'])] if abnormal_only else panel
        if abnormal_only and shown.empty:
            continue
        with st.expander(first.panel_name, expanded=True):
            ordered = first.ordered_on if pd.notna(first.ordered_on) else 'Not reported'
            st.caption(f'Ordered: {ordered} · Resulted: {first.resulted_on}')
            table = shown[['test_name','result_text','units_display','reference_text','status']].copy()
            table.columns = ['Test','Result','Units','Lab normal range','Range status']
            st.dataframe(style_results(table.fillna(''), [('Result','Range status')]),
                         hide_index=True, use_container_width=True)
            notes = panel[['test_name','unit_note']].dropna().drop_duplicates()
            for note in notes.itertuples():
                st.caption(f'{note.test_name}: {note.unit_note}')
            if pd.notna(first.notes) and first.notes:
                st.caption(first.notes)
            with st.expander('Source text'):
                st.caption(first.provenance)
                st.text(first.source_text)
