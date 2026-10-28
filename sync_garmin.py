"""CLI for an unattended Garmin sync, using the same local API key as the first test.
Usage: py sync_garmin.py --days 14
       py sync_garmin.py --start 2026-01-01 --end 2026-10-27
"""
import argparse
import os
from datetime import date,timedelta
from pathlib import Path
from importer import initialize
from garmin_importer import ensure_schema,sync_garmin

def main():
    parser=argparse.ArgumentParser(description='Garmin Personal API → local dashboard SQLite')
    parser.add_argument('--days',type=int,default=14,help='Recent rolling lookback days')
    parser.add_argument('--start',help='YYYY-MM-DD historical start (up to 366 days per run)')
    parser.add_argument('--end',help='YYYY-MM-DD end; default today')
    parser.add_argument('--batch-days',type=int,default=14,choices=range(1,15),metavar='1..14',
                        help='Days requested per dataset call (default 14; try 3 for problematic history)')
    args=parser.parse_args()
    if args.days<=0:parser.error('--days must be positive')
    end=date.fromisoformat(args.end) if args.end else date.today()
    start=date.fromisoformat(args.start) if args.start else end-timedelta(days=args.days-1)
    if start>end:parser.error('Start must be on/before end')
    path=Path(os.environ.get('NUTRITION_DB',str(Path(__file__).resolve().parent / 'nutrition_analytics.sqlite')))
    db=initialize(path);ensure_schema(db)
    counts,errors=sync_garmin(db,start,end,progress=print,batch_days=args.batch_days)
    print('Saved to',path.resolve())
    print('Updated:',counts)
    if errors:
        print('Some requests failed:',*errors,sep='\n - ')
        raise SystemExit(1)
    print('Garmin sync complete.')
if __name__=='__main__':main()
