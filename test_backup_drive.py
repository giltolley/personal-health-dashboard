"""Synthetic encryption and Drive retention tests. No Google account or DB access."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from backup_crypto import generate_keys,encrypt,decrypt,private_write
from backup_drive import publish,backup_files,APP,SCOPE,drive_client,run


class EncryptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private,cls.public=generate_keys()

    def test_roundtrip_and_randomized_encryption(self):
        a=encrypt(b'private synthetic data',self.public)
        b=encrypt(b'private synthetic data',self.public)
        self.assertNotEqual(a,b)
        self.assertNotIn(b'private synthetic data',a)
        self.assertEqual(decrypt(a,self.private),b'private synthetic data')

    def test_wrong_key_and_corruption_fail(self):
        from nacl.exceptions import CryptoError
        encrypted=encrypt(b'private',self.public)
        wrong,_=generate_keys()
        with self.assertRaises(CryptoError):decrypt(encrypted,wrong)
        corrupt=encrypted[:-1]+bytes([encrypted[-1]^1])
        with self.assertRaises(CryptoError):decrypt(corrupt,self.private)
        with self.assertRaises(ValueError):decrypt(b'wrong format',self.private)

    def test_private_files_are_exclusive_and_restricted(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'private.key'
            private_write(path,b'private')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):private_write(path,b'replacement')


class DriveTests(unittest.TestCase):
    now=datetime(2025,6,10,12,tzinfo=timezone.utc)

    def client(self,payload):
        client=MagicMock();files=client.files.return_value
        files.get.return_value.execute.return_value={'id':'folder','mimeType':'application/vnd.google-apps.folder',
            'capabilities':{'canAddChildren':True}}
        files.create.return_value.execute.return_value={'id':'new','size':str(len(payload))}
        files.get_media.return_value.execute.return_value=payload
        files.list.return_value.execute.return_value={'files':[
            {'id':'old','createdTime':'2025-01-01T00:00:00Z'},
            {'id':'recent','createdTime':'2025-06-01T00:00:00Z'},
            {'id':'new','createdTime':'2025-06-10T12:00:00Z'}]}
        return client,files

    def test_upload_verified_before_managed_old_backups_are_trashed(self):
        _,public=generate_keys();payload=encrypt(b'synthetic',public)
        client,files=self.client(payload)
        self.assertEqual(publish(client,'folder',payload,self.now),'new')
        metadata=files.create.call_args.kwargs['body']
        self.assertEqual(metadata['appProperties']['backupApp'],APP)
        self.assertEqual(metadata['parents'],['folder'])
        files.update.assert_called_once_with(fileId='old',body={'trashed':True},fields='id')
        self.assertIn('backupApp',files.list.call_args.kwargs['q'])
        self.assertIn("'folder' in parents",files.list.call_args.kwargs['q'])

    def test_failed_download_verification_never_runs_retention(self):
        payload=b'encrypted payload'
        client,files=self.client(payload)
        files.get_media.return_value.execute.return_value=b'wrong'
        with self.assertRaisesRegex(ValueError,'verification'):publish(client,'folder',payload,self.now)
        files.update.assert_not_called();files.list.assert_not_called()

    def test_folder_validation_and_upload_failure_do_not_prune(self):
        client,files=self.client(b'x')
        with self.assertRaises(ValueError):publish(client,"bad'folder",b'x',self.now)
        files.get.assert_not_called()
        files.create.return_value.execute.side_effect=RuntimeError('Upload failed')
        with self.assertRaises(RuntimeError):publish(client,'folder',b'x',self.now)
        files.update.assert_not_called()

    def test_paginated_listing_and_exact_scope(self):
        client=MagicMock()
        client.files.return_value.list.return_value.execute.side_effect=[
            {'files':[{'id':'one'}],'nextPageToken':'page2'}, {'files':[{'id':'two'}]}]
        self.assertEqual([x['id'] for x in backup_files(client,'folder')],['one','two'])
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_info') as credentials,\
             patch('googleapiclient.discovery.build'):
            drive_client({'token_uri':'https://oauth2.googleapis.com/token'})
            self.assertEqual(credentials.call_args.kwargs['scopes'],[SCOPE])
        with self.assertRaises(ValueError):drive_client({'token_uri':'https://unexpected.invalid/token'})

    def test_missing_configuration_fails_without_database_connection(self):
        with patch.dict('os.environ',{},clear=True),patch('backup_drive.connect') as connect:
            with self.assertRaises(ValueError):run()
            connect.assert_not_called()

class SetupAndRunTests(unittest.TestCase):
    def test_setup_creates_scoped_private_files_without_printing_secrets(self):
        import contextlib
        import io
        from setup_drive_backup import main
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'new-setup'
            credentials=MagicMock()
            credentials.refresh_token='synthetic-refresh'
            credentials.to_json.return_value=json.dumps({'token':'synthetic-access',
                'refresh_token':'synthetic-refresh','client_id':'synthetic-client',
                'client_secret':'synthetic-client-secret','token_uri':'https://oauth2.googleapis.com/token',
                'scopes':[SCOPE],'expiry':'2025-01-01T00:00:00Z'})
            client=MagicMock()
            client.files.return_value.create.return_value.execute.return_value={'id':'folder'}
            output=io.StringIO()
            with patch('sys.argv',['setup_drive_backup.py','--client','synthetic.json','--output-dir',str(root)]),\
                 patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as flow,\
                 patch('googleapiclient.discovery.build',return_value=client),\
                 contextlib.redirect_stdout(output):
                flow.return_value.run_local_server.return_value=credentials
                main()
                self.assertEqual(flow.call_args.args[1],[SCOPE])
            auth=json.loads((root/'drive-backup-auth.json').read_text())
            self.assertNotIn('token',auth);self.assertNotIn('expiry',auth)
            self.assertEqual(auth['folder_id'],'folder')
            self.assertNotIn('synthetic-refresh',output.getvalue())
            self.assertNotIn('synthetic-client-secret',output.getvalue())
            self.assertEqual((root/'drive-backup-auth.json').stat().st_mode&0o777,0o600)
            public=(root/'backup-public.txt').read_text()
            private=(root/'backup-private.key').read_text()
            self.assertEqual(decrypt(encrypt(b'test',public),private),b'test')

    def test_run_uploads_only_ciphertext_and_cleans_plaintext_on_failure(self):
        import sqlite3
        from backup_data import (snapshot_from_connection,NUTRITION_SCHEMA,GARMIN_SCHEMA,HEVY_SCHEMA,GOAL_SCHEMA)
        source=sqlite3.connect(':memory:')
        source.executescript(NUTRITION_SCHEMA+GARMIN_SCHEMA+HEVY_SCHEMA+GOAL_SCHEMA)
        snapshot=snapshot_from_connection(source);source.close()
        private,public=generate_keys()
        db=MagicMock();db.backend='postgresql'
        observed={}
        def reject_upload(client,folder,payload,now):
            self.assertEqual(folder,'folder')
            self.assertTrue(decrypt(payload,private).startswith(b'\x1f\x8b'))
            # The plaintext directory exists only while the context is active.
            raise RuntimeError('Synthetic upload failure')
        import backup_drive
        real_temp=backup_drive.tempfile.TemporaryDirectory
        def capture_temp(*args,**kwargs):
            directory=real_temp(*args,**kwargs)
            observed['path']=directory.name
            return directory
        with patch.dict('os.environ',{'DATABASE_URL':'postgresql://synthetic',
            'BACKUP_PUBLIC_KEY':public,'BACKUP_DRIVE_AUTH_JSON':json.dumps({'folder_id':'folder'})}),\
             patch('backup_drive.drive_client'),patch('backup_drive.connect',return_value=db),\
             patch('backup_drive.snapshot_from_connection',return_value=snapshot),\
             patch('backup_drive.publish',side_effect=reject_upload),\
             patch('backup_drive.tempfile.TemporaryDirectory',side_effect=capture_temp):
            with self.assertRaises(RuntimeError):run()
        self.assertFalse(Path(observed['path']).exists())
        db.close.assert_called_once()


if __name__=='__main__':
    unittest.main()
