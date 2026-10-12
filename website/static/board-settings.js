/* Browser-local appearance choices, shared by the account menu and replay. */
(() => {
  const pieces = document.querySelector('[data-piece-style]');
  const boards = document.querySelector('select[data-board-color]');
  if (!pieces || !boards) return;
  const restore = (select, key, fallback) => {
    let value = fallback;
    try { value = localStorage.getItem(key) || fallback; } catch (_) {}
    select.value = Array.from(select.options).some(option => option.value === value) ? value : fallback;
  };
  restore(pieces, 'clubdraft.pieceStyle', 'cardinal');
  restore(boards, 'clubdraft.boardColor', 'brown');
  const applyBoard = () => { document.documentElement.dataset.boardColor = boards.value; };
  applyBoard();
  pieces.addEventListener('change', () => { try { localStorage.setItem('clubdraft.pieceStyle', pieces.value); } catch (_) {} });
  boards.addEventListener('change', () => { applyBoard(); try { localStorage.setItem('clubdraft.boardColor', boards.value); } catch (_) {} });
})();
