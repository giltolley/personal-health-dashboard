"""Run once on your own computer. Secrets and the decryption key stay local."""
import argparse
import json
from pathlib import Path
from backup_crypto import generate_keys,private_write
from backup_drive import SCOPE,APP


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',required=True,help='Downloaded Desktop OAuth client JSON')
    parser.add_argument('--output-dir',default='backups/setup',help='New private local directory')
    args=parser.parse_args()
    root=Path(args.output_dir)
    # Refuse reuse so setup never overwrites an existing decryption key.
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    private,public=generate_keys()
    private_write(root/'backup-private.key',(private+'\n').encode())
    private_write(root/'backup-public.txt',(public+'\n').encode())
    flow=InstalledAppFlow.from_client_secrets_file(args.client,[SCOPE])
    credentials=flow.run_local_server(port=0,access_type='offline',prompt='consent')
    if not credentials.refresh_token:
        raise RuntimeError('Google did not provide offline authorization.')
    client=build('drive','v3',credentials=credentials,cache_discovery=False)
    folder=client.files().create(body={'name':'Personal Health Dashboard Backups',
        'mimeType':'application/vnd.google-apps.folder','appProperties':{'backupApp':APP}},
        fields='id').execute()
    auth={key:value for key,value in json.loads(credentials.to_json()).items()
          if key in ('client_id','client_secret','refresh_token','token_uri','scopes')}
    auth['folder_id']=folder['id']
    private_write(root/'drive-backup-auth.json',json.dumps(auth).encode())
    print('Setup files saved in the private output directory. No secret values were printed.')
    print('Keep backup-private.key in your password manager and another safe location; never upload it to GitHub.')
    print('Add drive-backup-auth.json as BACKUP_DRIVE_AUTH_JSON and backup-public.txt as BACKUP_PUBLIC_KEY in Actions secrets.')
    print('Then set ENABLE_DRIVE_BACKUPS=true in Actions variables and manually run the backup workflow once.')


if __name__=='__main__':
    main()
