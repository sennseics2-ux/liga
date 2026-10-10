"""Chess PGN validation and board position generation.

python-chess is a runtime dependency, not bundled with this application.
Replayer positions are computed on the server so viewers require no internet access.
"""
from datetime import datetime, timezone
from io import StringIO

MAX_PGN_BYTES = 256 * 1024
MAX_PLIES = 800
RESULTS = ('*', '1-0', '0-1', '1/2-1/2')


def parse_pgn(text: str) -> dict:
    try:
        import chess.pgn
    except ImportError:
        raise ValueError('PGN viewing requires the chess package. Run: python -m pip install -r requirements.txt') from None

    if not isinstance(text, str) or not text.strip():
        raise ValueError('Select a non-empty PGN game.')
    if len(text.encode('utf-8')) > MAX_PGN_BYTES:
        raise ValueError('PGN files must be 256 KB or smaller.')
    stream = StringIO(text)
    game = chess.pgn.read_game(stream)
    if game is None:
        raise ValueError('No chess game was found in the PGN.')
    if game.errors:
        raise ValueError(f'Invalid chess moves in PGN: {str(game.errors[0])[:160]}')
    if chess.pgn.read_game(stream) is not None:
        raise ValueError('Upload one PGN game per match, not a multi-game collection.')
    if game.headers.get('Variant', 'Standard') not in ('Standard', 'Chess', '?'):
        raise ValueError('Only standard chess games are supported for replay.')
    board = game.board()
    if not board.is_valid():
        raise ValueError('The PGN starts from an invalid chess position.')
    moves = []
    positions = [board.fen()]
    for ply, move in enumerate(game.mainline_moves(), start=1):
        if ply > MAX_PLIES:
            raise ValueError(f'PGN is too long (maximum {MAX_PLIES} half-moves).')
        san = board.san(move)
        # A SetUp/FEN game may start with Black, or after move one. The
        # position is authoritative; a replay-relative ply is only an index.
        move_number = board.fullmove_number
        color = 'white' if board.turn == chess.WHITE else 'black'
        board.push(move)
        positions.append(board.fen())
        moves.append({'san': san, 'uci': move.uci(), 'ply': ply,
                      'move_number': move_number, 'color': color})
    if not moves:
        raise ValueError('The PGN must contain at least one legal move.')
    result = game.headers.get('Result', '*')
    if result not in RESULTS:
        raise ValueError('PGN result is not valid.')
    return {'positions': positions, 'moves': moves, 'result': result,
            'headers': dict(game.headers)}


def parse_timestamp(value: str) -> str:
    """Accept UTC HTML datetime-local or an ISO timestamp; persist UTC ISO."""
    try:
        dt = datetime.fromisoformat(str(value).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        if not 2000 <= dt.year <= 2100:
            raise ValueError
        return dt.isoformat(timespec='seconds')
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Enter a valid match date/time (2000–2100, UTC).') from None


def awards(result: str) -> tuple[int, int]:
    return {'*': (0, 0), '1-0': (3, 0), '0-1': (0, 3), '1/2-1/2': (1, 1)}[result]
