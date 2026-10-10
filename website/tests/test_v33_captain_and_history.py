"""Season departures keep their historical meaning; public role labels change only display."""
import re
from html.parser import HTMLParser

class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.tags=[]; self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag,dict(attrs)))
import database as store
from main import season_bounds
from test_league import client,new_team
from test_v31_manager_and_lineup_privacy import arranged_match


def test_season_leave_dates_only_show_departures_during_selected_season(client):
    _,season,_,_,teams,_,rosters=arranged_match()
    with store.transaction() as db:
        start,end,_=season_bounds(db,f's{season}')
        db.execute('UPDATE player_team_terms SET started_at=? WHERE team_id=?',(start,teams[0]))
        for player,departure in zip(rosters[0],(None,end,'2026-08-12T12:00:00+00:00','2028-01-01T12:00:00+00:00')):
            db.execute('UPDATE player_team_terms SET ended_at=? WHERE player_id=? AND team_id=?',(departure,player,teams[0]))
    page=client.get(f'/teams/{teams[0]}?season=s{season}').text
    cells=re.findall(r'<td data-label="LEAVE DATE">(.*?)</td>',page,re.S)
    departures=[re.sub(r'<[^>]+>','',cell).strip() for cell in cells]
    assert departures.count('-')==3
    assert '2026-08-12' in departures
    assert '<th data-i18n="JOIN DATE">JOIN DATE</th>' in page
    assert '<th data-i18n="LEAVE DATE">LEAVE DATE</th>' in page


def test_profile_record_is_compact_in_identity_and_directory_removes_old_sorts(client):
    _,team=new_team('Manager','Manager Team')
    page=client.get('/users/Manager').text
    assert page.count('career-record-compact')==1
    assert page.index('member-profile-identity') < page.index('career-record-compact') < page.index('member-profile-header')
    assert '<h2><span data-no-i18n>Manager</span></h2>' in page
    assert 'Captain profile' in page
    for sort in ('name','newest','players_desc'):
        directory=client.get('/teams',params={'sort':sort}).text
        select=re.search(r'<select name="sort">(.*?)</select>',directory,re.S)[1]
        options=[attrs for tag,attrs in Tags(select).tags if tag=='option']
        assert {item['value'] for item in options}=={'name','name_desc','points_desc','budget_desc'}
        assert next(item['value'] for item in options if 'selected' in item)=='name'
