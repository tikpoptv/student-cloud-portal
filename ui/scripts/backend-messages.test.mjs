import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
// Coverage test: every Thai message the Python side can show a student as an error/warning needs an English entry in locales/en.json.
const root=fileURLToPath(new URL('../../',import.meta.url));
const script=`
import ast,json,sys,re
THAI=re.compile('[\\u0e00-\\u0e7f]')
out=set()
def strings(node):
    # Thai plain string constants inside an expression; f-strings are dynamic and skipped.
    if isinstance(node,ast.JoinedStr):return
    if isinstance(node,ast.Constant) and isinstance(node.value,str) and THAI.search(node.value):out.add(node.value);return
    for child in ast.iter_child_nodes(node):strings(child)
def is_warnings(n):
    return isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Constant) and n.slice.value=='warnings'
for path in sys.argv[1:]:
    tree=ast.parse(open(path,encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node,ast.Call):
            f=node.func;name=f.id if isinstance(f,ast.Name) else f.attr if isinstance(f,ast.Attribute) else ''
            if name in ('ValueError','RuntimeError','PermissionError'):[strings(a) for a in node.args]
            elif name=='abort':[strings(a) for a in node.args[1:]]
            elif name in ('append','insert') and isinstance(f,ast.Attribute) and is_warnings(f.value):[strings(a) for a in node.args]
            for kw in node.keywords:
                if kw.arg in ('error','error_source'):strings(kw.value)
        elif isinstance(node,ast.Assign) and any(is_warnings(t) for t in node.targets):strings(node.value)
print(json.dumps(sorted(out),ensure_ascii=False))
`;
test('every Thai backend error/warning message has an English translation',()=>{
 const files=['repo_review.py','app.py','chat.py'].map(f=>root+f);
 const run=spawnSync('python3',['-I','-c',script,...files],{encoding:'utf8',timeout:30000});
 assert.equal(run.status,0,run.stderr);
 const found=JSON.parse(run.stdout);
 assert.ok(found.length>10,'extractor should find the known messages');
 const messages=JSON.parse(fs.readFileSync(root+'locales/en.json','utf8'));
 const missing=found.filter(m=>messages[m.trim()]===undefined);
 assert.deepEqual(missing,[],'missing from locales/en.json:\n'+missing.join('\n'));
 for(const m of found)assert.doesNotMatch(messages[m.trim()],/[ก-๙]/,m);
});
