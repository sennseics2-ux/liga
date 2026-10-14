"""Bundled ISO 3166-1 choices; names remain compatible with stored profiles.

countries.json derives from Debian iso-codes (LGPL-2.1-or-later), with Kosovo
added for the KOS FIDE federation using the customary XK code. Its country
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

# FIDE uses IOC-style codes, which often differ from ISO alpha-3 (POR/PRT,
# GER/DEU, NGR/NGA). England, Scotland and Wales share the GB country choice.
_FIDE_ISO = dict(pair.split(':') for pair in '''
ALG:DZ ANG:AO ANT:AG ARU:AW BAH:BS BAN:BD BAR:BB BER:BM BHU:BT BIZ:BZ
BOT:BW BRN:BH BRU:BN BUL:BG BUR:BF CAM:KH CAY:KY CHA:TD CHI:CL CRC:CR
CRO:HR CUR:CW DEN:DK ENG:GB ESA:SV FAI:FO FIJ:FJ GAM:GM GCI:GG GEQ:GQ GER:DE
GRE:GR GRN:GD GUA:GT GUI:GN HAI:HT HON:HN INA:ID IOM:IM IRI:IR ISV:VI
IVB:VG JCI:JE KOS:XK KSA:SA KUW:KW LAT:LV LBA:LY LES:LS MAD:MG MAS:MY MAW:MW MGL:MN
MNC:MC MRI:MU MTN:MR MYA:MM NCA:NI NED:NL NEP:NP NGR:NG NIG:NE OMA:OM
PAR:PY PHI:PH PLE:PS POR:PT PUR:PR ROM:RO RSA:ZA SCO:GB SEY:SC SKN:KN
SLO:SI SOL:SB SRI:LK SUD:SD SUI:CH SWZ:SZ TAN:TZ TGA:TO TOG:TG TPE:TW
UAE:AE URU:UY VAN:VU VIE:VN VIN:VC WLS:GB ZAM:ZM ZIM:ZW
'''.split())


def federation_country(code):
    """Map a FIDE federation to a stored country; neutral/unknown codes have none."""
    code=str(code or '').strip().upper()
    if len(code)!=3 or not code.isascii() or not code.isalpha():
        return None
    return _ALIASES.get(_FIDE_ISO.get(code,code).casefold())


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
