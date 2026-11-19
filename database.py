"""Persistent PostgreSQL for hosting; SQLite remains the local preview store."""
import re
import sqlite3

class PostgresConnection:
    def __init__(self,url):
        import psycopg
        from psycopg.rows import dict_row
        self.connection=psycopg.connect(url,row_factory=dict_row,connect_timeout=15)
    def __enter__(self):
        self.connection.__enter__();return self
    def __exit__(self,*args):
        return self.connection.__exit__(*args)
    def execute(self,sql,params=()):
        if sql=='BEGIN IMMEDIATE':
            # Match SQLite's serialized writer transaction for identity binding and job leases.
            return self.connection.execute('SELECT pg_advisory_xact_lock(3342026)')
        if sql.startswith('INSERT OR IGNORE INTO'):
            sql=sql.replace('INSERT OR IGNORE INTO','INSERT INTO',1)+' ON CONFLICT DO NOTHING'
        sql=sql.replace('?','%s')
        if isinstance(params,dict):sql=re.sub(r':([a-z_]+)',r'%(\1)s',sql)
        return self.connection.execute(sql,params)
    def executescript(self,sql):
        for statement in sql.split(';'):
            if not statement.strip() or statement.strip().startswith('PRAGMA'):continue
            statement=statement.replace('id INTEGER PRIMARY KEY AUTOINCREMENT','id BIGSERIAL PRIMARY KEY')
            if 'CREATE TABLE IF NOT EXISTS events' in statement:
                statement=statement.replace('id INTEGER PRIMARY KEY','id BIGSERIAL PRIMARY KEY')
            self.execute(statement)

def connect(path,url=''):
    if url:return PostgresConnection(url)
    conn=sqlite3.connect(path,timeout=15);conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON');return conn
