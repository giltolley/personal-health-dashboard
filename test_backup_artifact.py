"""Synthetic encrypted-artifact tests, without production credentials."""
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from nacl.exceptions import CryptoError
from backup_crypto import generate_keys,encrypt,decrypt,save_key_pair
from backup_artifact import prepare_snapshot,verify_artifact,run,FILENAME
from backup_data import snapshot_from_connection,read_backup,NUTRITION_SCHEMA,GARMIN_SCHEMA,HEVY_SCHEMA,GOAL_SCHEMA


def synthetic_snapshot():
    db=sqlite3.connect(':memory:')
    try:
        db.executescript(NUTRITION_SCHEMA+GARMIN_SCHEMA+HEVY_SCHEMA+GOAL_SCHEMA)
        db.execute("INSERT INTO weights VALUES ('synthetic','2025-01-01','demo',150.5)")
        db.commit()
        return snapshot_from_connection(db)
    finally:db.close()


def write_synthetic_artifact(directory):
    _,public=generate_keys()
    return prepare_snapshot(synthetic_snapshot(),public,directory)


class ArtifactTests(unittest.TestCase):
    def test_sealed_box_randomization_authentication_and_wrong_key(self):
        private,public=generate_keys()
        data=encrypt(b'example',public)
        self.assertNotEqual(data,encrypt(b'example',public))
        self.assertEqual(decrypt(data,private),b'example')
        other,_=generate_keys()
        with self.assertRaises(CryptoError):decrypt(data,other)
        with self.assertRaises(CryptoError):decrypt(data[:-1]+bytes([data[-1]^1]),private)

    def test_key_pair_is_private_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'keys';public=save_key_pair(path)
            private=path/'Health_Dashboard_Backup_Private_Key.txt'
            self.assertEqual(private.stat().st_mode&0o777,0o600)
            self.assertEqual(decrypt(encrypt(b'test',public),private.read_text()),b'test')
            with self.assertRaises(FileExistsError):save_key_pair(path)

    def test_only_ciphertext_is_emitted_and_restore_is_verified(self):
        private,public=generate_keys()
        with tempfile.TemporaryDirectory() as root:
            output=Path(root)/'output'
            checksum=prepare_snapshot(synthetic_snapshot(),public,output)
            self.assertEqual([p.name for p in output.iterdir()],[FILENAME])
            cipher=output/FILENAME
            verify_artifact(cipher,checksum)
            clear=Path(root)/'clear.gz';clear.write_bytes(decrypt(cipher.read_bytes(),private))
            snapshot=read_backup(clear)
            self.assertEqual(len(snapshot['tables']),13)
            self.assertEqual(snapshot['counts']['weights'],1)
            self.assertEqual(cipher.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):prepare_snapshot(snapshot,public,output)
            cipher.write_bytes(cipher.read_bytes()+b'corrupt')
            with self.assertRaises(ValueError):verify_artifact(cipher,checksum)
            with self.assertRaises(ValueError):verify_artifact(cipher,'')

    def test_plaintext_temporary_files_are_removed_on_failure(self):
        _,public=generate_keys()
        actual=tempfile.TemporaryDirectory
        seen=[]
        def temporary(**kwargs):
            result=actual(**kwargs);seen.append(Path(result.name));return result
        with actual() as root,patch('backup_artifact.tempfile.TemporaryDirectory',side_effect=temporary),patch('backup_artifact.restore_sqlite',side_effect=ValueError('invalid snapshot')):
            output=Path(root)/'output'
            with self.assertRaises(ValueError):prepare_snapshot(synthetic_snapshot(),public,output)
            self.assertFalse(output.exists())
            self.assertTrue(seen)
            self.assertTrue(all(not path.exists() for path in seen))

    def test_configuration_fails_before_connecting(self):
        with patch.dict(os.environ,{},clear=True),patch('backup_artifact.connect') as connect:
            with self.assertRaises(Exception):run('unused')
            connect.assert_not_called()

    def test_database_transaction_is_read_only_and_closes_on_error(self):
        _,public=generate_keys()
        with patch.dict(os.environ,{'BACKUP_PUBLIC_KEY':public,'DATABASE_URL':'postgresql://synthetic'}),patch('backup_artifact.connect') as connect,patch('backup_artifact.snapshot_from_connection',side_effect=RuntimeError('failed')):
            db=connect.return_value
            with self.assertRaises(RuntimeError):run('unused')
            db.execute.assert_called_once_with('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            db.close.assert_called_once()
