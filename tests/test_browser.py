"""Real UI acceptance against a temporary local workspace, without running analyses."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import pytest

pytestmark = pytest.mark.skipif(os.environ.get('VIRALOGIX_BROWSER_TESTS') != '1', reason='Enable browser acceptance with VIRALOGIX_BROWSER_TESTS=1')


def test_workspace(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    repo = Path(__file__).parents[1]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    from viralogix.store import Store
    from test_pipeline_manager import attached
    store=Store(tmp_path / 'workspace')
    attached(store)
    from test_updates import release
    from viralogix.updates import release_record
    store.put('app_catalog','releases',{'checked_at':'TEST FIXTURE','releases':[release_record(release())]})
    env = {**os.environ, 'VIRALOGIX_HOME': str(tmp_path / 'workspace')}
    log = (tmp_path / 'server.log').open('w')
    proc = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(repo/'src/viralogix/app.py'), '--server.port', str(port), '--server.address', '127.0.0.1', '--server.headless', 'true', '--browser.gatherUsageStats', 'false'], env=env, stdout=log, stderr=subprocess.STDOUT)
    artifacts = repo / 'browser-artifacts'
    artifacts.mkdir(exist_ok=True)
    try:
        url = f'http://127.0.0.1:{port}'
        for _ in range(100):
            try:
                with urlopen(url + '/_stcore/health', timeout=1): break
            except OSError: time.sleep(.2)
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--no-sandbox'])
            page = browser.new_page(viewport={'width':1440,'height':1000}, device_scale_factor=1)
            errors=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url)
            expect(page.locator('#queue-status')).to_have_text('No active jobs',timeout=30000)
            nav=page.locator('#navigation')
            expected=['Overview','Samples','Runs','Comparisons','Jobs & progress','Results & reports','Install & update','Databases & models','Configuration','Storage']
            assert nav.get_by_role('link').all_text_contents()==expected
            for name in expected:
                nav.get_by_role('link',name=name,exact=True).click()
                expect(page.locator('#main h1')).to_be_visible()
                expect(page.locator('#main')).not_to_contain_text('Traceback')
            nav.get_by_role('link',name='Install & update',exact=True).click()
            for name in ['Guided setup','Pipelines & environments','PC capacity','Workstation check','Compatibility']:
                page.get_by_role('button',name=name,exact=True).click()
                expect(page.locator('#main h1')).to_be_visible()
                page.screenshot(path=str(artifacts/('setup-'+name.split()[0]+'.png')),full_page=True)
            page.locator('.topbar [data-action="app-updates"]').click()
            expect(page.get_by_role('dialog')).to_be_visible()
            expect(page.get_by_role('dialog')).to_contain_text('99.0.0a1')
            page.screenshot(path=str(artifacts/'updates-desktop.png'),full_page=True)
            page.locator('[data-action="close"]').first.click()
            nav.get_by_role('link',name='Samples',exact=True).click()
            page.locator('[data-action="new-sample"]').first.click()
            page.get_by_label('Sample ID',exact=True).fill('UI.fixture')
            page.get_by_label('Input folder',exact=True).fill(os.environ['FLUPOP_TEST_SOURCE']+'/examples')
            page.get_by_role('button',name='Browse folders',exact=True).click()
            page.get_by_role('button',name='Select this folder',exact=True).click()
            page.get_by_role('button',name='Register sample',exact=True).click()
            expect(page.get_by_role('heading',name='Your input folders.',exact=True)).to_be_visible()
            page.locator('[data-action="sample-draft"]').first.click()
            expect(page.get_by_role('heading',name='Create run drafts',exact=True)).to_be_visible()
            page.locator('#run-cores').fill('1')
            page.locator('#run-memory').fill('1024')
            page.get_by_role('button',name='Continue to settings',exact=True).click()
            page.locator('[data-action="run-setting-group"][data-id="Report options"]').click()
            expect(page.locator('[data-run-name="synthetic_demo"]')).to_be_visible()
            page.locator('[data-run-name="synthetic_demo"]').check()
            page.get_by_role('button',name='Save & exit',exact=True).click()
            page.reload()
            expect(page.get_by_role('button',name='Resume editing',exact=True)).to_be_visible(timeout=30000)
            page.get_by_role('button',name='Resume editing',exact=True).click()
            page.get_by_role('button',name='Review drafts',exact=True).click()
            page.get_by_role('button',name='Create drafts',exact=True).click()
            expect(page.get_by_role('heading',name='Your saved run',exact=True)).to_be_visible(timeout=30000)
            assert not store.jobs()
            page.screenshot(path=str(artifacts/'run-desktop.png'),full_page=True)
            # Validate and execute through the actual shared request bridge.
            rid=store.all('runs')[0]['id']
            page.locator('[data-action="dry-run"]').first.click()
            from test_pipeline_manager import wait
            for _ in range(100):
                if store.jobs():break
                time.sleep(.1)
            assert wait(store,store.jobs()[0]['id'])['status']=='succeeded'
            nav.get_by_role('link',name='Runs',exact=True).click()
            page.locator('[data-action="run-detail"][data-id="'+rid+'"]').first.click()
            page.locator('[data-action="run"]').first.click()
            for _ in range(100):
                if len(store.jobs())>=2:break
                time.sleep(.1)
            assert wait(store,store.jobs()[0]['id'])['status']=='succeeded'
            page.locator('[data-action="refresh"]').first.click()
            nav.get_by_role('link',name='Results & reports',exact=True).click()
            expect(page.locator('#main')).to_contain_text('Viral Cloud',timeout=30000)
            page.locator('[data-action="open-report"]').first.click()
            expect(page.frame_locator('.html-report-frame').get_by_role('heading',name='Viral Cloud',exact=True)).to_be_visible()
            page.locator('[data-action="close"]').first.click()
            for action in ['about','get-support','app-window-help']:
                page.locator('[data-action="'+action+'"]').first.evaluate('(el)=>el.click()')
                expect(page.get_by_role('dialog')).to_be_visible()
                page.locator('[data-action="close"]').first.click()
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_role('button',name='Open navigation',exact=True).click()
            nav.get_by_role('link',name='Overview',exact=True).click()
            expect(page.locator('.nav-scrim')).to_be_hidden()
            page.screenshot(path=str(artifacts/'overview-mobile.png'),full_page=True)
            assert page.locator('.bacto-root').evaluate('(el)=>el.scrollWidth <= 390')
            assert not errors
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        log.close()
