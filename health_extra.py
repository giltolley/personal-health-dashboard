"""Extra Health Connect record extraction; supplement existing importer."""
import sqlite3
import tempfile
import shutil
import zipfile
from pathlib import Path
from datetime import date,timedelta
from garmin_importer import ensure_schema

EPOCH = date(1970,1,1)

def import_health_extras(db,file):
    ensure_schema(db)
    if hasattr(file,'seek'):file.seek(0)
    with zipfile.ZipFile(file) as zf:
        matches=[n for n in zf.namelist() if n.endswith('.db')]
        if len(matches)!=1:raise ValueError('Expected exactly one database')
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'hc.db'
            with zf.open(matches[0]) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
            sc=sqlite3.connect(f'file:{target}?mode=ro',uri=True)
            sc.row_factory=sqlite3.Row
            apps=dict(sc.execute('SELECT row_id,package_name FROM application_info_table'))
            count={'body_fat':0,'blood_pressure':0}
            with db:
                for r in sc.execute('SELECT uuid,local_date,app_info_id,percentage FROM body_fat_record_table'):
                    app=apps.get(r['app_info_id'],'')
                    if app!='com.renpho.health':continue
                    db.execute('''INSERT INTO hc_body_fat VALUES(?,?,?,?)
                     ON CONFLICT(record_id) DO UPDATE SET
                     local_date=excluded.local_date,app=excluded.app,body_fat_pct=excluded.body_fat_pct''',
                       (bytes(r['uuid']).hex(),str(EPOCH+timedelta(days=r['local_date'])),app,r['percentage']))
                    count['body_fat']+=1
                for r in sc.execute('SELECT uuid,local_date,app_info_id,systolic,diastolic FROM blood_pressure_record_table'):
                    db.execute('''INSERT INTO hc_blood_pressure VALUES(?,?,?,?,?)
                     ON CONFLICT(record_id) DO UPDATE SET local_date=excluded.local_date,
                     app=excluded.app,systolic=excluded.systolic,diastolic=excluded.diastolic''',
                      (bytes(r['uuid']).hex(),str(EPOCH+timedelta(days=r['local_date'])),apps.get(r['app_info_id'],''),
                       r['systolic'],r['diastolic']))
                    count['blood_pressure']+=1
            sc.close()
            return count
