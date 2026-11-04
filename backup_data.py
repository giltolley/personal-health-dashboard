"""Portable application-data backups; does not back up PostgreSQL roles/RLS.

Use export with DATABASE_URL, then verify in an isolated SQLite file. Output
contains private health data: keep it off GitHub and in protected storage.
"""
import argparse
from datetime import datetime,timezone
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datastore import connect
from importer import SCHEMA as NUTRITION_SCHEMA
from garmin_importer import SCHEMA as GARMIN_SCHEMA
from hevy_importer import SCHEMA as HEVY_SCHEMA
from goals import SCHEMA as GOAL_SCHEMA

TABLES=('backfill','garmin_activities','garmin_daily','goal_history','hc_blood_pressure',
        'hc_body_fat','hevy_exercises','hevy_sets','hevy_sync_state','hevy_workouts',
        'ingestion_log','nutrition','weights')


def canonical_table(table):
    # Canonical row order makes comparison independent of SQL scan order.
    def normalize(row):
        # SQL JSON may emit a REAL zero as 0 while SQLite emits 0.0.
        return {k: {'number':str(Decimal(str(v)).normalize())} if isinstance(v,(int,float))
                and not isinstance(v,bool) else v for k,v in row.items()}
    rows=sorted(json.dumps(normalize(r),sort_keys=True,separators=(',',':'),allow_nan=False) for r in table['rows'])
    return json.dumps({'columns':table['columns'],'rows':rows},sort_keys=True,separators=(',',':')).encode()


def seal(snapshot):
    snapshot=dict(snapshot)
    snapshot['checksums']={name:hashlib.sha256(canonical_table(table)).hexdigest()
                           for name,table in snapshot['tables'].items()}
    snapshot['counts']={name:len(table['rows']) for name,table in snapshot['tables'].items()}
    return snapshot


def validate(snapshot):
    if snapshot.get('format_version')!=1 or set(snapshot.get('tables',{}))!=set(TABLES):
        raise ValueError('Unsupported format or incomplete application table set.')
    for name in TABLES:
        table=snapshot['tables'][name]
        if snapshot.get('counts',{}).get(name)!=len(table['rows']):
            raise ValueError('Row-count mismatch: '+name)
        if hashlib.sha256(canonical_table(table)).hexdigest()!=snapshot.get('checksums',{}).get(name):
            raise ValueError('Checksum mismatch: '+name)
        if any(set(row)!=set(table['columns']) for row in table['rows']):
            raise ValueError('Unexpected row columns: '+name)


def snapshot_from_connection(db):
    tables={}
    # Caller owns the transaction; use one repeatable-read transaction on PostgreSQL.
    for name in TABLES:
        cursor=db.execute('SELECT * FROM '+name)
        columns=[c[0] if isinstance(c,tuple) else c.name for c in cursor.description]
        tables[name]={'columns':columns,'rows':[dict(zip(columns,r)) for r in cursor.fetchall()]}
    return seal({'format_version':1,'created_at':datetime.now(timezone.utc).isoformat(),
                 'source_engine':getattr(db,'backend','sqlite'),'tables':tables})


def write_backup(snapshot,path):
    validate(snapshot)
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive create: never overwrite an earlier backup.
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as raw:
        with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as output:
            output.write(json.dumps(snapshot,allow_nan=False,separators=(',',':')).encode())
    path.chmod(0o600)


def read_backup(path):
    with gzip.open(path,'rt',encoding='utf-8') as source:
        snapshot=json.load(source)
    validate(snapshot)
    return snapshot


def restore_sqlite(snapshot,destination):
    validate(snapshot)
    path=Path(destination)
    # sqlite URI mode=rwc would overwrite data; exclusive creation prevents that.
    with path.open('xb'):
        pass
    path.chmod(0o600)
    db=sqlite3.connect(path)
    try:
        db.executescript(NUTRITION_SCHEMA+GARMIN_SCHEMA+HEVY_SCHEMA+GOAL_SCHEMA)
        with db:
            for name in TABLES:
                table=snapshot['tables'][name]
                columns=[r[1] for r in db.execute('PRAGMA table_info('+name+')')]
                if table['columns']!=columns:
                    raise ValueError('Schema mismatch: '+name)
                if table['rows']:
                    db.executemany('INSERT INTO '+name+' ('+','.join(columns)+') VALUES ('+
                                   ','.join('?' for _ in columns)+')',
                                   [tuple(row[c] for c in columns) for row in table['rows']])
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Restored database failed integrity check.')
        restored=snapshot_from_connection(db)
        if restored['checksums']!=snapshot['checksums']:
            raise ValueError('Restored data differs from source snapshot.')
        orphans=db.execute('''SELECT COUNT(*) FROM hevy_sets s LEFT JOIN hevy_exercises e
            ON s.workout_id=e.workout_id AND s.exercise_index=e.exercise_index
            WHERE e.workout_id IS NULL''').fetchone()[0]
        orphans+=db.execute('''SELECT COUNT(*) FROM hevy_exercises e LEFT JOIN hevy_workouts w
            ON e.workout_id=w.workout_id WHERE w.workout_id IS NULL''').fetchone()[0]
        if orphans:
            raise ValueError('Backup contains orphaned Hevy records.')
        return {'tables':len(TABLES),'rows':sum(restored['counts'].values()),
                'counts':restored['counts'],'integrity':'ok','checksums_match':True,'orphaned_records':0}
    except Exception:
        db.close()
        path.unlink(missing_ok=True)  # Only the newly created failed restore, never an existing file.
        raise
    finally:
        db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='operation',required=True)
    export=sub.add_parser('export');export.add_argument('--output',required=True)
    export.add_argument('--sqlite',default=None)
    restore=sub.add_parser('restore-sqlite');restore.add_argument('--backup',required=True)
    restore.add_argument('--destination',required=True)
    args=parser.parse_args()
    if args.operation=='export':
        db=connect(args.sqlite,url='' if args.sqlite else None)
        try:
            with db:
                if getattr(db,'backend',None)=='postgresql':
                    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                else:
                    db.execute('BEGIN')
                snapshot=snapshot_from_connection(db)
            write_backup(snapshot,args.output)
            print('Backup saved:',len(TABLES),'tables;',sum(snapshot['counts'].values()),'records.')
        finally:
            db.close()
    else:
        print(json.dumps(restore_sqlite(read_backup(args.backup),args.destination),sort_keys=True))


if __name__=='__main__':
    main()
