"""Check the bounded, connector-fetched course sheet snapshot against approved teams.

The public-editable issue sheet never grants access directly. Import remains a TA action.
"""
import json
import os
import re
from pathlib import Path
from app import create_app, normalize_email

SHEET_ID=os.environ.get('COURSE_SHEET_ID','')  # set to the course sheet's ID; intentionally not committed
TAB='summary_clear'

def reviewed_rows(snapshot):
    if snapshot.get('spreadsheet_id')!=SHEET_ID or snapshot.get('sheet_name')!=TAB:
        raise ValueError('Unexpected course sheet or tab')
    values=snapshot['values']
    if not values or len(values[0])!=4 or not values[0][0].startswith('ชื่อกลุ่ม') or 'email' not in values[0][3].lower():
        raise ValueError('Unexpected roster headers')
    rows={}
    for row in values[1:]:
        if not any(row):continue
        if len(row)!=4 or not row[0].strip():raise ValueError('Invalid roster row')
        email=normalize_email(row[3])
        if not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@gmail\.com',email) or email in rows:
            raise ValueError('Missing, invalid or duplicate team email')
        rows[email]=row[0].strip()
    if not rows:raise ValueError('Empty roster')
    return rows

def compare_roster(app,snapshot):
    expected=reviewed_rows(snapshot)
    with app.db() as conn:
        actual={r['email']:r['name'].strip() for r in conn.execute('SELECT email,name FROM teams WHERE demo=0 AND enabled=1')}
    return {'sheet_teams':len(expected),'approved_teams':len(actual),
            'pending_additions':len(expected.keys()-actual.keys()),
            'absent_from_sheet':len(actual.keys()-expected.keys()),
            'name_changes':sum(actual[e]!=expected[e] for e in expected.keys()&actual.keys())}

if __name__=='__main__':
    report=compare_roster(create_app(),json.loads(Path('private/roster-current.json').read_text()))
    print(json.dumps(report))
    if report['pending_additions'] or report['absent_from_sheet'] or report['name_changes']:
        raise SystemExit('TA review required; no access or identity changes applied.')
