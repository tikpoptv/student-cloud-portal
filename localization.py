"""Shared UI/API message catalogue. Repository code/diffs and identities are never translated."""
import json
import re
from pathlib import Path
MESSAGES=json.loads((Path(__file__).parent/'locales/en.json').read_text())
PATTERN=re.compile('|'.join(re.escape(k) for k in sorted(MESSAGES,key=len,reverse=True)))


def language_for_request(request):
    query=request.args.get('lang')
    if query in ('en','th'):return query
    cookie=request.cookies.get('portal_lang')
    if cookie in ('en','th'):return cookie
    return request.accept_languages.best_match(['th','en']) or 'th'


def translate(text,language='th'):
    if language!='en' or not isinstance(text,str):return text
    return PATTERN.sub(lambda m:MESSAGES[m.group()],text)


def localize_payload(value,language,path=()):
    if isinstance(value,dict):
        return {k:localize_payload(v,language,path+(k,)) for k,v in value.items()}
    if isinstance(value,list):return [localize_payload(v,language,path) for v in value]
    if isinstance(value,str) and path:
        key=path[-1]
        if key in ('error','notice','summary','detail','warnings','next_steps') or (key=='name' and 'findings' in path):
            return translate(value,language)
    return value
