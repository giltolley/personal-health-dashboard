"""Prepare only an encrypted artifact; plaintext never leaves a temporary directory."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import tempfile
from backup_crypto import encrypt,private_write,MAGIC
from backup_data import snapshot_from_connection,write_backup,read_backup,restore_sqlite
from datastore import connect

FILENAME='dashboard.health-backup.enc'


def prepare_snapshot(snapshot,public_key,output_dir):
    # Fail before producing files if the key is malformed.
    encrypt(b'configuration-check',public_key)
    with tempfile.TemporaryDirectory(prefix='private_health_backup_') as temp:
        archive=Path(temp)/'snapshot.health-backup.json.gz'
        write_backup(snapshot,archive)
        restore_sqlite(read_backup(archive),Path(temp)/'verification.sqlite')
        payload=encrypt(archive.read_bytes(),public_key)
    directory=Path(output_dir)
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/FILENAME
    private_write(path,payload)
    return hashlib.sha256(payload).hexdigest()


def verify_artifact(path,expected):
    if not re.fullmatch('[0-9a-f]{64}',expected or ''):
        raise ValueError('Expected SHA-256 is required.')
    payload=Path(path).read_bytes()
    if not payload.startswith(MAGIC) or hashlib.sha256(payload).hexdigest()!=expected:
        raise ValueError('Downloaded encrypted backup failed verification.')


def run(output_dir):
    public_key=os.environ.get('BACKUP_PUBLIC_KEY','').strip()
    encrypt(b'configuration-check',public_key)
    url=os.environ.get('DATABASE_URL','').strip()
    if not url.startswith(('postgresql://','postgres://')):
        raise ValueError('Hosted PostgreSQL connection is required.')
    db=connect(url=url)
    try:
        with db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            snapshot=snapshot_from_connection(db)
    finally:
        db.close()
    checksum=prepare_snapshot(snapshot,public_key,output_dir)
    # Only a ciphertext hash is exposed to subsequent workflow steps.
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:
            output.write('sha256='+checksum+'\n')
    print('Encrypted backup prepared after successful isolated restore verification.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir')
    parser.add_argument('--verify-file')
    args=parser.parse_args()
    if bool(args.output_dir)==bool(args.verify_file):
        parser.error('Choose --output-dir or --verify-file.')
    try:
        if args.verify_file:
            verify_artifact(args.verify_file,os.environ.get('EXPECTED_BACKUP_SHA256',''))
            print('Downloaded encrypted artifact verified.')
        else:
            run(args.output_dir)
    except Exception as error:
        print('Backup failed ('+type(error).__name__+'). Check private configuration and workflow steps.')
        raise SystemExit(1)


if __name__=='__main__':
    main()
