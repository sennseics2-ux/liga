"""Season scheduling and atomic four-board team lineups."""
from datetime import date, datetime, timezone
import sqlite3
from zoneinfo import ZoneInfo


def save_season(start_year, start_date, end_date, round_count, actor_id, season_id=None):
    import database as store
    try:
        start_year=int(start_year);count=int(round_count)
        start=date.fromisoformat(str(start_date));end=date.fromisoformat(str(end_date))
    except (ValueError,TypeError):
        raise ValueError('Choose valid season dates, year, and round count.') from None
    if not 2000 <= start_year <= 2100 or not 1 <= count <= 100 or end < start:
        raise ValueError('Season dates and round count are invalid.')
    if start < date(start_year,1,1) or end > date(start_year+1,12,31):
        raise ValueError('Season dates must fall within its two named calendar years.')
    with store.transaction() as db:
        store._admin_actor(db,actor_id)
        previous=db.execute('SELECT * FROM seasons WHERE id=?',(season_id,)).fetchone() if season_id else None
        if season_id and not previous:
            raise ValueError('Season not found.')
        if season_id:
            if db.execute('''SELECT 1 FROM team_matches m JOIN season_rounds r ON r.id=m.round_id
                WHERE r.season_id=? AND r.number>?''',(season_id,count)).fetchone():
                raise ValueError('Remove matches from the extra rounds before reducing the round count.')
            # Editing a schedule returns it to draft until consistency is checked.
            db.execute('DELETE FROM season_rounds WHERE season_id=? AND number>?',(season_id,count))
            try:
                db.execute("UPDATE seasons SET name=?,start_year=?,start_date=?,end_date=?,round_count=?,status='draft' WHERE id=?",
                           (f'{start_year}-{start_year+1}',start_year,start.isoformat(),end.isoformat(),count,season_id))
            except sqlite3.IntegrityError:
                raise ValueError('That season already exists.') from None
        else:
            try:
                season_id=db.execute('''INSERT INTO seasons(name,start_year,start_date,end_date,round_count,created_at)
                    VALUES(?,?,?,?,?,?)''',(f'{start_year}-{start_year+1}',start_year,start.isoformat(),end.isoformat(),count,store.iso(store.now_utc()))).lastrowid
            except sqlite3.IntegrityError:
                raise ValueError('That season already exists.') from None
        for number in range(1,count+1):
            db.execute('INSERT OR IGNORE INTO season_rounds(season_id,number) VALUES(?,?)',(season_id,number))
        store._audit(db,'season_updated','season',season_id,actor_id,'Season setup saved',after={'name':f'{start_year}-{start_year+1}','round_count':count})
    return season_id


def _datetime(value):
    try:
        parsed=datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError,TypeError):
        raise ValueError('Choose a valid match date and time.') from None


def save_match(round_id, home_team_id, away_team_id, scheduled_at, location, actor_id, match_id=None):
    import database as store
    try:
        round_id=int(round_id);home=int(home_team_id);away=int(away_team_id)
    except (ValueError,TypeError):
        raise ValueError('Choose two teams and a round.') from None
    scheduled=_datetime(scheduled_at);location=str(location or '').strip()
    if home==away or not 2 <= len(location) <= 200 or any(ord(c)<32 for c in location):
        raise ValueError('Choose different teams and a location of 2–200 characters.')
    with store.transaction() as db:
        store._admin_actor(db,actor_id)
        rnd=db.execute('''SELECT r.*,s.start_date,s.end_date,s.name FROM season_rounds r JOIN seasons s ON s.id=r.season_id
            WHERE r.id=?''',(round_id,)).fetchone()
        if not rnd:
            raise ValueError('Round not found.')
        match_date=scheduled.astimezone(ZoneInfo('Europe/Lisbon')).date().isoformat()
        if not rnd['start_date'] <= match_date <= rnd['end_date']:
            raise ValueError('Match date must be within the season dates.')
        if db.execute('SELECT COUNT(*) FROM teams WHERE id IN (?,?)',(home,away)).fetchone()[0]!=2:
            raise ValueError('Team not found.')
        if db.execute('''SELECT 1 FROM team_matches WHERE round_id=? AND id!=? AND
            (home_team_id IN (?,?) OR away_team_id IN (?,?))''',(round_id,match_id or -1,home,away,home,away)).fetchone():
            raise ValueError('Each team may play only one match in a round.')
        previous=db.execute('SELECT * FROM team_matches WHERE id=?',(match_id,)).fetchone() if match_id else None
        if match_id and not previous:
            raise ValueError('Match not found.')
        if previous:
            if (previous['home_team_id'],previous['away_team_id'],previous['round_id']) != (home,away,round_id):
                if db.execute('SELECT 1 FROM match_lineups WHERE match_id=?',(match_id,)).fetchone():
                    raise ValueError('Teams and round cannot change after a lineup has been submitted.')
            if db.execute('''SELECT 1 FROM match_games mg JOIN games g ON g.id=mg.game_id
                WHERE mg.match_id=? AND (g.result!='*' OR g.pgn_text IS NOT NULL)''',(match_id,)).fetchone():
                raise ValueError('A match with recorded games cannot be rescheduled.')
            db.execute('UPDATE team_matches SET round_id=?,home_team_id=?,away_team_id=?,scheduled_at=?,location=? WHERE id=?',
                       (round_id,home,away,store.iso(scheduled),location,match_id))
            for board_game in db.execute('SELECT game_id,board FROM match_games WHERE match_id=?',(match_id,)).fetchall():
                db.execute('UPDATE games SET scheduled_at=?,event_name=?,round_label=? WHERE id=?',
                           (store.iso(scheduled),rnd['name'],f"Round {rnd['number']} · Board {board_game['board']}",board_game['game_id']))
        else:
            match_id=db.execute('''INSERT INTO team_matches(round_id,home_team_id,away_team_id,scheduled_at,location,created_at)
                VALUES(?,?,?,?,?,?)''',(round_id,home,away,store.iso(scheduled),location,store.iso(store.now_utc()))).lastrowid
        db.execute("UPDATE seasons SET status='draft' WHERE id=?",(rnd['season_id'],))
        store._audit(db,'match_scheduled','match',match_id,actor_id,'Team match scheduled or updated')
    return match_id


def publish_season(season_id, actor_id):
    import database as store
    with store.transaction() as db:
        store._admin_actor(db,actor_id)
        season=db.execute('SELECT * FROM seasons WHERE id=?',(season_id,)).fetchone()
        if not season:
            raise ValueError('Season not found.')
        rounds=db.execute('SELECT * FROM season_rounds WHERE season_id=? ORDER BY number',(season_id,)).fetchall()
        participants=None
        for rnd in rounds:
            matches=db.execute('SELECT * FROM team_matches WHERE round_id=?',(rnd['id'],)).fetchall()
            teams=[]
            if not matches:
                raise ValueError('Schedule all rounds before publishing the season.')
            for match in matches:
                teams.extend((match['home_team_id'],match['away_team_id']))
                match_date=_datetime(match['scheduled_at']).astimezone(ZoneInfo('Europe/Lisbon')).date().isoformat()
                if not season['start_date'] <= match_date <= season['end_date']:
                    raise ValueError('All match dates must be within the current season dates.')
                if not match['location']:
                    raise ValueError('Every match needs a location.')
            if len(teams)!=len(set(teams)) or (participants is not None and set(teams)!=participants):
                raise ValueError('Every participating team must play exactly once in every round.')
            participants=set(teams)
        db.execute("UPDATE seasons SET status='published' WHERE id=?",(season_id,))
        store._audit(db,'season_published','season',season_id,actor_id,'Complete season schedule published')


def match_rows(db, season_id=None):
    return [dict(row) for row in db.execute('''SELECT m.*,r.number AS round_number,r.season_id,s.name AS season_name,s.status AS season_status,
        ht.name AS home_name,at.name AS away_name,
        (SELECT COUNT(*) FROM match_lineups l WHERE l.match_id=m.id) AS lineup_count
        FROM team_matches m JOIN season_rounds r ON r.id=m.round_id JOIN seasons s ON s.id=r.season_id
        JOIN teams ht ON ht.id=m.home_team_id JOIN teams at ON at.id=m.away_team_id
        WHERE (? IS NULL OR s.id=?) ORDER BY s.start_year DESC,r.number,m.scheduled_at,m.id''',(season_id,season_id))]


def eligible_players(db, team_id):
    return [dict(row) for row in db.execute('''SELECT p.*,u.username FROM players p LEFT JOIN users u ON u.id=p.user_id
        WHERE p.owner_team_id=? AND (u.id IS NULL OR (u.account_active=1 AND u.player_active=1))
        ORDER BY p.rating DESC,p.name COLLATE NOCASE''',(team_id,))]


def submit_lineup(match_id, manager_id, player_ids):
    import database as store
    try:
        ids=[int(player_id) for player_id in player_ids]
    except (ValueError,TypeError):
        raise ValueError('Select four different players.') from None
    if len(ids)!=4 or len(set(ids))!=4:
        raise ValueError('Select four different players.')
    with store.transaction() as db:
        match=db.execute('''SELECT m.*,r.number,s.name FROM team_matches m JOIN season_rounds r ON r.id=m.round_id
            JOIN seasons s ON s.id=r.season_id WHERE m.id=?''',(match_id,)).fetchone()
        team=db.execute('''SELECT t.id FROM teams t JOIN users u ON u.id=t.manager_id
            WHERE t.manager_id=? AND u.account_active=1 AND u.manager_active=1''',(manager_id,)).fetchone()
        if not match or not team or team['id'] not in (match['home_team_id'],match['away_team_id']):
            raise ValueError('Only the assigned team manager can submit this lineup.')
        if _datetime(match['scheduled_at']) <= store.now_utc():
            raise ValueError('The lineup deadline has passed.')
        if db.execute('''SELECT 1 FROM match_games mg JOIN games g ON g.id=mg.game_id
            WHERE mg.match_id=? AND (g.result!='*' OR g.pgn_text IS NOT NULL)''',(match_id,)).fetchone():
            raise ValueError('Lineups are locked once a game result or PGN has been recorded.')
        eligible={p['id'] for p in eligible_players(db,team['id'])}
        if not set(ids)<=eligible:
            raise ValueError('Every selected player must be an active member of your team.')
        db.execute('''INSERT INTO match_lineups(match_id,team_id,manager_id,submitted_at) VALUES(?,?,?,?)
            ON CONFLICT(match_id,team_id) DO UPDATE SET manager_id=excluded.manager_id,submitted_at=excluded.submitted_at''',
            (match_id,team['id'],manager_id,store.iso(store.now_utc())))
        db.execute('DELETE FROM lineup_players WHERE match_id=? AND team_id=?',(match_id,team['id']))
        for board,player in enumerate(ids,1):
            db.execute('INSERT INTO lineup_players(match_id,team_id,board,player_id) VALUES(?,?,?,?)',(match_id,team['id'],board,player))
        store._audit(db,'lineup_submitted','match',match_id,manager_id,'Four-player lineup submitted',after={'team_id':team['id'],'players':ids})
        _sync_board_games(db,match)


def _sync_board_games(db, match):
    import database as store
    lineups=db.execute('SELECT COUNT(*) FROM match_lineups WHERE match_id=?',(match['id'],)).fetchone()[0]
    if lineups!=2:
        return
    entries=db.execute('SELECT * FROM lineup_players WHERE match_id=?',(match['id'],)).fetchall()
    for entry in entries:
        # Revalidate both submissions: a player may have transferred since the first.
        if entry['player_id'] not in {p['id'] for p in eligible_players(db,entry['team_id'])}:
            raise ValueError('A submitted lineup has an ineligible player. The team manager must update it.')
    players={(e['team_id'],e['board']):e['player_id'] for e in entries}
    for board in range(1,5):
        white_team,black_team=(match['home_team_id'],match['away_team_id']) if board%2 else (match['away_team_id'],match['home_team_id'])
        white=players[(white_team,board)];black=players[(black_team,board)]
        previous=db.execute('SELECT game_id FROM match_games WHERE match_id=? AND board=?',(match['id'],board)).fetchone()
        if previous:
            db.execute('UPDATE games SET white_player_id=?,black_player_id=?,white_team_id=?,black_team_id=?,attribution_confirmed=1 WHERE id=?',
                       (white,black,white_team,black_team,previous['game_id']))
            # Empty generated fixtures have zero-value ledger awards only if touched.
            db.execute("DELETE FROM points_ledger WHERE game_id=? AND source='game_award'",(previous['game_id'],))
        else:
            game=db.execute('''INSERT INTO games(white_player_id,black_player_id,scheduled_at,event_name,round_label,
                white_team_id,black_team_id,attribution_confirmed,created_at) VALUES(?,?,?,?,?,?,?,1,?)''',
                (white,black,match['scheduled_at'],match['name'],f"Round {match['number']} · Board {board}",white_team,black_team,store.iso(store.now_utc()))).lastrowid
            db.execute('INSERT INTO match_games(match_id,board,game_id) VALUES(?,?,?)',(match['id'],board,game))
