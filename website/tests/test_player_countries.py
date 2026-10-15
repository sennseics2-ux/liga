"""Player country flags and filtering share the visible directory population."""
from html.parser import HTMLParser
import database as store
from test_league import client, new_team


class Directory(HTMLParser):
    def __init__(self,text):
        super().__init__()
        self.options=[];self.players=[];self.flags=[];self.in_countries=False
        self.feed(text)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='select':self.in_countries=attrs.get('name')=='country'
        if tag=='option' and self.in_countries:self.options.append(attrs)
        if tag=='tr' and 'data-player-profile' in attrs:self.players.append(attrs['data-player-profile'])
        if tag=='img' and attrs.get('class')=='player-country-flag':self.flags.append(attrs)
    def handle_endtag(self,tag):
        if tag=='select':self.in_countries=False


def test_options_flags_and_combined_filters(client):
    manager,team=new_team('countrycaptain','Country Team')
    portugal=store.create_player('Country Ana',rating=1800,country='Portugal')
    alias=store.create_player('Country Bea',rating=1600,country='PT')
    spain=store.create_player('Country Carla',rating=1700,country='Spain')
    blank=store.create_player('Country Dora',country='')
    with store.transaction() as db:
        db.execute("UPDATE players SET country='PT' WHERE id=?",(alias,))
        db.execute("UPDATE users SET country='Germany' WHERE id=?",(manager,))
        db.execute("UPDATE players SET country='Spain' WHERE user_id=?",(manager,))
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team,portugal))
        linked=db.execute('SELECT id FROM players WHERE user_id=?',(manager,)).fetchone()[0]
    page=client.get('/players')
    assert page.status_code==200
    directory=Directory(page.text)
    assert [option['value'] for option in directory.options]==['all','Germany','Portugal','Spain']
    assert len(directory.players)==5 and len(directory.flags)==4
    assert sorted(flag['src'].split('/')[-1] for flag in directory.flags)==['de.svg','es.svg','pt.svg','pt.svg']
    assert all(flag['alt'] for flag in directory.flags)
    assert 'Country not provided' in page.text
    for flag in directory.flags:assert client.get(flag['src']).status_code==200
    portuguese=Directory(client.get('/players',params={'country':'Portugal','sort':'name_desc'}).text)
    assert portuguese.players==[f'/players/{alias}',f'/players/{portugal}']
    assert 'selected' in next(option for option in portuguese.options if option['value']=='Portugal')
    assert len(portuguese.options)==4  # Other countries remain selectable.
    page=Directory(client.get('/players',params={'country':'PT','q':'Ana','team':team}).text)
    assert page.players==[f'/players/{portugal}']
    assert Directory(client.get('/players',params={'country':'Germany'}).text).players==[f'/players/{linked}']
    assert Directory(client.get('/players',params={'country':'Spain'}).text).players==[f'/players/{spain}']
    assert f'/players/{blank}' in Directory(client.get('/players',params={'country':'all'}).text).players
    assert 'No matching players' in client.get('/players',params={'country':'Portugal','q':'Carla'}).text


def test_options_exclude_inactive_and_empty_countries_and_refresh(client):
    manager,_=new_team('hidden-country','Hidden Team')
    player=store.create_player('Visible Country Player',country='Portugal')
    legacy=store.create_player('Unknown Country Player')
    store.create_player('Blank Country Player',country='   ')
    with store.transaction() as db:
        db.execute("UPDATE players SET country='Atlantis' WHERE id=?",(legacy,))
        db.execute("UPDATE users SET country='Finland',player_active=0 WHERE id=?",(manager,))
    directory=Directory(client.get('/players').text)
    assert [option['value'] for option in directory.options]==['all','Atlantis','Portugal']
    assert len(directory.flags)==1
    for country in ['Finland',"Portugal' OR 1=1 --"]:
        response=client.get('/players',params={'country':country})
        assert response.status_code==200 and len(Directory(response.text).players)==3
    with store.transaction() as db:
        db.execute("UPDATE players SET country='Finland' WHERE id=?",(player,))
    updated=Directory(client.get('/players').text)
    assert [option['value'] for option in updated.options]==['all','Atlantis','Finland']
    assert updated.flags[0]['src'].endswith('/fi.svg')
