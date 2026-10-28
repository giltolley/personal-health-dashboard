"""Self-contained smoke test; only uses fabricated records, no account access."""
import json
import sqlite3
import zipfile
from io import BytesIO
from garmin_importer import ensure_schema,import_dataset,import_garmin_zip

def test():
    db=sqlite3.connect(':memory:')
    ensure_schema(db)
    day={'calendarDate':'2026-10-20',
        'movement':{'steps':{'value':9750,'distanceInMeters':7100}},
        'calories':{'burnedTotal':2600,'burnedResting':1900,'burnedActive':700},
        'heartRate':{'restingValue':55},
        'intensityMinutes':{'moderate':20,'vigorous':10},
        'stress':{'avgLevel':35},'bodyBattery':{'minValue':15,'maxValue':85}}
    bundle={'daily_summaries':{'data':[day]},
            'hrv_summaries':{'hrvSummaries':[{'calendarDate':'2026-10-20','lastNightAvg':41,'weeklyAvg':42,'status':'BALANCED'}]},
            'sleep_summaries':[{'calendarDate':'2026-10-20','sleepTimeSeconds':25200,
                'deepSleepSeconds':5400,'remSleepSeconds':5400,'sleepScores':{'overall':{'value':79}}}],
            'activities':[{'activityId':123,'startTimeLocal':'2026-10-20 07:00:00',
                'activityName':'Example run','activityType':{'typeKey':'running'},
                'duration':3600,'distance':10000,'calories':650}]}
    stream=BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name,data in bundle.items():z.writestr(f'{name}.json',json.dumps(data))
    assert import_garmin_zip(db,stream)=={'daily_summaries':1,'hrv_summaries':1,'sleep_summaries':1,'activities':1}
    assert import_garmin_zip(db,stream)=={'daily_summaries':1,'hrv_summaries':1,'sleep_summaries':1,'activities':1}
    assert db.execute('SELECT COUNT(*) FROM garmin_daily').fetchone()[0]==1
    assert db.execute('SELECT COUNT(*) FROM garmin_activities').fetchone()[0]==1
    fields=db.execute("SELECT steps,calories_burned,hrv_ms,sleep_hours,intensity_minutes FROM garmin_daily WHERE local_date='2026-10-20'").fetchone()
    assert fields==(9750.0,2600.0,41.0,7.0,40.0), fields
    print('PASS: parsing, normalization, idempotence, source data preservation')
if __name__=='__main__':test()
