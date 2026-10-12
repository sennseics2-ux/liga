"""Complete game browsing, preserved filters, stable ordering and Lisbon dates."""
from html import unescape
import re
from urllib.parse import parse_qs, urlsplit

import pytest

import database as store
from test_league import client


def insert_games(rows):
    """Create game summaries efficiently; no results or PGNs need processing."""
    white = store.create_player('Ada White')
    black = store.create_player('Ben Black')
    with store.transaction() as db:
        db.executemany('''INSERT INTO games
            (white_player_id,black_player_id,scheduled_at,event_name,result,created_at)
            VALUES(?,?,?,?,?,?)''',
            [(white, black, date, event, result, '2026-01-01T00:00:00+00:00')
             for date, event, result in rows])
        return [row[0] for row in db.execute('SELECT id FROM games ORDER BY id')]


def cards(response):
    assert response.status_code == 200
    return [int(game_id) for game_id in re.findall(
        r'<article class="game-list-card" data-game-id="(\d+)"', response.text)]


def pagination_link(response, relation):
    match = re.search(r'href="([^"]+)" rel="' + relation + '"', response.text)
    return unescape(match.group(1)) if match else None


@pytest.mark.parametrize('sort,reverse', [('newest', True), ('soonest', False)])
def test_every_game_beyond_old_200_limit_is_browsable_without_gaps(client, sort, reverse):
    # Identical dates also exercise the ID tie-breaker at page boundaries.
    game_ids = insert_games([('2026-06-15T12:00:00+00:00', 'Club open', '*')] * 201)
    seen = []
    response = client.get('/games', params={'sort': sort})
    for page in range(1, 10):
        page_ids = cards(response)
        expected_count = 25 if page < 9 else 1
        assert len(page_ids) == expected_count
        assert f'Showing {expected_count} of 201 matching games' in response.text
        assert f'Page {page} of 9' in response.text
        assert bool(pagination_link(response, 'prev')) == (page > 1)
        seen.extend(page_ids)
        next_url = pagination_link(response, 'next')
        assert bool(next_url) == (page < 9)
        if next_url:
            assert parse_qs(urlsplit(next_url).query)['sort'] == [sort]
            response = client.get(next_url)
    assert seen == sorted(game_ids, reverse=reverse)
    assert len(set(seen)) == 201
    # The final card is a functioning detail link, including the oldest record.
    assert client.get(f'/games/{seen[-1]}').status_code == 200


def test_filter_counts_and_encoded_search_survive_next_and_previous_pages(client):
    date = '2026-06-15T12:00:00+00:00'
    game_ids = insert_games(
        [(date, 'Club & Cup', '*')] * 59 +
        [(date, 'Club & Cup', '1-0')] * 30 +
        [('2025-06-15T12:00:00+00:00', 'Club & Cup', '*')] * 20 +
        [(date, 'Practice', '*')] * 8)
    filters = {'q':'Club & Cup', 'status':'scheduled', 'season':'2026', 'sort':'soonest'}
    first = client.get('/games', params=filters)
    assert cards(first) == game_ids[:25]
    assert 'Showing 25 of 59 matching games' in first.text
    assert 'Page 1 of 3' in first.text
    assert 'value="soonest" selected' in first.text
    next_url = pagination_link(first, 'next')
    assert parse_qs(urlsplit(next_url).query) == {
        **{key:[value] for key, value in filters.items()}, 'page':['2'], 'white_player':['all'], 'black_player':['all']}
    second = client.get(next_url)
    assert cards(second) == game_ids[25:50]
    assert parse_qs(urlsplit(pagination_link(second, 'prev')).query) == {
        **{key:[value] for key, value in filters.items()}, 'page':['1'], 'white_player':['all'], 'black_player':['all']}
    third = client.get(pagination_link(second, 'next'))
    assert cards(third) == game_ids[50:59]
    assert 'Showing 9 of 59 matching games' in third.text
    assert not pagination_link(third, 'next')


def test_scheduled_default_sort_is_chronological_but_explicit_newest_is_respected(client):
    ids = insert_games([
        ('2026-07-01T12:00:00+00:00', 'Late', '*'),
        ('2026-05-01T12:00:00+00:00', 'Early', '*'),
        ('2026-06-01T12:00:00+00:00', 'Middle', '*')])
    assert cards(client.get('/games?status=scheduled')) == [ids[1], ids[2], ids[0]]
    assert cards(client.get('/games?status=scheduled&sort=newest')) == [ids[0], ids[2], ids[1]]
    assert cards(client.get('/games?sort=soonest')) == [ids[1], ids[2], ids[0]]


@pytest.mark.parametrize('page', ['0', '-1', 'bad', '1.5'])
def test_invalid_page_uses_first_page(client, page):
    ids = insert_games([('2026-06-15T12:00:00+00:00', 'Club open', '*')] * 26)
    response = client.get('/games', params={'page':page})
    assert cards(response) == list(reversed(ids))[:25]
    assert 'Page 1 of 2' in response.text
    assert not pagination_link(response, 'prev')


def test_large_page_clamps_to_last_page_and_empty_results_remain_valid(client):
    ids = insert_games([('2026-06-15T12:00:00+00:00', 'Club open', '*')] * 26)
    response = client.get('/games?page=1000000')
    assert cards(response) == [ids[0]]
    assert 'Page 2 of 2' in response.text
    assert not pagination_link(response, 'next')
    empty = client.get('/games?page=1000000&q=not-a-real-event')
    assert cards(empty) == []
    assert 'Showing 0 of 0 matching games' in empty.text
    assert 'No matches found' in empty.text
    assert empty.context['page'] == 1


def test_search_treats_percent_and_underscore_as_literal_characters(client):
    ids = insert_games([
        ('2026-06-15T12:00:00+00:00', '100%_Cup', '*'),
        ('2026-06-15T12:00:00+00:00', '100XACup', '*')])
    response = client.get('/games', params={'q':'100%_Cup'})
    assert cards(response) == [ids[0]]
    assert 'Showing 1 of 1 matching games' in response.text


def test_lisbon_display_handles_both_dst_transitions_and_keeps_utc_storage(client):
    dates = [
        ('2026-06-15T12:00:00+00:00', '2026-06-15 · 13:00 WEST (Europe/Lisbon)'),
        ('2026-01-15T12:00:00+00:00', '2026-01-15 · 12:00 WET (Europe/Lisbon)'),
        ('2026-03-29T00:30:00+00:00', '2026-03-29 · 00:30 WET (Europe/Lisbon)'),
        ('2026-03-29T01:30:00+00:00', '2026-03-29 · 02:30 WEST (Europe/Lisbon)'),
        ('2026-10-25T00:30:00+00:00', '2026-10-25 · 01:30 WEST (Europe/Lisbon)'),
        ('2026-10-25T01:30:00+00:00', '2026-10-25 · 01:30 WET (Europe/Lisbon)'),
    ]
    ids = insert_games([(date, 'DST fixture', '*') for date, _ in dates])
    directory = client.get('/games')
    for game_id, (stored, display) in zip(ids, dates):
        assert display[:18] in directory.text
        assert display not in directory.text
        assert f'datetime="{stored}"' in directory.text
        detail = client.get(f'/games/{game_id}')
        assert detail.status_code == 200
        assert display in detail.text
    with store.read_db() as db:
        assert [row[0] for row in db.execute('SELECT scheduled_at FROM games ORDER BY id')] == [date for date, _ in dates]


def test_white_and_black_filters_match_the_correct_side_and_survive_pagination(client):
    ids = insert_games([('2026-06-15T12:00:00+00:00', 'Club open', '*')] * 30)
    with store.transaction() as db:
        row = db.execute('SELECT white_player_id,black_player_id FROM games WHERE id=?',(ids[0],)).fetchone()
        white, black = row
        db.execute('UPDATE games SET white_player_id=?,black_player_id=? WHERE id=?',(black,white,ids[-1]))
    response = client.get('/games',params={'white_player':white,'black_player':black})
    assert len(cards(response)) == 25
    assert ids[-1] not in cards(response)
    assert 'name="q"' not in response.text
    assert 'Player (white)' in response.text and 'Player (black)' in response.text
    link = pagination_link(response,'next')
    query = parse_qs(urlsplit(link).query)
    assert query['white_player'] == [str(white)] and query['black_player'] == [str(black)]
    assert len(cards(client.get(link))) == 4
    assert cards(client.get('/games',params={'white_player':black})) == [ids[-1]]
    assert cards(client.get('/games',params={'black_player':white})) == [ids[-1]]
    assert cards(client.get('/games',params={'white_player':white,'black_player':white})) == []
