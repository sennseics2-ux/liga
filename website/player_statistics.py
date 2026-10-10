"""Chess results use 1 / 0.5 / 0, independently of fantasy points or FIDE IDs."""


def chess_score(half_points):
    return str(half_points // 2) + ('.5' if half_points % 2 else '')


def player_totals(db, player_id, visible_sql, visible_values):
    row=db.execute(f'''SELECT
        COUNT(*) AS played,
        COALESCE(SUM((g.result='1-0' AND g.white_player_id=?) OR
                     (g.result='0-1' AND g.black_player_id=?)),0) AS wins,
        COALESCE(SUM(g.result='1/2-1/2'),0) AS draws
        FROM games g WHERE (g.white_player_id=? OR g.black_player_id=?)
          AND g.result IN ('1-0','0-1','1/2-1/2') AND {visible_sql}''',
        (player_id,player_id,player_id,player_id,*visible_values)).fetchone()
    result=dict(row)
    result['losses']=result['played']-result['wins']-result['draws']
    result['score']=chess_score(2*result['wins']+result['draws'])
    return result


def team_season_scores(db, team_id, start, end, season_id, visible_sql, visible_values):
    # Match season IDs stay authoritative when administrators adjust season dates.
    # Standalone games use the selected season's dates. Attribution is recorded
    # on the game, never inferred from today's roster or an account's FIDE ID.
    period='g.scheduled_at>=? AND g.scheduled_at<?'
    period_values=(start,end)
    if season_id is not None:
        period='((sr.season_id=?) OR (mg.game_id IS NULL AND g.scheduled_at>=? AND g.scheduled_at<?))'
        period_values=(season_id,start,end)
    games=db.execute(f'''SELECT g.white_player_id,g.black_player_id,g.white_team_id,g.black_team_id,g.result
        FROM games g LEFT JOIN match_games mg ON mg.game_id=g.id
        LEFT JOIN team_matches m ON m.id=mg.match_id LEFT JOIN season_rounds sr ON sr.id=m.round_id
        WHERE (g.white_team_id=? OR g.black_team_id=?) AND g.attribution_confirmed=1
          AND g.result IN ('1-0','0-1','1/2-1/2') AND {period} AND {visible_sql}''',
        (team_id,team_id,*period_values,*visible_values))
    totals={}
    for game in games:
        for side in ('white','black'):
            if game[side+'_team_id']!=team_id:
                continue
            stats=totals.setdefault(game[side+'_player_id'],{'half_points':0,'played':0})
            stats['played']+=1
            stats['half_points']+=1 if game['result']=='1/2-1/2' else (
                2 if game['result']==('1-0' if side=='white' else '0-1') else 0)
    for stats in totals.values():
        stats['score']=chess_score(stats['half_points'])
        stats['summary']=f"{stats['score']}/{stats['played']}"
    return totals
