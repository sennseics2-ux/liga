"""Read-only podium honours from complete, concluded season match records.

Match wins/draws/losses earn 3/1/0 league points. Ties use head-to-head match wins,
head-to-head board points, then all-season board points. A multi-team tie uses
the mini-table between all teams tied on league points. Exact ties share ranks.
Current squads, lifetime player points and budgets never decide past placements.
"""
from collections import defaultdict
from zoneinfo import ZoneInfo


def season_honours(db, team_id):
    import database as store
    today=store.now_utc().astimezone(ZoneInfo('Europe/Lisbon')).date().isoformat()
    closed=[dict(row) for row in db.execute("SELECT * FROM seasons WHERE status='published' AND end_date<? ORDER BY start_year DESC",(today,))]
    matches=defaultdict(list)
    for row in db.execute('''SELECT m.*,r.number AS round_number,r.season_id FROM team_matches m
        JOIN season_rounds r ON r.id=m.round_id JOIN seasons s ON s.id=r.season_id
        WHERE s.status='published' AND s.end_date<? ORDER BY m.id''',(today,)):
        matches[row['season_id']].append(dict(row))
    boards=defaultdict(list)
    for row in db.execute('''SELECT mg.match_id,mg.board,g.result,g.attribution_confirmed,g.white_team_id,g.black_team_id
        FROM match_games mg JOIN games g ON g.id=mg.game_id JOIN team_matches m ON m.id=mg.match_id
        JOIN season_rounds r ON r.id=m.round_id JOIN seasons s ON s.id=r.season_id
        WHERE s.status='published' AND s.end_date<?''',(today,)):
        boards[row['match_id']].append(dict(row))
    honours=[]
    for season in closed:
        fixtures=matches[season['id']]
        if {m['round_number'] for m in fixtures} != set(range(1,season['round_count']+1)):
            continue
        teams_by_round=defaultdict(list)
        scores=defaultdict(int)
        board_points=defaultdict(int)
        records=[]
        complete=True
        for match in fixtures:
            pairing={match['home_team_id'],match['away_team_id']}
            teams_by_round[match['round_number']].extend(pairing)
            games=boards[match['id']]
            if {g['board'] for g in games}!={1,2,3,4}:
                complete=False
                break
            match_points={team:0 for team in pairing}
            for game in games:
                if (game['result'] not in ('1-0','0-1','1/2-1/2') or not game['attribution_confirmed']
                    or {game['white_team_id'],game['black_team_id']}!=pairing):
                    complete=False
                    break
                white,black=game['white_team_id'],game['black_team_id']
                # Integer half-points avoid floating-point comparisons for draws.
                match_points[white]+=2 if game['result']=='1-0' else (1 if game['result']=='1/2-1/2' else 0)
                match_points[black]+=2 if game['result']=='0-1' else (1 if game['result']=='1/2-1/2' else 0)
            if not complete:
                break
            home,away=match['home_team_id'],match['away_team_id']
            records.append((home,away,match_points[home],match_points[away]))
            for team,opponent in ((home,away),(away,home)):
                scores[team]+=3 if match_points[team]>match_points[opponent] else (1 if match_points[team]==match_points[opponent] else 0)
                board_points[team]+=match_points[team]
        participants=set(teams_by_round.get(1,[]))
        if not complete or any(len(ids)!=len(set(ids)) or set(ids)!=participants for ids in teams_by_round.values()):
            continue
        if team_id not in scores:
            continue
        standings=_standing_keys(scores,board_points,records)
        rank=1+sum(key>standings[team_id] for key in standings.values())
        if rank>3:
            continue
        medal,place,medal_label={1:('gold','1st place','Gold medal'),2:('silver','2nd place','Silver medal'),
                                3:('bronze','3rd place','Bronze medal')}[rank]
        honours.append({'season_id':season['id'],'season_name':season['name'],'rank':rank,'medal':medal,
                        'place_label':place,'medal_label':medal_label,'points':scores[team_id]})
    return honours


def _standing_keys(league_points,board_points,records):
    """Stable mini-tables avoid cyclic pairwise sorting in a three-team tie."""
    groups=defaultdict(set)
    for team,points in league_points.items():
        groups[points].add(team)
    keys={}
    for points,tied in groups.items():
        head_wins=defaultdict(int)
        head_boards=defaultdict(int)
        for home,away,home_points,away_points in records:
            if home not in tied or away not in tied:
                continue
            head_wins[home]+=home_points>away_points
            head_wins[away]+=away_points>home_points
            head_boards[home]+=home_points
            head_boards[away]+=away_points
        for team in tied:
            keys[team]=(points,head_wins[team],head_boards[team],board_points[team])
    return keys
