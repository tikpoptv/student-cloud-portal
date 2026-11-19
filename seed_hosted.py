"""One-time migration of approved identities to the hosted PostgreSQL database."""
import json
import sqlite3
from pathlib import Path
from app import create_app
from database import connect


def migrate(source_path,target_url):
    source=sqlite3.connect(source_path);source.row_factory=sqlite3.Row
    source.execute('BEGIN')
    teams=[dict(r) for r in source.execute('SELECT * FROM teams WHERE demo=0')]
    app=create_app({'DATABASE_URL':target_url,'AUTH_MODE':'google','SECRET_KEY':'migration-only','PREVIEW':True,'BASE_URL':'https://migration.invalid'})
    counts={}
    with app.db() as target:
        target.execute('BEGIN IMMEDIATE')
        for team in teams:
            existing=target.execute('SELECT * FROM teams WHERE id=? OR email=? OR prefix=?',(team['id'],team['email'],team['prefix'])).fetchone()
            if existing:
                if any(existing[k]!=team[k] for k in ('id','email','prefix','name','enabled','google_sub')):
                    raise ValueError('Existing identity differs; TA review required')
                continue
            cols=list(team);target.execute('INSERT INTO teams('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',tuple(team.values()))
        # No live team work should be silently discarded during initial migration.
        for table in ('activations','repo_reviews','events'):
            rows=[dict(r) for r in source.execute(f'SELECT * FROM {table} WHERE team_id IN (SELECT id FROM teams WHERE demo=0)')]
            if rows:raise ValueError('Existing non-demo work requires a separate migration plan')
        counts['approved_teams']=len(teams)
    source.close()
    return counts

if __name__=='__main__':
    from urllib.parse import quote
    private=json.loads(Path('private/hosted-secrets.json').read_text())
    url='postgresql://portal:'+quote(private['database_password'],safe='')+'@127.0.0.1:55440/portal'
    print(json.dumps(migrate('private/portal.sqlite3',url)))
