"""Season table from completed, attributed four-board team matches."""
from collections import defaultdict
from league_honours import _standing_keys
from player_statistics import chess_score
from league_seasons import _datetime


def season_table(db, season_id, include_all=False, through_round=None):
    import database as store
    teams={row['id']:dict(row) for row in db.execute('''SELECT t.*,u.username,photo.updated_at AS photo_updated_at
        FROM teams t LEFT JOIN users u ON u.id=t.manager_id LEFT JOIN team_photos photo ON photo.team_id=t.id''')}
    fixtures=[dict(row) for row in db.execute('''SELECT m.*,r.number AS round_number FROM team_matches m
        JOIN season_rounds r ON r.id=m.round_id JOIN seasons s ON s.id=r.season_id
        WHERE r.season_id=? AND s.status='published' ''',(season_id,))] if season_id else []
    participants=set(teams) if include_all else {m[side+'_team_id'] for m in fixtures for side in ('home','away')}
    stats={team:{**teams[team],'played':0,'wins':0,'draws':0,'losses':0,'points':0,'half_points':0} for team in participants}
    boards=defaultdict(list)
    if season_id:
        for row in db.execute('''SELECT mg.*,g.result,g.white_team_id,g.black_team_id,g.attribution_confirmed
            FROM match_games mg JOIN games g ON g.id=mg.game_id JOIN team_matches m ON m.id=mg.match_id
            JOIN season_rounds r ON r.id=m.round_id WHERE r.season_id=?''',(season_id,)):
            boards[row['match_id']].append(row)
    records=[]
    now=store.now_utc()
    for match in fixtures:
        if through_round is not None and match['round_number']>through_round:continue
        if _datetime(match['scheduled_at'])>now:continue
        home,away=match['home_team_id'],match['away_team_id'];games=boards[match['id']]
        if len(games)!=4 or {g['board'] for g in games}!={1,2,3,4}:continue
        if any(g['result'] not in ('1-0','0-1','1/2-1/2') or not g['attribution_confirmed'] or
               {g['white_team_id'],g['black_team_id']}!={home,away} for g in games):continue
        points={home:0,away:0}
        for game in games:
            for side in ('white','black'):
                points[game[side+'_team_id']]+=1 if game['result']=='1/2-1/2' else (2 if game['result']==('1-0' if side=='white' else '0-1') else 0)
        records.append((home,away,points[home],points[away]))
        for team,opponent in ((home,away),(away,home)):
            row=stats[team];row['played']+=1;row['half_points']+=points[team]
            result='wins' if points[team]>points[opponent] else ('draws' if points[team]==points[opponent] else 'losses')
            row[result]+=1;row['points']+=3 if result=='wins' else (1 if result=='draws' else 0)
    keys=_standing_keys({team:r['points'] for team,r in stats.items()},{team:r['half_points'] for team,r in stats.items()},records)
    ordered=sorted(stats.values(),key=lambda r:r['name'].casefold())
    ordered.sort(key=lambda r:keys[r['id']],reverse=True)
    for row in ordered:
        row['rank']=1+sum(key>keys[row['id']] for key in keys.values())
        row['board_points']=chess_score(row['half_points'])
    return ordered


def current_table(db):
    import league_seasons as seasons
    context=seasons.calendar_view(db,'current')
    return season_table(db,context['season']['id'],True)
