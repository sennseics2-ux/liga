"""Federation fallback for players missing from the ratings-provider registry."""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit
from urllib.request import Request

from countries import COUNTRIES,country_field,federation_country


class ProfileParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack=[]
        self.identity=[]
        self.country=[]
        self.flag=None

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        classes=attrs.get('class','').split()
        role=self.stack[-1][1] if self.stack else None
        if 'profile-info-id' in classes:role='id'
        if 'profile-info-country' in classes:role='country'
        if tag=='img' and role=='country':
            match=re.fullmatch(r'/images/flags/([a-zA-Z]{2,3})\.svg',attrs.get('src',''))
            if match:self.flag=match.group(1)
        if tag not in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):
            self.stack.append((tag,role))

    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:
                del self.stack[index:]
                break

    def handle_data(self,data):
        role=self.stack[-1][1] if self.stack else None
        if role=='id':self.identity.append(data)
        if role=='country':self.country.append(data)


def parse_official_country(html,fide_id):
    parser=ProfileParser()
    parser.feed(html)
    if ''.join(parser.identity).strip()!=fide_id:
        raise ValueError('Official FIDE profile identity does not match the requested ID.')
    label=' '.join(''.join(parser.country).split())
    for value in (parser.flag,label):
        country=country_field(value)['selected_country']
        if country in COUNTRIES:return country
        country=federation_country(value)
        if country:return country
    # Constituent federation labels may use individual flags on FIDE's site.
    return {'England':'United Kingdom','Scotland':'United Kingdom','Wales':'United Kingdom'}.get(label)


def fetch_official_country(fide_id):
    from database import validate_player_fide_id
    from fide_ratings import urlopen
    fide_id=validate_player_fide_id(fide_id)
    if fide_id is None:raise ValueError('FIDE ID is required for country lookup.')
    url=f'https://ratings.fide.com/profile/{fide_id}'
    # API credentials belong only to fideratings.com and are never forwarded.
    request=Request(url,headers={'Accept':'text/html','User-Agent':'LigaSX-AAC/112'})
    with urlopen(request,timeout=15) as response:
        final=urlsplit(response.geturl())
        if final.scheme!='https' or final.hostname!='ratings.fide.com':
            raise ValueError('Unexpected official FIDE redirect.')
        data=response.read(1048577)
        if len(data)>1048576:raise ValueError('Official FIDE profile is too large.')
    return parse_official_country(data.decode('utf-8'),fide_id)
