"""Native Ctrl+C copies the visible FEN while preserving normal editing copy."""
import os
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
import database as store
from test_league import client
from test_member_journey import chromium
pytestmark=pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS')!='1',reason='Enable Chromium checks.')

@pytest.mark.parametrize('width,theme',[(1280,'light'),(390,'dark')])
def test_native_fen_clipboard(chromium,client,width,theme):
    white=store.create_player('Copy White');black=store.create_player('Copy Black')
    game=store.create_game(white,black,'2026-10-01T12:00:00+00:00','Clipboard test')
    pgn='''[SetUp "1"]
[FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 10"]
[Result "*"]

10... e5 11. e4 Nf6 12. Nf3 *
'''
    with store.transaction() as db:db.execute('UPDATE games SET pgn_text=? WHERE id=?',(pgn,game))
    context=chromium.new_context(viewport={'width':width,'height':900},color_scheme=theme,permissions=['clipboard-read','clipboard-write'])
    context.add_init_script("localStorage.setItem('clubdraft.language','en')")
    def local_application(route):
        url=urlsplit(route.request.url)
        if url.netloc!='liga.test':route.abort();return
        response=client.get(url.path+('?' + url.query if url.query else ''))
        route.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/plain')})
    context.route('**/*',local_application)
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(f'https://liga.test/games/{game}')
        expected=page.locator('#replay-data').evaluate('(el)=>JSON.parse(el.textContent).positions')
        def copy_and_read():
            page.keyboard.press('Control+c')
            return page.evaluate('navigator.clipboard.readText()')
        assert copy_and_read()==expected[0]
        expect(page.locator('.replay-copy-feedback')).to_have_text('FEN copied to clipboard')
        page.keyboard.press('ArrowRight')
        assert copy_and_read()==expected[1]
        page.locator('[data-action=flip]').click()
        assert copy_and_read()==expected[1]
        page.locator('[data-action=last]').click()
        assert copy_and_read()==expected[-1]
        # Selecting page text must copy that text, rather than chess data.
        page.evaluate('''() => { const range=document.createRange();range.selectNodeContents(document.querySelector('.replay-page-header strong'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range); }''')
        assert copy_and_read()=='Clipboard test'
        page.evaluate('window.getSelection().removeAllRanges()')
        # Input selection is distinct from window.getSelection() in some browsers.
        page.evaluate('''() => { const input=document.createElement('textarea');input.id='copy-input';input.value='Keep normal copying';document.body.prepend(input); }''')
        page.locator('#copy-input').focus();page.keyboard.press('Control+a')
        assert copy_and_read()=='Keep normal copying'
        page.evaluate("document.getElementById('copy-input').remove()")
        page.locator('#account-toggle').click()
        assert copy_and_read()=='Keep normal copying'
        page.locator('#account-toggle').click()
        assert copy_and_read()==expected[-1]
        page.locator('#language-toggle').click();page.locator('button[data-language="pt-PT"]').click()
        assert copy_and_read()==expected[-1]
        expect(page.locator('.replay-copy-feedback')).to_have_text('FEN copiado para a área de transferência')
        expect(page.locator('.replay-copy-feedback')).to_be_hidden(timeout=4000)
        assert not errors,errors
    finally:context.close()
