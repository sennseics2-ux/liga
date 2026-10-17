"""Federation lookup uses FIDE codes and never invents or erases a country."""
import json
from unittest.mock import patch
import pytest
import database as store
import fide_ratings
from countries import federation_country,country_code
from deploy.refresh_fide_ratings import refresh_all
from test_league import client


@pytest.mark.parametrize('federation,name,flag',[
    ('POR','Portugal','pt'),('GER','Germany','de'),('ESP','Spain','es'),
    ('USA','United States','us'),('EGY','Egypt','eg'),('FRA','France','fr'),
    ('NGR','Nigeria','ng'),('NIG','Niger','ne'),('BRN','Bahrain','bh'),
    ('BRU','Brunei Darussalam','bn'),('ENG','United Kingdom','gb'),
    ('SCO','United Kingdom','gb'),('WLS','United Kingdom','gb'),
    ('ALG','Algeria','dz'),('SUI','Switzerland','ch'),('TPE','Taiwan','tw'),
    ('KOS','Kosovo','xk'),('LES','Lesotho','ls'),('CUR','Curaçao','cw'),
])
def test_fide_codes_differ_from_iso_and_use_existing_flags(federation,name,flag):
    assert federation_country(federation)==name
    assert country_code(name)==flag


@pytest.mark.parametrize('code',[None,'','FID','NON','XXX','PОR','Portugal','<script>'])
def test_missing_neutral_or_unknown_federation_has_no_country(code):
    assert federation_country(code) is None


@pytest.mark.parametrize('code,rating',[('POR','1870'),('EGY',None)])
def test_provider_profile_country_is_fetched_even_for_unrated_players(monkeypatch,code,rating):
    for key in ('CHESS_FIDE_API_URL_TEMPLATE','CHESS_FIDE_RATING_FIELD','CHESS_FIDE_MONTH_FIELD'):
        monkeypatch.delenv(key,raising=False)
    class Response:
        def __init__(self,kind):self.kind=kind
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def geturl(self):return f'https://fideratings.com/api/player/1959506/{self.kind}'
        def read(self,n):
            if self.kind=='profile':
                payload={'fideid':'1959506','federation_code':code}
            else:
                payload={'fideid':'1959506','current':{'standard':{'rating':rating,'date':'2026-10'}}}
            return json.dumps(payload).encode()
    with patch('fide_ratings.urlopen',side_effect=[Response('current'),Response('profile')]) as lookup:
        assert fide_ratings.fetch_player_details('1959506')==(int(rating) if rating else None,'2026-10',federation_country(code))
        assert lookup.call_args_list[1].args[0].full_url.endswith('/1959506/profile')


def test_country_profile_must_belong_to_requested_fide_id(monkeypatch):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def geturl(self):return 'https://fideratings.com/api/player/1959506/profile'
        def read(self,n):return b'{"fideid":"123456","federation_code":"POR"}'
    monkeypatch.setattr(fide_ratings,'fetch_standard_rating',lambda _:(1870,'2026-10'))
    with patch('fide_ratings.urlopen',return_value=Response()):
        with pytest.raises(ValueError,match='unexpected player profile'):
            fide_ratings.fetch_player_details('1959506')


def test_missing_provider_profile_keeps_rating_and_uses_official_country(monkeypatch):
    from urllib.error import HTTPError
    monkeypatch.setattr(fide_ratings,'fetch_standard_rating',lambda _:(None,None))
    monkeypatch.setattr('fide_official.fetch_official_country',lambda _:'Egypt')
    with patch('fide_ratings.urlopen',side_effect=HTTPError('https://fideratings.com/',404,'Not found',{},None)):
        assert fide_ratings.fetch_player_details('555014356')==(None,None,'Egypt')


def test_federation_failure_is_not_hidden_and_preserves_stored_values(client,monkeypatch):
    from urllib.error import HTTPError
    player=store.create_player('Failed profile',rating=1700,country='Spain',fide_id='1959506')
    monkeypatch.setattr(fide_ratings,'fetch_standard_rating',lambda _:(1870,'2026-10'))
    with patch('fide_ratings.urlopen',side_effect=HTTPError('https://fideratings.com/',503,'Unavailable',{},None)):
        assert fide_ratings.sync_ratings(force=True)==0
    with store.read_db() as db:
        assert db.execute('SELECT rating,country FROM players WHERE id=?',(player,)).fetchone()[:]==(1700,'Spain')


def test_requests_for_rating_and_profile_share_pacing_budget(monkeypatch):
    now=[0.0];calls=[]
    monkeypatch.setattr(fide_ratings,'_last_request',None)
    from types import SimpleNamespace
    # Replace this module's clock, without advancing asyncio's global clock.
    monkeypatch.setattr(fide_ratings,'time',SimpleNamespace(
        monotonic=lambda:now[0],sleep=lambda delay:now.__setitem__(0,now[0]+delay)))
    class Opener:
        def open(self,request,timeout):calls.append((request,now[0]))
    monkeypatch.setattr(fide_ratings,'build_opener',lambda _:Opener())
    fide_ratings.urlopen('rating',timeout=10)
    fide_ratings.urlopen('profile',timeout=10)
    assert calls==[('rating',0.0),('profile',1.0)]


def test_unknown_country_and_failed_lookup_preserve_existing_profile_country(client):
    player=store.create_player('Existing Player',rating=1700,country='Spain',fide_id='1959506')
    totals=refresh_all(fetcher=lambda _:(1870,'2026-10',None),output=lambda _:None)
    assert totals['updated']==1
    with store.read_db() as db:
        assert db.execute('SELECT rating,country FROM players WHERE id=?',(player,)).fetchone()[:]==(1870,'Spain')
    def fail(_):raise TimeoutError('Profile unavailable')
    assert refresh_all(fetcher=fail,output=lambda _:None)['failed']==1
    with store.read_db() as db:
        assert db.execute('SELECT rating,country FROM players WHERE id=?',(player,)).fetchone()[:]==(1870,'Spain')


def test_automatic_monthly_worker_updates_country_and_profile_flag(client,monkeypatch):
    player=store.create_player('Imported Player',fide_id='1959506')
    monkeypatch.setattr(fide_ratings,'fetch_player_details',lambda _:(1870,'2026-10','Portugal'))
    assert fide_ratings.sync_ratings()==1
    with store.read_db() as db:
        assert db.execute('SELECT country FROM players WHERE id=?',(player,)).fetchone()[0]=='Portugal'
    response=client.get(f'/players/{player}')
    assert 'Portugal' in response.text and '/static/flags/countries/pt.svg' in response.text
