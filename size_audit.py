"""Inspect actual local SQLite disk usage and count rows, no uploads or network."""
import argparse
import sqlite3
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sqlite', default='nutrition_analytics.sqlite')
    args = p.parse_args()
    path = Path(args.sqlite)
    if not path.is_file():
        p.error(f'Database file not found: {path}')
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True) as db:
        pages = db.execute('PRAGMA page_count').fetchone()[0]
        page_size = db.execute('PRAGMA page_size').fetchone()[0]
        print('Current local database:', f'{path.stat().st_size/1024/1024:.2f} MiB')
        print('Allocated SQLite pages:', f'{pages*page_size/1024/1024:.2f} MiB')
        print('Supabase free PostgreSQL quota:', '500 MB (Postgres overhead differs)')
        print('Tables and row counts:')
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence' ORDER BY name"):
            print(f'  {table:<25} {db.execute("SELECT COUNT(*) FROM " + chr(34) + table + chr(34)).fetchone()[0]:>9,}')

if __name__ == '__main__':
    main()
