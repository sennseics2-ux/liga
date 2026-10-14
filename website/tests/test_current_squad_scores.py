"""Current-roster results stay within the current season and attributed team."""
from datetime import datetime,timezone
import re
import pytest
import database as store
import league_seasons as seasons
from test_league import client,seed_admin,new_team


@pytest.mark.parametrize('configured',[True,False])
def test_current_squad_scores_do_not_follow_the_archive_picker(client,monkeypatch,configured):
    monkeypatch.setattr(store,'now_utc',lambda:datetime(2026,10,14,tzinfo=timezone.utc))
    seed_admin()
    _,team=new_team('CurrentCaptain','Current Team')
    _,opposing_team=new_team('OtherCaptain','Other Team')
    player=store.create_player('Current Squad Player','Removed club',1800)
    opponent=store.create_player('Opponent')
    with store.transaction() as db:
        admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        for pid,tid in [(player,team),(opponent,opposing_team)]:
            db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(tid,pid))
            store._start_player_term(db,pid,tid,'2025-01-01T00:00:00+00:00')
    current='s'+str(seasons.save_season(2026,'2026-08-01','2027-06-30',6,admin)) if configured else '2026'
    old=seasons.save_season(2025,'2025-07-01','2026-06-30',6,admin)
    for date,result in [('2026-09-01','1-0'),('2026-09-02','1/2-1/2'),('2025-09-01','0-1'),('2026-07-01','0-1'),('2026-10-20','*')]:
        game=store.create_game(player,opponent,date+'T18:00:00+00:00')
        if result!='*':store.update_game_result(game,result,actor_id=admin,reason='Squad score fixture')
    for selection in [current,f's{old}']:
        page=client.get(f'/teams/{team}?season={selection}').text
        current_table=re.search(r'<table class="data-table mobile-cards current-squad-table">(.*?)</table>',page,re.S).group(1)
        row=next(row for row in re.findall(r'<tr>(.*?)</tr>',current_table,re.S) if 'Current Squad Player' in row)
        assert f'data-no-i18n>1.5/{2 if configured else 3}</strong>' in row
        assert 'data-label="CLUB"' not in current_table
        assert 'Removed club' not in current_table
        assert 'data-label="SCORE / MATCHES"' in row
        assert 'SCORE / PLAYED' not in page
    assert 'class="season-player-score" data-no-i18n>0/1</strong>' in page
