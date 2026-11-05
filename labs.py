"""Private laboratory records with source-preserving values and lab ranges."""
import re
from decimal import Decimal
from datastore import read_frame

SCHEMA = '''
CREATE TABLE IF NOT EXISTS lab_collections (
 collection_id TEXT PRIMARY KEY,
 collected_on TEXT NOT NULL,
 source TEXT NOT NULL,
 performing_lab TEXT,
 fasting INTEGER CHECK (fasting IN (0,1)),
 provenance TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_panels (
 panel_id TEXT PRIMARY KEY,
 collection_id TEXT NOT NULL REFERENCES lab_collections(collection_id),
 panel_name TEXT NOT NULL,
 ordered_on TEXT,
 resulted_on TEXT NOT NULL,
 source_text TEXT NOT NULL,
 notes TEXT
);
CREATE INDEX IF NOT EXISTS lab_panels_collection_idx ON lab_panels(collection_id);
CREATE TABLE IF NOT EXISTS lab_results (
 panel_id TEXT NOT NULL REFERENCES lab_panels(panel_id),
 test_key TEXT NOT NULL,
 test_name TEXT NOT NULL,
 result_text TEXT NOT NULL CHECK (length(result_text)>0),
 value_numeric DOUBLE PRECISION,
 comparator TEXT CHECK (comparator IN ('=','>','>=','<','<=')),
 units_reported TEXT,
 units_display TEXT,
 unit_note TEXT,
 reference_text TEXT,
 reported_flag TEXT,
 display_order INTEGER NOT NULL,
 PRIMARY KEY (panel_id,test_key),
 CHECK ((value_numeric IS NULL AND comparator IS NULL)
     OR (value_numeric IS NOT NULL AND comparator IS NOT NULL))
);
'''


def ensure_labs(db):
    # Hosted tables are provisioned separately, with RLS and revoked API grants.
    if getattr(db, 'backend', None) != 'postgresql':
        db.executescript(SCHEMA)
        db.commit()


def read_labs(db):
    return read_frame(db, '''SELECT c.collection_id,c.collected_on,c.source,
        c.performing_lab,c.fasting,c.provenance,p.panel_id,p.panel_name,
        p.ordered_on,p.resulted_on,p.source_text,p.notes,
        r.test_key,r.test_name,r.result_text,r.value_numeric,r.comparator,
        r.units_reported,r.units_display,r.unit_note,r.reference_text,r.reported_flag,
        r.display_order
        FROM lab_collections c JOIN lab_panels p ON p.collection_id=c.collection_id
        JOIN lab_results r ON r.panel_id=p.panel_id
        ORDER BY c.collected_on DESC,p.panel_name,r.display_order''')


NUMBER = r'(?:\d+(?:\.\d*)?|\.\d+)'


def range_status(result, reference):
    """Compare source values to source ranges only; never infer clinical targets.

    Qualified and interval values are assessed as sets of possible values. If
    the set crosses a reference boundary, do not pretend the value is exact.
    Unrecognized text stays unassessed rather than being marked normal.
    """
    result = str(result).strip().replace('≥', '>=').replace('≤', '<=')
    reference = str(reference or '').strip()
    if not reference or reference.lower() == 'not estab.':
        return 'No reference range'
    match = re.fullmatch(rf'({NUMBER})\s*-\s*({NUMBER})', reference)
    one_sided = re.fullmatch(rf'(>=|<=|>|<)\s*({NUMBER})', reference)
    if not match and not one_sided:
        allowed = [v.strip().casefold() for v in reference.split('/')]
        return 'Within lab range' if result.casefold() in allowed else 'Not assessed'
    low, high = None, None
    low_closed, high_closed = True, True
    if match:
        low, high = map(Decimal, match.groups())
    else:
        op, value = one_sided.groups()
        if op.startswith('>'):
            low, low_closed = Decimal(value), op == '>='
        else:
            high, high_closed = Decimal(value), op == '<='
    numeric = re.fullmatch(rf'(>=|<=|>|<)?\s*({NUMBER})', result)
    interval = re.fullmatch(rf'({NUMBER})\s*-\s*({NUMBER})', result)
    if not numeric and not interval:
        return 'Not assessed'
    a_closed, b_closed = True, True
    if interval:
        a, b = map(Decimal, interval.groups())
    else:
        op, value = numeric.groups()
        a = b = Decimal(value)
        if op in ('>', '>='):
            b, a_closed = None, op == '>='
        elif op in ('<', '<='):
            a, b_closed = None, op == '<='
    if low is not None and b is not None and (b < low or (b == low and (not low_closed or not b_closed))):
        return 'Below lab range'
    if high is not None and a is not None and (a > high or (a == high and (not high_closed or not a_closed))):
        return 'Above lab range'
    inside_low = low is None or (a is not None and (a > low or (a == low and (low_closed or not a_closed))))
    inside_high = high is None or (b is not None and (b < high or (b == high and (high_closed or not b_closed))))
    if inside_low and inside_high:
        return 'Within lab range'
    return 'Boundary uncertain'
