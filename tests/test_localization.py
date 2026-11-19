from app import create_app
from localization import localize_payload, translate


def test_language_selection_and_english_error_pages(tmp_path):
    app=create_app({'DATABASE':str(tmp_path/'locale.sqlite3'),'SECRET_KEY':'test','TESTING':True,'PREVIEW':True})
    c=app.test_client()
    page=c.get('/?lang=en')
    assert b'<html lang="en"' in page.data
    assert b'Please enable JavaScript' in page.data
    assert page.headers['Content-Language']=='en'
    error=c.get('/api/status',headers={'Accept-Language':'en'})
    assert error.status_code==401
    assert error.headers['Content-Language']=='en'
    assert not any('\u0e00' <= ch <= '\u0e7f' for ch in error.json['error'])
    c.set_cookie('portal_lang','en')
    assert c.get('/').headers['Content-Language']=='en'
    assert c.get('/?lang=th').headers['Content-Language']=='th'
    assert b'Unable to continue' in c.get('/missing').data


def test_localizing_review_preserves_raw_code_and_student_identity():
    source={'warnings':['ยังไม่มีการสร้างทรัพยากรหรือใช้เครดิต Google Cloud'],
            'changes':[{'diff':'+echo "รายการ"','after':'echo "รายการ"'}],
            'team':{'name':'กลุ่มทดลอง'},'repo':'team/main',
            'findings':[{'name':'รายการ','value':'ชื่อแอปของกลุ่ม'}]}
    result=localize_payload(source,'en')
    assert result['warnings']!=source['warnings']
    assert result['changes']==source['changes']
    assert result['team']==source['team']
    assert result['repo']==source['repo']
    assert result['findings'][0]['name']=='Item'
    assert result['findings'][0]['value']==source['findings'][0]['value']
    assert translate('ออกจากระบบ','th')=='ออกจากระบบ'
