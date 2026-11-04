"""Synthetic recovery tests; never access the live database."""
import copy
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from backup_data import (snapshot_from_connection,write_backup,read_backup,restore_sqlite,
    seal,validate,NUTRITION_SCHEMA,GARMIN_SCHEMA,HEVY_SCHEMA,GOAL_SCHEMA,main)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.executescript(NUTRITION_SCHEMA+GARMIN_SCHEMA+HEVY_SCHEMA+GOAL_SCHEMA)
        self.db.execute("INSERT INTO weights VALUES (?,?,?,?)",('synthetic','2025-01-01','demo',150.5))
        self.db.execute('INSERT INTO hevy_sync_state VALUES (?,?)',('demo',"Unicode: ñ; DROP TABLE weights;"))
        self.db.commit()
        self.snapshot=snapshot_from_connection(self.db)
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)

    def tearDown(self):
        self.db.close();self.temp.cleanup()

    def test_round_trip_exact_rows_and_integrity(self):
        path=self.root/'sample.health-backup.json.gz'
        write_backup(self.snapshot,path)
        result=restore_sqlite(read_backup(path),self.root/'restore.sqlite')
        self.assertEqual(result['tables'],13)
        self.assertEqual(result['rows'],2)
        self.assertTrue(result['checksums_match'])
        db=sqlite3.connect(self.root/'restore.sqlite')
        self.assertEqual(db.execute('SELECT value FROM hevy_sync_state').fetchone()[0],
                         "Unicode: ñ; DROP TABLE weights;")
        db.close()
        self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_existing_backup_and_destination_are_never_overwritten(self):
        path=self.root/'existing'
        path.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):write_backup(self.snapshot,path)
        with self.assertRaises(FileExistsError):restore_sqlite(self.snapshot,path)
        self.assertEqual(path.read_bytes(),b'keep')

    def test_tampered_data_count_or_hash_is_rejected(self):
        bad=copy.deepcopy(self.snapshot)
        bad['tables']['weights']['rows'][0]['weight_lb']=999
        with self.assertRaisesRegex(ValueError,'Checksum'):validate(bad)
        bad=copy.deepcopy(self.snapshot);bad['counts']['weights']=50
        with self.assertRaisesRegex(ValueError,'Row-count'):validate(bad)

    def test_incomplete_or_unknown_tables_are_rejected(self):
        bad=copy.deepcopy(self.snapshot);del bad['tables']['weights']
        with self.assertRaises(ValueError):validate(bad)

    def test_schema_mismatch_removes_only_new_failed_restore(self):
        bad=copy.deepcopy(self.snapshot)
        bad['tables']['weights']['columns'].append('unexpected_column')
        for row in bad['tables']['weights']['rows']:row['unexpected_column']='anything'
        bad=seal(bad)
        path=self.root/'failed.sqlite'
        with self.assertRaisesRegex(ValueError,'Schema mismatch'):restore_sqlite(bad,path)
        self.assertFalse(path.exists())

    def test_real_zero_and_json_integer_zero_have_same_checksum(self):
        a=copy.deepcopy(self.snapshot)
        b=copy.deepcopy(self.snapshot)
        a['tables']['weights']['rows'][0]['weight_lb']=0
        b['tables']['weights']['rows'][0]['weight_lb']=0.0
        self.assertEqual(seal(a)['checksums'],seal(b)['checksums'])

    def test_orphaned_hevy_records_do_not_pass_restore(self):
        self.db.execute("INSERT INTO hevy_exercises VALUES ('missing-workout',0,'demo','Demo',NULL)")
        self.db.commit()
        with self.assertRaisesRegex(ValueError,'orphaned'):
            restore_sqlite(snapshot_from_connection(self.db),self.root/'orphan.sqlite')

    def test_recovery_migration_includes_goal_history_and_is_idempotent(self):
        from migrate_sqlite_to_postgres import migrate
        from goals import save_goal
        save_goal(self.db,'2025-01-01','Maintenance',2400,150)
        source=self.root/'source.sqlite'
        db=sqlite3.connect(source);self.db.backup(db);db.close()
        target=sqlite3.connect(self.root/'target.sqlite')
        counts=migrate(source,target)
        self.assertEqual(counts['goal_history'],1)
        migrate(source,target)
        self.assertEqual(target.execute('SELECT COUNT(*) FROM goal_history').fetchone()[0],1)
        self.assertEqual(migrate(source,None,dry_run=True)['goal_history'],1)
        target.close()

    def test_explicit_sqlite_export_ignores_hosted_environment(self):
        source=self.root/'source.sqlite'
        db=sqlite3.connect(source)
        self.db.backup(db);db.close()
        output=self.root/'export.health-backup.json.gz'
        with patch.dict(os.environ,{'DATABASE_URL':'postgresql://invalid-do-not-connect'}),\
             patch('sys.argv',['backup_data.py','export','--sqlite',str(source),'--output',str(output)]):
            main()
        self.assertEqual(read_backup(output)['counts']['weights'],1)
