"""Bundled ISO 3166-1 choices; names remain compatible with stored profiles.

countries.json derives from Debian iso-codes (LGPL-2.1-or-later). Its ISO
codes and English/Portuguese names are kept locally, with no runtime lookup.
"""
import json
from pathlib import Path

_ROWS = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
COUNTRIES = tuple(row['name'] for row in _ROWS)
_ALIASES = {
    alias.casefold(): row['name']
    for row in _ROWS
    for alias in [row['name'], row['code'], *row['aliases']]
}
_ALIASES['uk'] = 'United Kingdom'
_CODES = {row['name']: row['code'].lower() for row in _ROWS}


def country_field(current):
    """Match existing text without losing an unrecognized legacy country."""
    current = str(current or '').strip()
    selected = _ALIASES.get(current.casefold(), current)
    return {
        'countries': COUNTRIES,
        'selected_country': selected,
        'legacy_country': current if current and selected not in COUNTRIES else None,
    }


def country_code(value):
    """Return a recognized ISO code for local flags, or None for unknown text."""
    name = _ALIASES.get(str(value or '').strip().casefold())
    return _CODES.get(name)
