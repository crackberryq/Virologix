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
            expect(page.get_by_role('heading', name='Pick up where you left off.')).to_be_visible(timeout=30000)
            page.screenshot(path=str(artifacts/'overview-desktop.png'), full_page=True)
            nav = page.locator('#navigation')
            nav.get_by_role('link', name='Samples').click()
            page.get_by_role('button',name='Add sample',exact=True).click()
            read = tmp_path/'input.fastq'
            read.write_text('@fixture\nA\n+\nI\n')
            page.get_by_label('Sample ID', exact=True).fill('UI.fixture')
            page.get_by_label('Sample folder', exact=True).fill(str(tmp_path))
            page.get_by_role('button',name='Browse folders',exact=True).click()
            expect(page.get_by_role('dialog')).to_be_visible()
            page.get_by_role('button',name='Use this folder',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            page.get_by_role('button',name='Add sample',exact=True).click()
            expect(page.get_by_text('Sample registered. Input files remain in their original locations.')).to_be_visible()
            expect(page.locator('#sample-results')).to_contain_text('UI.fixture')
            page.get_by_label('Search samples').fill('missing')
            expect(page.locator('#sample-results')).to_contain_text('No samples to display')
            page.get_by_label('Search samples').fill('UI.fixture')
            expect(page.locator('#sample-results')).to_contain_text('UI.fixture')
            page.screenshot(path=str(artifacts/'samples-desktop.png'), full_page=True)
            assert nav.get_by_role('link').all_text_contents() == ['Overview','Samples','Runs','Comparisons','Jobs & progress','Results & reports','Install & update','Databases & models','Configuration','Storage']
            page.get_by_role('button',name='Create draft',exact=True).click()
            expect(page.get_by_label('Sample',exact=True)).to_have_value('UI.fixture')
            page.get_by_label('Run name',exact=True).fill('Unfinished test')
            nav.get_by_role('link',name='Overview',exact=True).click()
            page.reload()
            expect(page.get_by_role('button',name='Continue editing',exact=True)).to_be_visible(timeout=30000)
            page.get_by_role('button',name='Continue editing',exact=True).click()
            expect(page.get_by_label('Run name',exact=True)).to_have_value('Unfinished test')
            page.get_by_role('button',name='Discard unsaved edits',exact=True).click()
            nav.get_by_role('link',name='Overview',exact=True).click()
            page.get_by_role('button',name='Create synthetic demo draft',exact=True).click()
            page.get_by_label('Run name',exact=True).fill('Browser demo')
            page.get_by_role('button',name='Save draft',exact=True).click()
            expect(page.get_by_text('Run draft saved. No job has been started.')).to_be_visible()
            assert not store.jobs()
            page.screenshot(path=str(artifacts/'run-draft-desktop.png'),full_page=True)
            page.get_by_role('button',name='Run / resume',exact=True).click()
            expect(page.get_by_role('heading',name='Viral Cloud report',exact=True)).to_be_visible(timeout=60000)
            expect(page.frame_locator('#cloud-report').get_by_role('heading',name='Viral Cloud',exact=True)).to_be_visible()
            with page.expect_download() as cloud_download:
                page.get_by_role('button',name='Download report bundle',exact=True).click()
            from zipfile import ZipFile
            with ZipFile(cloud_download.value.path()) as archive:
                assert 'population.cfasta' in archive.namelist()
            nav.get_by_role('link',name='Results & reports',exact=True).click()
            page.get_by_role('button',name='Open report',exact=True).click()
            expect(page.get_by_text('Viral Cloud report opened.')).to_be_visible()
            nav.get_by_role('link',name='Configuration',exact=True).click()
            expect(page.get_by_text('viromics (standard installer environment)')).to_be_visible()
            page.get_by_role('button',name='Releases & updates').click()
            expect(page.get_by_role('heading',name='Install & update',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Check for updates',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Install v99.0.0a1',exact=True)).to_be_enabled()
            page.get_by_label('Release channel',exact=True).select_option('stable')
            expect(page.get_by_text('No releases in this channel.',exact=True)).to_be_visible()
            page.get_by_label('Release channel',exact=True).select_option('all')
            expect(page.get_by_role('button',name='Install v99.0.0a1',exact=True)).to_be_enabled()
            page.screenshot(path=str(artifacts/'updates-desktop.png'),full_page=True)
            expect(page.get_by_role('link',name='Open releases')).to_have_attribute('href','https://github.com/crackberryq/Virologix/releases')
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_role('button',name='Open navigation',exact=True).click()
            nav.get_by_role('link',name='Overview',exact=True).click()
            expect(page.get_by_role('heading',name='Pick up where you left off.')).to_be_visible()
            expect(page.locator('.nav-scrim')).to_be_hidden()
            page.screenshot(path=str(artifacts/'overview-mobile.png'), full_page=True)
            assert page.locator('.bacto-root').evaluate('(el)=>el.scrollWidth <= 390')
            page.get_by_role('button',name='Open navigation',exact=True).click()
            nav.get_by_role('link',name='Samples',exact=True).click()
            page.get_by_role('button',name='Add sample',exact=True).click()
            expect(page.get_by_label('Sample ID',exact=True)).to_be_visible()
            page.screenshot(path=str(artifacts/'samples-mobile.png'),full_page=True)
            assert page.locator('.bacto-root').evaluate('(el)=>el.scrollWidth <= 390')
            assert not errors
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        log.close()
