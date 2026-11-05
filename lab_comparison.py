"""Conservative lab matching and source-range colors; no clinical targets."""
from decimal import Decimal
import re
import pandas as pd
from labs import NUMBER, range_status

OUTSIDE = ('Above lab range', 'Below lab range')
COLORS = {
    'Within lab range': ('#dcfce7', '#14532d'),
    'Above lab range': ('#fee2e2', '#7f1d1d'),
    'Below lab range': ('#fee2e2', '#7f1d1d'),
    'Boundary uncertain': ('#fef3c7', '#78350f'),
}
NEUTRAL = ('#f1f5f9', '#334155')
PANEL_ALIASES = {
    'cbc diff ambiguous default': 'CBC with differential',
    'cbc platelets aut diff 85025': 'CBC with differential',
    'comp metabolic panel 14': 'Metabolic panel',
    'complete metabolic panel 80053': 'Metabolic panel',
    'lipid panel': 'Lipid panel',
    'lipid panel 80061': 'Lipid panel',
    'microscopic examination': 'Urine microscopy',
    'urinalysis automated w micro 81001': 'Urinalysis',
    'tsh w reflex to free t4 84443': 'Thyroid',
}


def clean(value):
    return '' if value is None or pd.isna(value) else str(value).strip()


def panel_family(name):
    normalized = re.sub(r'[^a-z0-9]+', ' ', name.casefold()).strip()
    return PANEL_ALIASES.get(normalized, normalized)


def status_css(status):
    background, foreground = COLORS.get(status, NEUTRAL)
    return f'background-color: {background}; color: {foreground}; font-weight: 600'


def style_results(table, pairs):
    """Color only the result and status cells; keep explicit text labels."""
    def styles(row):
        css = pd.Series('', index=row.index)
        for result_col, status_col in pairs:
            css[result_col] = css[status_col] = status_css(row[status_col])
        return css
    return table.style.apply(styles, axis=1)


def result_change(baseline, comparison):
    if baseline is None or comparison is None:
        return '', 'Not measured in both collections'
    units_a, units_b = clean(baseline.units_display), clean(comparison.units_display)
    if units_a != units_b:
        return '', 'Different units; no conversion applied'
    a, b = clean(baseline.result_text), clean(comparison.result_text)
    if not re.fullmatch(NUMBER, a) or not re.fullmatch(NUMBER, b):
        return '', 'Text, interval or qualified result; no numeric change'
    delta = Decimal(b) - Decimal(a)
    value = format(delta, 'f').rstrip('0').rstrip('.') if '.' in format(delta, 'f') else str(delta)
    value = '0' if delta == 0 else ('+' if delta > 0 else '') + value
    return value + (' ' + units_b if units_b else ''), ''


def comparison_frame(frame, baseline_id, comparison_id):
    """Outer match by explicit panel family and test key, never test name alone.

    Ambiguous duplicate keys are shown separately rather than paired arbitrarily.
    Unknown panel names match only their own normalized name.
    """
    def groups(collection):
        grouped = {}
        for row in frame[frame.collection_id == collection].itertuples():
            grouped.setdefault((panel_family(row.panel_name), row.test_key), []).append(row)
        return grouped
    baseline, comparison = groups(baseline_id), groups(comparison_id)
    output = []

    def append(key, a, b, note=''):
        row = {'Panel': key[0], 'Test': (b if b is not None else a).test_name}
        for prefix, source in [('Baseline', a), ('Comparison', b)]:
            if source is None:
                result, reference, status = 'Not in collection', '', 'Not in collection'
            else:
                units = clean(source.units_display)
                result = clean(source.result_text) + (' ' + units if units else '')
                reference = clean(source.reference_text)
                status = range_status(source.result_text, reference)
            row.update({prefix+' result': result, prefix+' range': reference, prefix+' status': status})
        change, change_note = result_change(a, b)
        row.update({'Change': change, 'Note': note or change_note})
        output.append(row)

    for key in dict.fromkeys([*baseline, *comparison]):
        left, right = baseline.get(key, []), comparison.get(key, [])
        if len(left) > 1 or len(right) > 1:
            for a in left:
                append(key, a, None, 'Multiple results for this test; not automatically matched')
            for b in right:
                append(key, None, b, 'Multiple results for this test; not automatically matched')
        else:
            append(key, left[0] if left else None, right[0] if right else None)
    return pd.DataFrame(output)
