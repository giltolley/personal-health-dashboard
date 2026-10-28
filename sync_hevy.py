"""Command line read-only Hevy synchronization.

   py sync_hevy.py          # full import first run, incremental thereafter
   py sync_hevy.py --full   # force complete reimport / reconcile deletions
"""
import argparse
import os
from pathlib import Path
from importer import initialize
from garmin_importer import ensure_schema
from hevy_importer import sync_hevy, ensure_hevy_schema


def main():
    parser=argparse.ArgumentParser(description='Hevy workouts -> local health dashboard SQLite')
    parser.add_argument('--full',action='store_true',help='Force complete download/reconciliation')
    args=parser.parse_args()
    path=Path(os.environ.get('NUTRITION_DB',str(Path(__file__).resolve().parent/'nutrition_analytics.sqlite')))
    db=initialize(path)
    ensure_schema(db)
    ensure_hevy_schema(db)
    try:
        result=sync_hevy(db,full=args.full,progress=print)
        print('Hevy sync complete:',result)
        print('Database:',path.resolve())
    finally:
        db.close()

if __name__=='__main__':main()
