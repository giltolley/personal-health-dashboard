"""Laboratory panel viewer; collection history is independent of daily filters."""
import pandas as pd
import streamlit as st
from labs import read_labs, range_status


def render_labs(db):
    st.subheader('Labs')
    st.caption('Collection history is independent of the dashboard date filters. '
               'Results are compared with the normal ranges supplied by the lab.')
    frame = read_labs(db)
    if frame.empty:
        st.info('No laboratory results recorded yet.')
        return
    collections = frame.drop_duplicates('collection_id').set_index('collection_id')
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
            st.caption(f'Ordered: {first.ordered_on} · Resulted: {first.resulted_on}')
            table = shown[['test_name','result_text','units_display','reference_text','status']].copy()
            table.columns = ['Test','Result','Units','Lab normal range','Range status']
            st.dataframe(table.fillna(''), hide_index=True, use_container_width=True)
            notes = panel[['test_name','unit_note']].dropna().drop_duplicates()
            for note in notes.itertuples():
                st.caption(f'{note.test_name}: {note.unit_note}')
            if pd.notna(first.notes) and first.notes:
                st.caption(first.notes)
            with st.expander('Source text'):
                st.caption(first.provenance)
                st.text(first.source_text)
