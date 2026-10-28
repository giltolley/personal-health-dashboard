"""Cloud-friendly scheduled CLI; no Streamlit process required.

Python 3.12+, keys via environment or local key files.
DATABASE_URL chooses PostgreSQL; otherwise the existing SQLite DB is used.
"""
import argparse
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from importer import initialize
from garmin_importer import ensure_schema, sync_garmin
from hevy_importer import ensure_hevy_schema, sync_hevy


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--garmin',action='store_true',help='Synchronize Garmin')
    p.add_argument('--hevy',action='store_true',help='Synchronize Hevy')
    p.add_argument('--days',type=int,default=14,help='Garmin inclusive rolling lookback')
    p.add_argument('--full-hevy',action='store_true',help='Force complete Hevy reconciliation')
    args=p.parse_args()
    if not args.garmin and not args.hevy:
        p.error('Choose --garmin or --hevy, or both')
    if args.days < 1 or args.days > 366:
        p.error('--days must be 1..366')
    db=initialize(os.environ.get('NUTRITION_DB'))
    try:
        ensure_schema(db)
        ensure_hevy_schema(db)
        if args.garmin:
            today=datetime.now(ZoneInfo('America/New_York')).date()
            counts,errors=sync_garmin(db,today-timedelta(days=args.days-1),today)
            print('Garmin saved counts:',counts)
            if errors:
                print('Garmin failed dataset requests:',len(errors))
                for error in errors:print(' -',error)
                raise SystemExit(1)
        if args.hevy:
            result=sync_hevy(db, full=args.full_hevy)
            print('Hevy sync:',result)
    finally:
        db.close()

if __name__=='__main__':
    main()
