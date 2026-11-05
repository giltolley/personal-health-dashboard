"""Synthetic lab range, presentation and recovery checks; no personal records."""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from labs import SCHEMA, ensure_labs, read_labs, range_status
from lab_comparison import comparison_frame, style_results
from backup_data import (NUTRITION_SCHEMA, GARMIN_SCHEMA, HEVY_SCHEMA, GOAL_SCHEMA,
                         snapshot_from_connection, restore_sqlite, validate)


def add_sample(db):
    db.execute("INSERT INTO lab_collections VALUES ('demo','2025-02-03','Synthetic clinic','Demo lab',1,'Synthetic fixture')")
    db.execute("INSERT INTO lab_panels VALUES ('demo-panel','demo','Demo panel','2025-02-01','2025-02-04','Empty| | |\nMarker|>=4|units|1-4','Sample note')")
    rows=[('marker','Marker','>=4',4,'>=','units','units',None,'1-4',None,0),
          ('text','Text result','Negative',None,None,None,None,None,'Negative',None,1),
          ('high','High marker','7',7,'=',None,None,None,'1-4',None,2)]
    db.executemany('INSERT INTO lab_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   [('demo-panel',)+r for r in rows])
    db.commit()


def add_older_sample(db):
    db.execute("INSERT INTO lab_collections VALUES ('older','2024-02-03','Older synthetic clinic','Demo lab',1,'Synthetic fixture')")
    db.execute("INSERT INTO lab_panels VALUES ('older-panel','older','Demo panel',NULL,'2024-02-04','Synthetic old results',NULL)")
    rows=[('marker','Marker','4',4,'=','units','units',None,'0-10',None,0),
          ('text','Text result','Negative',None,None,None,None,None,'Negative',None,1),
          ('high','High marker','5',5,'=',None,None,None,'1-6',None,2),
          ('old_only','Older-only result','12',12,'=','mg/dL','mg/dL',None,'1-20',None,3)]
    db.executemany('INSERT INTO lab_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   [('older-panel',)+r for r in rows])
    db.commit()


class LabTests(unittest.TestCase):
    def test_comparison_uses_each_range_and_keeps_unmatched_and_qualified_results(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        ensure_labs(db)
        add_sample(db)
        add_older_sample(db)
        frame=read_labs(db)
        table=comparison_frame(frame,'older','demo').set_index('Test')
        high=table.loc['High marker']
        self.assertEqual(high['Change'],'+2')
        self.assertEqual(high['Baseline status'],'Within lab range')
        self.assertEqual(high['Comparison status'],'Above lab range')
        self.assertEqual(table.loc['Marker','Comparison status'],'Boundary uncertain')
        self.assertEqual(table.loc['Marker','Change'],'')
        self.assertEqual(table.loc['Text result','Change'],'')
        self.assertEqual(table.loc['Older-only result','Comparison status'],'Not in collection')
        styled=style_results(table,[('Baseline result','Baseline status'),('Comparison result','Comparison status')])
        css=styled._compute().ctx
        row=table.index.get_loc('High marker')
        self.assertIn(('background-color','#dcfce7'),css[row,table.columns.get_loc('Baseline result')])
        self.assertIn(('background-color','#fee2e2'),css[row,table.columns.get_loc('Comparison result')])
        frame.loc[(frame.collection_id=='older') & (frame.test_key=='high'),'units_display']='other units'
        changed=comparison_frame(frame,'older','demo').set_index('Test').loc['High marker']
        self.assertEqual(changed['Change'],'')
        self.assertIn('Different units',changed['Note'])

    def test_comparison_matches_panel_aliases_without_cross_matching_blood_and_urine(self):
        import pandas as pd
        row=dict(collection_id='old',panel_name='CBC/Diff Ambiguous Default',
                 test_key='wbc',test_name='WBC',result_text='5.0',units_display='x10E3/uL',reference_text='3-10')
        newer=dict(row,collection_id='new',panel_name='CBC, PLATELETS & AUT DIFF (85025)',result_text='6.2')
        urine=dict(row,collection_id='new',panel_name='Microscopic Examination',
                   units_display='/hpf',result_text='None seen',reference_text='0-5')
        table=comparison_frame(pd.DataFrame([row,newer,urine]),'old','new')
        self.assertEqual(len(table),2)
        self.assertEqual(table.loc[table.Panel=='CBC with differential','Change'].iloc[0],'+1.2 x10E3/uL')
        self.assertEqual(table.loc[table.Panel=='Urine microscopy','Baseline status'].iloc[0],'Not in collection')
        ambiguous=comparison_frame(pd.DataFrame([row,newer,newer]),'old','new')
        self.assertEqual(len(ambiguous),3)
        self.assertTrue(ambiguous.Change.eq('').all())
        self.assertTrue(ambiguous.Note.str.contains('Multiple results').all())

    def test_comparison_view_and_abnormal_filter_render(self):
        from streamlit.testing.v1 import AppTest
        script='''
import sqlite3
from labs import ensure_labs
from labs_ui import render_labs
from test_labs import add_sample, add_older_sample
db=sqlite3.connect(':memory:')
ensure_labs(db)
add_sample(db)
add_older_sample(db)
render_labs(db)
'''
        at=AppTest.from_string(script).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key='lab_baseline').value,'older')
        self.assertEqual(at.selectbox(key='lab_comparison').value,'demo')
        self.assertEqual(len(at.dataframe[0].value),4)
        at.checkbox(key='lab_comparison_outside').check().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.dataframe[0].value['Test'].tolist(),['High marker'])
        at.radio(key='lab_view').set_value('Collection details').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key='lab_collection').value,'demo')
        at.radio(key='lab_view').set_value('Compare collections').run()
        at.selectbox(key='lab_baseline').set_value('demo').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key='lab_comparison').value,'older')

    def test_ranges_preserve_qualifiers_and_do_not_invent_normality(self):
        cases=[('4','1-4','Within lab range'),('4.1','1-4','Above lab range'),
               ('0','1-4','Below lab range'),('>=4','1-4','Boundary uncertain'),
               ('>4','1-4','Above lab range'),('>=4.1','1-4','Above lab range'),
               ('4','>4','Below lab range'),('>4','>4','Within lab range'),
               ('>=4','>4','Boundary uncertain'),('<=4','1-4','Boundary uncertain'),
               ('<1','1-4','Below lab range'),('0-2','0 - 2','Within lab range'),
               ('0-3','0-2','Boundary uncertain'),('Trace','Negative/Trace','Within lab range'),
               ('None seen','0 - 5','Not assessed'),('0','Not Estab.','No reference range'),
               ('Other','Negative','Not assessed'),('4',None,'No reference range')]
        for result,reference,status in cases:
            with self.subTest(result=result,reference=reference):
                self.assertEqual(range_status(result,reference),status)

    def test_lab_backup_round_trip_and_legacy_compatibility(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(NUTRITION_SCHEMA+GARMIN_SCHEMA+HEVY_SCHEMA+GOAL_SCHEMA)
        legacy=snapshot_from_connection(db)
        self.assertEqual(legacy['format_version'],1)
        ensure_labs(db)
        add_sample(db)
        snapshot=snapshot_from_connection(db)
        self.assertEqual(snapshot['format_version'],2)
        self.assertEqual(snapshot['counts']['lab_results'],3)
        with tempfile.TemporaryDirectory() as root:
            result=restore_sqlite(snapshot,Path(root)/'new.sqlite')
            self.assertEqual(result['tables'],16)
            self.assertTrue(result['checksums_match'])
            self.assertEqual(restore_sqlite(legacy,Path(root)/'legacy.sqlite')['tables'],13)
            restored=sqlite3.connect(Path(root)/'new.sqlite')
            self.assertEqual(read_labs(restored).iloc[0].result_text,'>=4')
            restored.close()
            from migrate_sqlite_to_postgres import migrate
            target=sqlite3.connect(Path(root)/'target.sqlite')
            counts=migrate(Path(root)/'new.sqlite',target)
            self.assertEqual(counts['lab_results'],3)
            migrate(Path(root)/'new.sqlite',target)
            self.assertEqual(len(read_labs(target)),3)
            target.close()
        incomplete=copy.deepcopy(snapshot)
        del incomplete['tables']['lab_results']
        with self.assertRaises(ValueError): validate(incomplete)
        db.execute('DROP TABLE lab_results')
        with self.assertRaisesRegex(ValueError,'Incomplete laboratory schema'):
            snapshot_from_connection(db)

    def test_lab_viewer_renders_source_and_filters_ranges(self):
        from streamlit.testing.v1 import AppTest
        script='''
import sqlite3
from labs import ensure_labs
from labs_ui import render_labs
from test_labs import add_sample
db=sqlite3.connect(':memory:')
ensure_labs(db)
add_sample(db)
render_labs(db)
'''
        at=AppTest.from_string(script).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key='lab_collection').value,'demo')
        self.assertEqual(len(at.dataframe[0].value),3)
        self.assertIn('Boundary uncertain',at.dataframe[0].value['Range status'].tolist())
        at.checkbox(key='lab_abnormal_only').check().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.dataframe[0].value['Result'].tolist(),['7'])
