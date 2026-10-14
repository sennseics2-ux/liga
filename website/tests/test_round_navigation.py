"""Scheduled round bubbles open the match or a complete round match list."""
import re
import database as store
import league_seasons as seasons
from test_league import client,post
from test_v25_seasons import setup


def round_links(text):
    return re.findall(r'<a href="([^"]+)" class="schedule-round[^\"]*"',text)


def test_one_match_round_links_directly_and_empty_round_is_not_a_link(client):
    _,season,_,match,_,_,_=setup()
    with store.transaction() as db:db.execute("UPDATE seasons SET status='published' WHERE id=?",(season,))
    text=client.get(f'/seasons?season={season}').text
    assert round_links(text)==[f'/matches/{match}']
    assert text.count('class="schedule-round')==8  # Four spans per scheduled/empty bubble.
    assert client.get(f'/matches/{match}').status_code==200


def test_multi_match_round_lists_every_fixture_and_respects_draft_privacy(client):
    admin,season,rounds,match,_,_,_=setup()
    third,fourth=store.create_team('Third Team'),store.create_team('Fourth Team')
    with store.read_db() as db:date=db.execute('SELECT scheduled_at FROM team_matches WHERE id=?',(match,)).fetchone()[0]
    second=seasons.save_match(rounds[0],third,fourth,date,'Second hall',admin)
    assert client.get(f'/rounds/{rounds[0]}').status_code==404
    post(client,'/login',username='commissioner',password='adminpass123!')
    assert client.get(f'/rounds/{rounds[0]}').status_code==200
    post(client,'/logout')
    with store.transaction() as db:db.execute("UPDATE seasons SET status='published' WHERE id=?",(season,))
    assert round_links(client.get(f'/seasons?season={season}').text)==[f'/rounds/{rounds[0]}']
    page=client.get(f'/rounds/{rounds[0]}')
    assert page.status_code==200
    assert page.text.count('class="fixture-card"')==2
    assert f'href="/matches/{match}"' in page.text
    assert f'href="/matches/{second}"' in page.text
    assert client.get(f'/rounds/{rounds[1]}').status_code==404
    assert client.get('/rounds/9223372036854775808').status_code==404
