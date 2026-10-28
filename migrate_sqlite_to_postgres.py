"""One-time migration of v0.3's SQLite data into any PostgreSQL database.

Requires DATABASE_URL. Does not modify the source SQLite file or print the URL.
Idempotent: unique/primary keys ensure repeated migrations update rather than duplicate.
"""
import argparse
import os
import sqlite3
from pathlib import Path
from datastore import connect
from importer import SCHEMA as NUTRITION_SCHEMA
from garmin_importer import SCHEMA as GARMIN_SCHEMA
from hevy_importer import SCHEMA as HEVY_SCHEMA

TABLE_KEYS = {
    'nutrition': ['record_id'], 'weights': ['record_id'],
    'backfill': ['local_date'], 'garmin_daily': ['local_date'],
    'garmin_activities': ['activity_id'], 'hc_body_fat': ['record_id'],
    'hc_blood_pressure': ['record_id'], 'hevy_workouts': ['workout_id'],
    'hevy_exercises': ['workout_id', 'exercise_index'],
    'hevy_sets': ['workout_id', 'exercise_index', 'set_index'],
    'hevy_sync_state': ['key'],
    'ingestion_log': ['run_id'],
}


def migrate(source_file, destination, *, dry_run=False):
    source = sqlite3.connect(f'file:{Path(source_file).resolve()}?mode=ro', uri=True)
    try:
        available = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if dry_run:
            return {table: source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    for table in TABLE_KEYS if table in available}
        for schema in (NUTRITION_SCHEMA, GARMIN_SCHEMA, HEVY_SCHEMA):
            destination.executescript(schema)
        counts = {}
        # One transaction for all rows, protecting referential consistency.
        with destination:
            for table, pk in TABLE_KEYS.items():
                if table not in available:
                    continue
                cols = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
                if not cols:
                    continue
                column_sql = ','.join(f'"{col}"' for col in cols)
                placeholders = ','.join(['?'] * len(cols))
                conflict_sql = ','.join(f'"{k}"' for k in pk)
                update_cols = [col for col in cols if col not in pk]
                update_sql = (f' DO UPDATE SET '+','.join(f'"{col}"=excluded."{col}"' for col in update_cols)
                              if update_cols else ' DO NOTHING')
                statement = (f'INSERT INTO "{table}" ({column_sql}) VALUES({placeholders}) '
                             f'ON CONFLICT ({conflict_sql}){update_sql}')
                cur = source.execute(f'SELECT {column_sql} FROM "{table}"')
                count = 0
                for row in cur:
                    destination.execute(statement, row)
                    count += 1
                counts[table] = count
            # Explicit IDs in ingestion_log may leave the PG identity sequence behind.
            if 'ingestion_log' in available:
                destination.execute('''SELECT setval(pg_get_serial_sequence('ingestion_log','run_id'),
                   GREATEST(COALESCE((SELECT MAX(run_id) FROM ingestion_log), 0), 1), true)''')
        return counts
    finally:
        source.close()


def main():
    p = argparse.ArgumentParser(description='Copy a local SQLite dashboard into PostgreSQL')
    p.add_argument('--sqlite', default='nutrition_analytics.sqlite', help='Existing SQLite file (read-only)')
    p.add_argument('--dry-run', action='store_true', help='Show table counts without connecting to PostgreSQL')
    args = p.parse_args()
    if not Path(args.sqlite).is_file():
        p.error('SQLite source file does not exist')
    if args.dry_run:
        result = migrate(args.sqlite, None, dry_run=True)
    else:
        if not os.environ.get('DATABASE_URL'):
            p.error('Set DATABASE_URL in your shell environment; do not paste it into source code')
        destination = connect(url=os.environ['DATABASE_URL'])
        try: result = migrate(args.sqlite, destination)
        finally: destination.close()
    print('Table counts:', result)
    if args.dry_run: print('Dry run only; no data was copied.')
    else: print('Migration complete. Original SQLite file was not changed.')

if __name__ == '__main__':
    main()
