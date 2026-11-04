"""Goal history display and explicitly saved changes; hosted editing is owner-gated."""
import hmac
import os
from datetime import timedelta
import pandas as pd
import streamlit as st
from goals import PHASES,save_goal


def editor_allowed(hosted,configured,entered):
    return not hosted or bool(configured and entered and hmac.compare_digest(configured.encode(),entered.encode()))


def goal_editor(db,history,today,calories,protein,hosted):
    with st.expander('Saved goals and phase history'):
        if history.empty:
            st.info('No saved goal history yet. Displayed defaults are temporary until you save a goal.')
        else:
            display=history[['effective_date','known_before_date','phase','calories','protein_g','recorded_at']].copy()
            display['effective_date']=display.effective_date.fillna('Start unknown')
            st.dataframe(display,hide_index=True,use_container_width=True)
        st.caption('A new entry takes effect on its date. Changes for the same date preserve prior revisions. '
                   'An entry with an unknown start is retained as context, not extended across earlier charts.')
        secret=os.environ.get('GOAL_EDIT_TOKEN','')
        entered=st.text_input('Goal editor password',type='password',key='goal_editor_password') if hosted and secret else ''
        if not editor_allowed(hosted,secret,entered):
            st.info('Goal history is read-only. To enable owner editing, configure GOAL_EDIT_TOKEN in private app settings and enter it here.')
            return
        with st.form('save_dated_goal'):
            effective=st.date_input('Effective date',value=today,max_value=today+timedelta(days=365),key='goal_effective_date')
            phase=st.selectbox('Diet phase',PHASES,index=PHASES.index('Muscle gain'),key='goal_phase')
            kcal=st.number_input('Saved calorie target (kcal/day)',min_value=500,max_value=10000,
                                 value=int(calories),step=25,key='goal_calories')
            has_protein=st.checkbox('Record a protein reference for this date',value=pd.notna(protein))
            grams=st.number_input('Saved protein reference (g/day)',min_value=0,max_value=500,
                                  value=int(protein) if pd.notna(protein) else 160,step=5,key='goal_protein')
            submit=st.form_submit_button('Save dated goal')
        if submit:
            try:
                save_goal(db,effective,phase,kcal,grams if has_protein else None)
                st.rerun()
            except ValueError as ex:
                st.error(str(ex))
