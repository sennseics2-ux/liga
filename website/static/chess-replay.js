/* Local PGN replay. Legal positions are generated and validated on the server. */
(() => {
  'use strict';
  const root = document.querySelector('[data-chess-replay]');
  const source = document.getElementById('replay-data');
  if (!root || !source) return;
  let game;
  try { game = JSON.parse(source.textContent); } catch (_) { return; }
  if (!Array.isArray(game.positions) || !Array.isArray(game.moves) ||
      game.positions.length !== game.moves.length + 1) return;

  const board = root.querySelector('[data-board]');
  const list = root.querySelector('[data-moves]');
  const progress = root.querySelector('[data-progress]');
  const description = root.querySelector('[data-position-description]');
  const playButton = root.querySelector('[data-action="play"]');
  const flipButton = root.querySelector('[data-action="flip"]');
  const speed = root.querySelector('[data-speed]');
  const pieces = 'KQRBNPkqrbnp';
  const pieceStyleSelect = root.querySelector('[data-piece-style]');
  const availableStyles = new Map(Array.from(pieceStyleSelect.options, option => [option.value, option.dataset.pieceExtension]));
  let pieceStyle = 'cardinal';
  try { const saved = localStorage.getItem('clubdraft.pieceStyle'); if (availableStyles.has(saved)) pieceStyle = saved; } catch (_) {}
  pieceStyleSelect.value = pieceStyle;
  const pieceNames = {k:'king',q:'queen',r:'rook',b:'bishop',n:'knight',p:'pawn'};
  const controlLabels = {first:'First position',prev:'Previous move',next:'Next move',last:'Last position'};
  let index = 0;
  let timer = null;
  let flipped = false;
  const moveButtons = [];

  pieceStyleSelect.addEventListener('change', () => {
    if (!availableStyles.has(pieceStyleSelect.value)) return;
    pieceStyle = pieceStyleSelect.value;
    try { localStorage.setItem('clubdraft.pieceStyle', pieceStyle); } catch (_) {}
    render(index, false);
  });

  function t(key, params = {}) {
    if (window.LigaI18n) return window.LigaI18n.t(key, params);
    return key.replace(/\{(\w+)\}/g, (match, name) => name in params ? String(params[name]) : match);
  }
  function updatePlayState() {
    const playing = timer !== null;
    playButton.textContent = `${playing ? 'Ⅱ' : '▶'} ${t(playing ? 'Pause' : 'Play')}`;
    playButton.setAttribute('aria-label', t(playing ? 'Pause' : 'Play'));
    playButton.setAttribute('aria-pressed', String(playing));
  }
  function stop() {
    if (timer !== null) clearInterval(timer);
    timer = null;
    updatePlayState();
  }
  function positionToBoard(fen) {
    const ranks = fen.split(' ')[0].split('/');
    if (ranks.length !== 8) return [];
    const cells = [];
    for (const rank of ranks) {
      let count = 0;
      for (const symbol of rank) {
        if (/^[1-8]$/.test(symbol)) {
          for (let n = 0; n < Number(symbol); n++) { cells.push(null); count++; }
        } else if (pieces.includes(symbol)) { cells.push(symbol); count++; }
        else return [];
      }
      if (count !== 8) return [];
    }
    return cells;
  }
  function pieceDescription(piece) {
    // Full phrase keys allow languages with gendered piece/color names.
    return piece ? t(`${piece === piece.toUpperCase() ? 'White' : 'Black'} ${pieceNames[piece.toLowerCase()]}`) : t('empty');
  }
  function keepSelectedMoveVisible(button) {
    if (!button) return;
    const bounds = button.getBoundingClientRect();
    const viewport = list.getBoundingClientRect();
    if (bounds.top < viewport.top) list.scrollTop -= viewport.top - bounds.top;
    else if (bounds.bottom > viewport.bottom) list.scrollTop += bounds.bottom - viewport.bottom;
  }
  function render(nextIndex, scrollToMove = true) {
    index = Math.max(0, Math.min(game.moves.length, nextIndex));
    const fen = game.positions[index];
    const squares = positionToBoard(fen);
    if (squares.length !== 64) return;
    const lastMove = index ? game.moves[index - 1].uci : '';
    const from = lastMove.slice(0, 2), to = lastMove.slice(2, 4);
    const fragment = document.createDocumentFragment();
    const occupiedSquares = [];
    for (let rowIndex = 0; rowIndex < 8; rowIndex++) {
      const row = document.createElement('div');
      row.className = 'replay-row';
      row.setAttribute('role', 'row');
      row.setAttribute('aria-rowindex', String(rowIndex + 1));
      for (let column = 0; column < 8; column++) {
        const displayIndex = rowIndex * 8 + column;
        const squareIndex = flipped ? 63 - displayIndex : displayIndex;
        const rank = 8 - Math.floor(squareIndex / 8);
        const file = String.fromCharCode(97 + squareIndex % 8);
        const squareName = `${file}${rank}`;
        const piece = squares[squareIndex];
        const cell = document.createElement('div');
        cell.className = `replay-square ${(Math.floor(squareIndex / 8) + squareIndex % 8) % 2 ? 'dark' : 'light'}`;
        cell.dataset.square = squareName;
        cell.setAttribute('role', 'gridcell');
        cell.setAttribute('aria-colindex', String(column + 1));
        const label = t('{square}: {piece}', {square:squareName, piece:pieceDescription(piece)});
        cell.setAttribute('aria-label', label);
        if (squareName === from || squareName === to) cell.classList.add('last-move');
        if (piece) {
          occupiedSquares.push(label);
          const glyph = document.createElement('img');
          glyph.className = `replay-piece ${piece === piece.toUpperCase() ? 'light-piece' : 'dark-piece'}`;
          glyph.setAttribute('aria-hidden', 'true');
          glyph.alt = '';
          glyph.draggable = false;
          glyph.src = `/static/pieces/${pieceStyle}/${pieceStyle === 'mono' ? '' : (piece === piece.toUpperCase() ? 'w' : 'b')}${piece.toUpperCase()}${availableStyles.get(pieceStyle)}`;
          cell.appendChild(glyph);
        }
        row.appendChild(cell);
      }
      fragment.appendChild(row);
    }
    board.replaceChildren(fragment);
    for (const [moveIndex, button] of moveButtons.entries()) {
      const selected = moveIndex === index - 1;
      button.classList.toggle('selected', selected);
      if (selected) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    }
    const move = game.moves[index - 1];
    const positionLabel = move ? t('Move {number}{suffix} {san} · {current} / {total} half-moves', {
      number:move.move_number, suffix:move.color === 'white' ? '.' : '…',
      san:move.san, current:index, total:game.moves.length
    }) : t('Starting position');
    progress.textContent = positionLabel;
    const turn = t('{color} to move', {color:t(fen.split(' ')[1] === 'b' ? 'Black' : 'White')});
    description.textContent = t('{position}. {turn}. {pieces}', {
      position:positionLabel, turn, pieces:occupiedSquares.join('; ')
    });
    root.querySelector('[data-action="first"]').disabled = index === 0;
    root.querySelector('[data-action="prev"]').disabled = index === 0;
    root.querySelector('[data-action="next"]').disabled = index === game.moves.length;
    root.querySelector('[data-action="last"]').disabled = index === game.moves.length;
    if (scrollToMove) keepSelectedMoveVisible(moveButtons[index - 1]);
    if (index === game.moves.length) stop();
  }
  function updateCoordinates() {
    const files = root.querySelector('[data-file-coords]');
    const ranks = root.querySelector('[data-rank-coords]');
    files.replaceChildren();
    ranks.replaceChildren();
    for (let i = 0; i < 8; i++) {
      const file = document.createElement('span');
      file.textContent = String.fromCharCode(97 + (flipped ? 7 - i : i));
      files.appendChild(file);
      const rank = document.createElement('span');
      rank.textContent = String(flipped ? i + 1 : 8 - i);
      ranks.appendChild(rank);
    }
    flipButton.setAttribute('aria-pressed', String(flipped));
  }
  function goto(ply) { stop(); render(ply); }
  function start() {
    if (index >= game.moves.length) render(0);
    timer = setInterval(() => render(index + 1), Number(speed.value));
    updatePlayState();
  }
  function togglePlay() { if (timer !== null) stop(); else start(); }
  function flip() { flipped = !flipped; updateCoordinates(); render(index, false); }

  // One number/White/Black row per actual full move, including a Black start.
  const rows = [];
  for (const [moveIndex, move] of game.moves.entries()) {
    let row = rows[rows.length - 1];
    if (!row || row.number !== move.move_number) {
      row = {number:move.move_number, white:null, black:null};
      rows.push(row);
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'replay-move';
    button.textContent = move.san;
    button.addEventListener('click', () => goto(moveIndex + 1));
    moveButtons.push(button);
    row[move.color] = button;
  }
  const movesFragment = document.createDocumentFragment();
  for (const row of rows) {
    const number = document.createElement('span');
    number.className = 'replay-move-number';
    number.textContent = `${row.number}.`;
    movesFragment.appendChild(number);
    for (const color of ['white', 'black']) {
      const cell = row[color] || document.createElement('span');
      if (!row[color]) { cell.className = 'replay-move-placeholder'; cell.setAttribute('aria-hidden', 'true'); }
      movesFragment.appendChild(cell);
    }
  }
  list.appendChild(movesFragment);
  for (const [action, callback] of Object.entries({
    first:() => goto(0), prev:() => goto(index - 1), next:() => goto(index + 1),
    last:() => goto(game.moves.length), play:togglePlay, flip
  })) root.querySelector(`[data-action="${action}"]`).addEventListener('click', callback);
  speed.addEventListener('change', () => {
    if (timer !== null) { stop(); start(); }
  });
  root.addEventListener('keydown', (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.target.closest('input, select, textarea, [contenteditable="true"]')) return;
    const actions = {ArrowLeft:() => goto(index - 1), ArrowRight:() => goto(index + 1),
      Home:() => goto(0), End:() => goto(game.moves.length), f:flip, F:flip};
    // Space on a button retains its normal native activation.
    if (event.key === ' ' && !event.target.closest('button, a')) actions[' '] = togglePlay;
    if (actions[event.key]) { event.preventDefault(); actions[event.key](); }
  });
  function localizeReplay() {
    root.setAttribute('aria-label', t('Chess replay'));
    board.setAttribute('aria-label', t('Chessboard showing game position'));
    list.setAttribute('aria-label', t('Click any move to jump to that position'));
    speed.setAttribute('aria-label', t('Playback speed'));
    for (const [action, label] of Object.entries(controlLabels)) {
      const button = root.querySelector(`[data-action="${action}"]`);
      button.setAttribute('aria-label', t(label));
      button.title = t(label);
    }
    for (const [moveIndex, button] of moveButtons.entries()) {
      const move = game.moves[moveIndex];
      const label = t('Go to move {number} {color}: {san}', {
        number:move.move_number, color:t(move.color === 'white' ? 'White' : 'Black'), san:move.san
      });
      button.title = label;
      button.setAttribute('aria-label', label);
    }
    updatePlayState();
    render(index, false);
  }
  document.addEventListener('liga:languagechange', localizeReplay);
  window.addEventListener('pagehide', stop);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  updateCoordinates();
  localizeReplay();
})();
