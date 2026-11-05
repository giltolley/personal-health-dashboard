"""Synthetic lab range, presentation and recovery checks; no personal records."""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from labs import SCHEMA, ensure_labs, read_labs, range_status
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


class LabTests(unittest.TestCase):
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
