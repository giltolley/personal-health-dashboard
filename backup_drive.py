"""Daily private Drive backups. No plaintext artifacts or decryption keys on GitHub."""
from datetime import datetime,timedelta,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from backup_data import snapshot_from_connection,write_backup,read_backup,restore_sqlite
from backup_crypto import encrypt
from datastore import connect

SCOPE='https://www.googleapis.com/auth/drive.file'
APP='personal-health-dashboard-backup-v1'


def drive_client(auth):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    if auth.get('token_uri')!='https://oauth2.googleapis.com/token':
        raise ValueError('Unexpected Google token endpoint.')
    credentials=Credentials.from_authorized_user_info(auth,scopes=[SCOPE])
    return build('drive','v3',credentials=credentials,cache_discovery=False)


def backup_files(client,folder_id):
    result=[];page=None
    while True:
        response=client.files().list(q=f"'{folder_id}' in parents and trashed=false and "
            f"appProperties has {{ key='backupApp' and value='{APP}' }}",
            fields='nextPageToken,files(id,createdTime,appProperties)',pageSize=100,pageToken=page).execute()
        result.extend(response.get('files',[]))
        page=response.get('nextPageToken')
        if not page:
            return result


def publish(client,folder_id,payload,now,retention_days=30):
    from googleapiclient.http import MediaIoBaseUpload
    if not re.fullmatch(r'[A-Za-z0-9_-]+',folder_id or ''):
        raise ValueError('Missing or malformed backup folder.')
    folder=client.files().get(fileId=folder_id,
        fields='id,mimeType,trashed,capabilities(canAddChildren)').execute()
    if folder.get('trashed') or folder.get('mimeType')!='application/vnd.google-apps.folder' or not folder.get('capabilities',{}).get('canAddChildren'):
        raise ValueError('Backup folder is unavailable or not writable.')
    checksum=hashlib.sha256(payload).hexdigest()
    name='dashboard-'+now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.health-backup.enc'
    uploaded=client.files().create(body={'name':name,'parents':[folder_id],
        'appProperties':{'backupApp':APP,'sha256':checksum}},
        media_body=MediaIoBaseUpload(io.BytesIO(payload),mimetype='application/octet-stream',resumable=True),
        fields='id,size,md5Checksum').execute()
    stored=client.files().get_media(fileId=uploaded['id']).execute()
    if len(stored)!=len(payload) or hashlib.sha256(stored).hexdigest()!=checksum:
        raise ValueError('Uploaded backup did not pass download verification; retention was not applied.')
    # Recoverable trash only; never permanently delete and never touch unrelated files.
    cutoff=now-timedelta(days=retention_days)
    for item in backup_files(client,folder_id):
        created=datetime.fromisoformat(item['createdTime'].replace('Z','+00:00'))
        if item['id']!=uploaded['id'] and created<cutoff:
            client.files().update(fileId=item['id'],body={'trashed':True},fields='id').execute()
    return uploaded['id']


def run():
    auth=json.loads(os.environ.get('BACKUP_DRIVE_AUTH_JSON','{}'))
    public_key=os.environ.get('BACKUP_PUBLIC_KEY','').strip()
    if not public_key or not auth.get('folder_id'):
        raise ValueError('Backup authorization and public encryption key are required.')
    # Fail before exporting if the public key is malformed.
    encrypt(b'configuration-check',public_key)
    client=drive_client(auth)
    url=os.environ.get('DATABASE_URL','').strip()
    if not url.startswith(('postgresql://','postgres://')):
        raise ValueError('Hosted PostgreSQL connection is required.')
    db=connect(url=url)
    if getattr(db,'backend',None)!='postgresql':
        db.close()
        raise ValueError('Hosted PostgreSQL is required; refusing SQLite fallback.')
    try:
        with db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            snapshot=snapshot_from_connection(db)
    finally:
        db.close()
    with tempfile.TemporaryDirectory(prefix='private_health_backup_') as temp:
        archive=Path(temp)/'snapshot.health-backup.json.gz'
        write_backup(snapshot,archive)
        restore_sqlite(read_backup(archive),Path(temp)/'verification.sqlite')
        encrypted=encrypt(archive.read_bytes(),public_key)
        publish(client,auth['folder_id'],encrypted,datetime.now(timezone.utc))
    print('Encrypted backup uploaded and verified. Thirty-day retention applied.')


if __name__=='__main__':
    try:
        run()
    except Exception as error:
        # Do not print OAuth responses, tokens, private measurements or DSNs.
        print('Backup failed ('+type(error).__name__+'). Check private configuration and Google authorization.')
        raise SystemExit(1)
