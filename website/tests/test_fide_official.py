"""Official profiles recover federations missing from the secondary provider."""
from pathlib import Path
from urllib.request import Request
import pytest
import fide_ratings
import fide_official
import database as store
from deploy import fill_missing_countries

PROFILE='''<html><div>Portugal</div><p class="profile-info-id other">555014356</p>
<div class="profile-info-country "><img src="/images/flags/eg.svg" height="30">Egypt</div>
<footer>International Chess Federation</footer></html>'''


def test_official_profile_extracts_country_only_after_verifying_id():
    assert fide_official.parse_official_country(PROFILE,'555014356')=='Egypt'
    with pytest.raises(ValueError,match='identity'):
        fide_official.parse_official_country(PROFILE,'1959506')
    with pytest.raises(ValueError,match='identity'):
        fide_official.parse_official_country('<div>Egypt</div>','555014356')


def test_missing_provider_code_uses_official_fide_profile(monkeypatch):
    calls=[]
    monkeypatch.setattr(fide_ratings,'_fetch_payload',lambda *_:{'fideid':'555014356','federation_code':'XXX'})
    def official(fid):calls.append(fid);return 'Egypt'
    monkeypatch.setattr(fide_official,'fetch_official_country',official)
    assert fide_ratings.fetch_federation_country('555014356')=='Egypt'
    assert calls==['555014356']


def test_official_request_does_not_forward_api_credentials(monkeypatch):
    monkeypatch.setenv('CHESS_FIDE_API_KEY','private-test-key')
    calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def geturl(self):return 'https://ratings.fide.com/profile/555014356'
        def read(self,n):return PROFILE.encode()
    def open_request(request,timeout):calls.append(request);return Response()
    monkeypatch.setattr(fide_ratings,'urlopen',open_request)
    assert fide_official.fetch_official_country('555014356')=='Egypt'
    assert calls[0].full_url=='https://ratings.fide.com/profile/555014356'
    assert not any(key.lower() in ('authorization','x-api-key','x-fideratings-key') for key in calls[0].headers)


@pytest.mark.parametrize('origin,target',[
    ('https://fideratings.com/api/player/555014356/profile','https://ratings.fide.com/profile/555014356'),
    ('https://ratings.fide.com/profile/555014356','https://fideratings.com/api/player/555014356/profile'),
    ('https://ratings.fide.com/profile/555014356','http://ratings.fide.com/profile/555014356'),
])
def test_redirects_cannot_cross_provider_boundaries(origin,target):
    with pytest.raises(ValueError,match='redirect'):
        fide_ratings.ProviderRedirects().redirect_request(Request(origin),None,302,'redirect',{},target)


def test_country_only_command_marks_unresolved_records_as_incomplete(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'league.sqlite3')
    store.init_db()
    store.create_player('Unresolved player',fide_id='555014356')
    monkeypatch.setattr(fill_missing_countries,'fetch_federation_country',lambda _:None)
    monkeypatch.setattr('sys.argv',['fill_missing_countries','--backup-dir',str(tmp_path/'backups')])
    assert fill_missing_countries.main()==1
    assert len(list((tmp_path/'backups').rglob('*.sqlite3')))==1
