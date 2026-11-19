"""Import the reviewed one-email-per-team tab from the course sheet export."""
import csv
import hashlib
import io
import re
import sys
from app import create_app, normalize_email


def parse_roster(text):
    # Connector exports sheets separated by a form feed. Use the prepared one-email tab.
    tabs = text.split('\f')
    if len(tabs) < 2:
        raise ValueError('Expected the reviewed one-email roster tab')
    rows = list(csv.reader(io.StringIO(tabs[1].lstrip())))
    result, seen = [], set()
    for row in rows[1:]:
        if not row or not row[0].isdigit():
            continue
        if len(row) != 5:
            raise ValueError('Unexpected roster columns; review source first')
        name, email = row[1].strip(), normalize_email(row[4])
        if not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@gmail\.com', email):
            raise ValueError('Roster requires one valid Gmail per team')
        if email in seen:
            raise ValueError('An email belongs to multiple teams; resolve manually')
        seen.add(email)
        key = hashlib.sha256(email.encode()).hexdigest()[:12]
        # Stable course prefix, independent of student-ID duplicates in the submitted sheet.
        result.append({'id':key,'name':name,'email':email,'prefix':'s'+key[:8]})
    if not result:
        raise ValueError('No approved rows found')
    return result


def main():
    from pathlib import Path
    path = Path(sys.argv[1] if len(sys.argv)>1 else 'private/roster-source.txt')
    teams = parse_roster(path.read_text())
    app = create_app()
    with app.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for team in teams:
            conn.execute('INSERT OR IGNORE INTO teams(id,name,email,prefix) VALUES(:id,:name,:email,:prefix)', team)
        # Never silently transfer identities, regenerate prefixes, remove a team, or change jobs on reimport.
        for team in teams:
            actual = conn.execute('SELECT id,email,prefix FROM teams WHERE id=?', (team['id'],)).fetchone()
            if not actual or actual['email'] != team['email'] or actual['prefix'] != team['prefix']:
                raise ValueError('Roster conflict requires TA review')
    path.chmod(0o600)
    path.parent.chmod(0o700)
    print(f'Imported {len(teams)} teams. No personal data printed. Existing activations preserved.')


if __name__ == '__main__':
    main()
