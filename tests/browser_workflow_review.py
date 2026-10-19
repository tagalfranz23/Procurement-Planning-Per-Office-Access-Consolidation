"""Browser integration review with an isolated in-memory database and fake offices.

Run explicitly with the project interpreter. No live database is opened or seeded.
"""
import base64
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['FLASK_SECRET_KEY'] = 'isolated-browser-workflow-only'
os.environ['WEBSOCKET_URL'] = ''
from tests.test_workflow_app import ConsolidatedAPPWorkflowTest
from tests.browser_cdp import CDP
import app as application
from models import College, IndicativePPMPCopy, PPMPOrder, User, db
from werkzeug.serving import WSGIRequestHandler, make_server

ARTIFACTS = ROOT / 'backups' / 'revised-workflow-review'
ARTIFACTS.mkdir(parents=True, exist_ok=True)

class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


fixture = ConsolidatedAPPWorkflowTest()
fixture.setUp()
source1 = fixture.source('CBAO', quantity='4', budget='1000.00')
source2 = fixture.source('CASHIER', quantity='6', budget='1500.00')
plan = fixture.plan([source1, source2])
fixture.complete(plan['id'])
fixture.transition(plan['id'], 'ADMIN', 'submit')
fixture.transition(plan['id'], 'BAC CHAIRMAN', 'approve')
late_office = College(code='CAS', name='College of Arts and Sciences', is_active=True)
db.session.add(late_office)
db.session.flush()
late_user = User(username='browser_cas', full_name='CAS User', email='cas@example.test',
                password_hash='unused', role='CAS', office='CAS', college_id=late_office.id,
                account_status='ACTIVE', is_active=True)
db.session.add(late_user)
db.session.commit()
fixture.users['CAS'] = late_user
fixture.source('CAS', title='Ergonomic chair', quantity='1', budget='300.00', unit='piece')
legacy = PPMPOrder(reference_number='BROWSER-LEGACY-2029', office_id=fixture.users['CBAO'].college_id,
                   requested_by=fixture.users['CBAO'].id, fiscal_year=2029, status='Requested')
db.session.add(legacy)
db.session.commit()
legacy_id = legacy.id
official_id = PPMPOrder.query.filter_by(office_id=fixture.users['CBAO'].college_id, fiscal_year=2027).one().id
fixture.login('CBAO')
copy_response = fixture.client.post(f'/api/ppmp-orders/{official_id}/indicative-copy', json={})
assert copy_response.status_code == 201, copy_response.get_json()
copy_id = copy_response.get_json()['id']

server = make_server('127.0.0.1', 5917, application.app, request_handler=QuietHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
browser = subprocess.Popen([
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=5918', '--remote-allow-origins=*', '--window-size=1600,1100',
    '--user-data-dir=' + str(ARTIFACTS / 'edge-profile'), 'about:blank',
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
checks = []
try:
    pages = []
    for _ in range(80):
        try:
            pages = json.load(urllib.request.urlopen('http://127.0.0.1:5918/json', timeout=1))
            if pages:
                break
        except OSError:
            time.sleep(.15)
    if not pages:
        raise RuntimeError('Headless Edge did not start.')
    cdp = CDP(next(page['webSocketDebuggerUrl'] for page in pages if page['type'] == 'page'))
    cdp.call('Runtime.enable')
    cdp.call('Network.enable')

    def check(label, expression):
        value = cdp.evaluate(expression)
        checks.append({'check': label, 'passed': value is True, 'value': value})
        if value is not True:
            raise AssertionError(f'{label}: {value!r}')
        print('PASS:', label, flush=True)

    def navigate(role):
        # Cancel the previous account's requests before changing its cookie.
        # Flask can renew a session cookie on a response already in flight.
        cdp.call('Page.navigate', {'url': 'about:blank'})
        cdp.wait_for('location.href === "about:blank" && document.readyState === "complete"')
        cdp.call('Network.clearBrowserCookies')
        user = fixture.users[role]
        serializer = application.app.session_interface.get_signing_serializer(application.app)
        token = serializer.dumps({'user_id': user.id, 'role': user.role, 'auth_version': user.auth_version or 0})
        cdp.call('Network.setCookie', {'name': application.app.config['SESSION_COOKIE_NAME'],
            'value': token, 'url': 'http://127.0.0.1:5917/', 'httpOnly': True, 'sameSite': 'Lax'})
        cdp.call('Page.navigate', {'url': 'http://127.0.0.1:5917/'})
        cdp.wait_for(f'typeof currentUser !== "undefined" && currentUser?.role === {json.dumps(role)}')
        if role != 'ADMIN':
            expected_panel = 'ppmp-dashboard' if role in {'CBAO', 'CASHIER', 'CAS'} else 'workspace-choice'
            cdp.wait_for(f'document.getElementById("panel-{expected_panel}")?.classList.contains("active")')

    def screenshot(filename):
        result = cdp.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
        (ARTIFACTS / filename).write_bytes(base64.b64decode(result['data']))

    navigate('ADMIN')
    check('Rendered template scripts parse', """(() => { for (const s of document.scripts) if (!s.src && s.textContent.trim()) new Function(s.textContent); return true; })()""")
    cdp.evaluate(f'window.confirm = () => true; await designateOfficialPPMP({legacy_id},{{disabled:false}});')
    check('Admin can designate a historical official PPMP', f'return await (async () => {{ const orders=await apiFetch("/api/ppmp-orders"); return orders.some(o => o.id === {legacy_id} && o.workflow_official && o.status === "Draft"); }})()')
    cdp.evaluate("showPanel('apps');")
    cdp.wait_for('appPlans.length > 0')
    cdp.evaluate(f"await openAPP({plan['id']},false);")
    check('Admin sees merged institution APP', "selectedAPPRecord.office.includes('OFFICES') && appItems().length === 1 && appItems()[0].contributions.length === 2")
    check('Merged quantities and budgets reconcile', 'appItems()[0].quantity === 10 && selectedAPPRecord.totals.overall === 2500')
    check('APP next reviewer is Budget after BAC', "selectedAPPRecord.expected_reviewer === 'BUDGET'")
    screenshot('admin-consolidated-app.png')
    cdp.evaluate('openAPPContributions(appItems()[0].id);')
    check('Contribution modal retains two offices', "document.querySelectorAll('#app-contribution-list [data-contribution-id]').length === 2")
    screenshot('office-contributions.png')
    cdp.evaluate('closeAPPContributions();')
    cdp.evaluate("showPanel('consolidation'); await renderConsolidation();")
    check('Admin sees late office eligible source', "document.querySelectorAll('input[name=consolidation-item]').length === 1")
    screenshot('admin-consolidation.png')
    cdp.evaluate("toggleConsolidationItems(true); await createConsolidationBatch({disabled:false});")
    cdp.evaluate("await generateAPPFromBatch(consolidationBatches.find(b => !b.app_id).id, {disabled:false});")
    cdp.evaluate(f"await openAPP({plan['id']},false);")
    check('Late batch preserves Budget reviewer', "selectedAPPRecord.expected_reviewer === 'BUDGET' && appItems().length === 2")
    cdp.evaluate("openAPPItemModal(appItems().find(i => i.is_pending_completion).id); document.getElementById('app-item-early').value='No'; document.getElementById('app-item-criteria').value='Lowest calculated responsive bid'; await saveAPPItem({disabled:false});")
    check('Admin can complete late row during review', "appItems().every(i => !i.is_pending_completion) && selectedAPPRecord.expected_reviewer === 'BUDGET'")
    cdp.evaluate("document.body.classList.add('print-app');")
    app_pdf = cdp.call('Page.printToPDF', {'printBackground': True, 'landscape': True, 'preferCSSPageSize': True})
    (ARTIFACTS / 'app-print-preview.pdf').write_bytes(base64.b64decode(app_pdf['data']))
    cdp.evaluate("document.body.classList.remove('print-app');")

    navigate('CBAO')
    cdp.evaluate("showPanel('ppmp-request-records');")
    cdp.evaluate(f'await openPPMPRequestReport({official_id},true);')
    check('Approved PPMP is locked for its creator', "selectedPPMPRequestReport.status === 'Approved' && !selectedPPMPRequestReport.editable && document.getElementById('ppmp-report-edit-controls').hidden")
    screenshot('approved-official-ppmp.png')
    cdp.evaluate(f'await openIndicativeCopy({copy_id});')
    cdp.evaluate('editPPMPRequestReport();')
    check('Independent indicative copy is editable', "selectedPPMPRequestReport.source_type === 'indicative' && !document.querySelector('#ppmp-request-report-items [data-report-field=quantity]').disabled")
    cdp.evaluate("document.querySelector('#ppmp-request-report-items [data-report-field=remarks]').value = 'Independent copy edited in browser';")
    cdp.evaluate('await savePPMPRequestReport();')
    check('Copy save persisted separately', "selectedPPMPRequestReport.items[0].remarks === 'Independent copy edited in browser'")
    screenshot('editable-indicative-copy.png')
    cdp.evaluate('preparePPMPPrintValues();')
    ppmp_pdf = cdp.call('Page.printToPDF', {'printBackground': True, 'landscape': True, 'preferCSSPageSize': True})
    (ARTIFACTS / 'ppmp-print-preview.pdf').write_bytes(base64.b64decode(ppmp_pdf['data']))

    cdp.evaluate("showPanel('cse-selected-items'); document.getElementById('order-year').value='2028'; document.getElementById('order-quarter').selectedIndex=1; orderDraftItems=[{item_name:'Browser draft item',category:'Goods',unit:'piece',quantity:2,estimated_unit_cost:10,is_custom_item:true}]; renderOrderDraft(); await submitPPMPOrder(document.getElementById('submit-order-button'));")
    check('Selected Items creates and opens official draft', "selectedPPMPRequestReport?.status === 'Draft' && selectedPPMPRequestReport.is_official")
    cdp.evaluate("editPPMPRequestReport(); const values={project_type:'Goods/Services',procurement_method:'Small Value Procurement',pre_procurement_conference:'No',source_of_funds:'GAA/101',procurement_start:'2028-01',procurement_end:'2028-02',delivery_period:'2028-03'}; for (const [key,value] of Object.entries(values)) document.querySelector('[data-report-field='+key+']').value=value; await savePPMPRequestReport();")
    screenshot('official-draft-ready-to-submit.png')
    cdp.evaluate('window.confirm = () => true; await submitOpenPPMPReport({disabled:false});')
    check('UI submission reaches Procurement and locks edit', "selectedPPMPRequestReport.status === 'Submitted' && !selectedPPMPRequestReport.editable")

    navigate('PROCUREMENT')
    check('Procurement has no consolidation navigation', "!document.getElementById('consolidation-nav') || getComputedStyle(document.getElementById('consolidation-nav')).display === 'none' || document.getElementById('consolidation-nav').hidden")
    navigate('BUDGET')
    cdp.evaluate("showPanel('apps');")
    cdp.evaluate(f"await openAPP({plan['id']},false);")
    check('Budget has review actions', "document.getElementById('selected-app-actions').textContent.includes('Approve')")
    screenshot('budget-review.png')

    from PyPDF2 import PdfReader
    for filename in ('app-print-preview.pdf', 'ppmp-print-preview.pdf'):
        reader = PdfReader(str(ARTIFACTS / filename))
        content = ' '.join(page.extract_text() or '' for page in reader.pages)
        if filename.startswith('app-'):
            assert 'Printer paper' in content and '2,800' in content and 'CBAO' in content, content
        else:
            assert 'Printer paper' in content and 'TOTAL BUDGET' in content, content
    checks.append({'check': 'Both browser print previews contain report data and totals', 'passed': True, 'value': True})

    exceptions = [event for event in cdp.events if event.get('method') == 'Runtime.exceptionThrown']
    if exceptions:
        raise AssertionError(json.dumps(exceptions, indent=2))
    print(json.dumps({'checks': checks, 'screenshots': str(ARTIFACTS)}, indent=2))
finally:
    (ARTIFACTS / 'browser-results.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    server.shutdown()
    browser.terminate()
    fixture.tearDown()
