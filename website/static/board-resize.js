/* Desktop board sizing; geometry and annotation coordinates scale with the board. */
(() => {
  const root = document.querySelector('[data-chess-replay]');
  const handle = root?.querySelector('[data-board-resize]');
  const panel = root?.querySelector('.replay-board-panel');
  if (!handle || !panel) return;
  const desktop = window.matchMedia('(min-width:901px) and (hover:hover) and (pointer:fine)');
  const key = 'clubdraft.replayBoardSize';
  let requested = null, drag = null, origin = null;
  try {
    const saved = Number(localStorage.getItem(key));
    if (Number.isFinite(saved) && saved >= 320 && saved <= 920) requested = saved;
  } catch (_) {}
  const maximum = () => Math.max(320, Math.min(920, root.clientWidth-(origin || 0)-298));
  const clamp = value => Math.round(Math.max(320, Math.min(maximum(), value)));
  const updateValue = () => {
    handle.setAttribute('aria-valuemin','320');
    handle.setAttribute('aria-valuemax',String(Math.floor(maximum())));
    handle.setAttribute('aria-valuenow',String(Math.round(panel.getBoundingClientRect().width)));
  };
  const apply = size => {
    if (origin===null) {
      origin=Math.max(0, Math.min(panel.getBoundingClientRect().left-root.getBoundingClientRect().left,root.clientWidth-618));
      root.style.setProperty('--replay-board-offset',`${origin}px`);
    }
    requested = clamp(size);
    root.style.setProperty('--replay-board-size',`${requested}px`);
    root.classList.add('replay-resized');
    updateValue();
  };
  const save = () => { if (requested!==null) { try { localStorage.setItem(key,String(requested)); } catch (_) {} } };
  const finish = () => {
    if (!drag) return;
    const pointer = drag.pointer;
    drag = null;
    document.documentElement.classList.remove('board-resize-active');
    if (handle.hasPointerCapture(pointer)) handle.releasePointerCapture(pointer);
    save();
  };
  handle.addEventListener('pointerdown', event => {
    if (!desktop.matches || event.button!==0 || event.pointerType!=='mouse') return;
    event.preventDefault();event.stopPropagation();
    drag={pointer:event.pointerId,x:event.clientX,y:event.clientY,size:panel.getBoundingClientRect().width};
    handle.setPointerCapture(event.pointerId);
    document.documentElement.classList.add('board-resize-active');
  });
  handle.addEventListener('pointermove', event => {
    if (!drag || drag.pointer!==event.pointerId) return;
    apply(drag.size+((event.clientX-drag.x)+(event.clientY-drag.y))/2);
  });
  handle.addEventListener('pointerup',finish);
  handle.addEventListener('pointercancel',finish);
  handle.addEventListener('lostpointercapture',finish);
  window.addEventListener('blur',finish);
  handle.addEventListener('keydown', event => {
    if (!desktop.matches) return;
    const size=panel.getBoundingClientRect().width;
    const steps={ArrowLeft:size-16,ArrowDown:size-16,ArrowRight:size+16,ArrowUp:size+16,Home:320,End:maximum()};
    if (!(event.key in steps)) return;
    event.preventDefault();event.stopPropagation();
    apply(steps[event.key]);save();
  });
  const refresh = () => {
    finish();origin=null;
    root.style.removeProperty('--replay-board-offset');
    root.style.removeProperty('--replay-board-size');root.classList.remove('replay-resized');
    if (!desktop.matches) {
      updateValue();return;
    } else if (requested!==null) apply(requested);
    updateValue();
  };
  window.addEventListener('resize',refresh);
  desktop.addEventListener('change',refresh);
  window.addEventListener('pagehide',finish);
  refresh();
})();
