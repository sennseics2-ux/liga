/* Browser-local appearance choices with progressive, keyboard-accessible previews. */
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

  function preview(option, pieceSet) {
    const sample = document.createElement('span');
    sample.setAttribute('aria-hidden', 'true');
    sample.setAttribute('data-no-i18n', '');
    if (pieceSet) {
      sample.className = 'piece-set-preview';
      for (const piece of 'KQRBNP') {
        const img = document.createElement('img');
        img.alt = '';
        img.loading = 'lazy';
        img.draggable = false;
        img.src = `/static/pieces/${option.value}/${option.value === 'mono' ? '' : 'w'}${piece}${option.dataset.pieceExtension}`;
        sample.appendChild(img);
      }
    } else {
      sample.className = 'board-color-preview';
      sample.dataset.boardColor = option.value;
    }
    return sample;
  }

  function enhance(select, pieceSet) {
    const labelFor = option => !pieceSet && window.LigaI18n
      ? window.LigaI18n.t(option.dataset.i18n) : option.textContent;
    const field = select.closest('.appearance-field');
    const picker = document.createElement('details');
    picker.className = 'appearance-picker';
    picker.dataset.appearancePicker = pieceSet ? 'pieces' : 'board';
    const summary = document.createElement('summary');
    const selectedName = document.createElement('span');
    selectedName.className = 'appearance-choice-name';
    selectedName.id = `${select.id}-selected-name`;
    selectedName.setAttribute('data-no-i18n', '');
    summary.setAttribute('aria-labelledby', `${select.id}-label ${selectedName.id}`);
    summary.appendChild(selectedName);
    const options = document.createElement('div');
    options.className = 'appearance-options';
    options.setAttribute('role', 'listbox');
    options.setAttribute('aria-labelledby', `${select.id}-label`);
    const entries = Array.from(select.options, option => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'appearance-option';
      button.setAttribute('role', 'option');
      button.setAttribute('data-no-i18n', '');
      button.dataset.value = option.value;
      const name = document.createElement('span');
      name.className = 'appearance-choice-name';
      button.append(name, preview(option, pieceSet));
      button.addEventListener('click', () => {
        select.value = option.value;
        select.dispatchEvent(new Event('change', {bubbles:true}));
        picker.open = false;
        summary.focus();
      });
      options.appendChild(button);
      return {option, button, name};
    });
    const sync = () => {
      const current = select.selectedOptions[0];
      selectedName.textContent = labelFor(current);
      summary.querySelector('.piece-set-preview, .board-color-preview')?.remove();
      summary.appendChild(preview(current, pieceSet));
      for (const {option, button, name} of entries) {
        name.textContent = labelFor(option);
        const selected = option.value === select.value;
        button.setAttribute('aria-selected', String(selected));
        button.tabIndex = selected ? 0 : -1;
      }
    };
    const focusAt = index => {
      const entry = entries[(index + entries.length) % entries.length];
      for (const {button} of entries) button.tabIndex = button === entry.button ? 0 : -1;
      entry.button.focus({preventScroll:true});
      const button = entry.button.getBoundingClientRect();
      const viewport = options.getBoundingClientRect();
      if (button.top < viewport.top) options.scrollTop -= viewport.top - button.top;
      else if (button.bottom > viewport.bottom) options.scrollTop += button.bottom - viewport.bottom;
    };
    summary.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        picker.open = true;
        focusAt(select.selectedIndex);
      }
    });
    options.addEventListener('keydown', event => {
      const at = entries.findIndex(entry => entry.button === document.activeElement);
      if (at < 0) return;
      const targets = {ArrowDown:at+1, ArrowUp:at-1, Home:0, End:entries.length-1};
      if (event.key in targets) { event.preventDefault(); focusAt(targets[event.key]); }
      else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); picker.open = false; summary.focus(); }
      else if (event.key.length === 1 && /\S/.test(event.key) && !event.altKey && !event.ctrlKey && !event.metaKey) {
        const next = entries.map((_, n) => (at+n+1)%entries.length).find(index => entries[index].name.textContent.toLocaleLowerCase().startsWith(event.key.toLocaleLowerCase()));
        if (next !== undefined) { event.preventDefault(); focusAt(next); }
      }
    });
    picker.addEventListener('toggle', () => {
      if (!picker.open) return;
      for (const other of field.parentElement.querySelectorAll('.appearance-picker')) if (other !== picker) other.open = false;
      const selected = entries[select.selectedIndex].button;
      options.scrollTop = Math.max(0, selected.offsetTop - options.offsetTop - options.clientHeight / 2);
    });
    select.addEventListener('change', sync);
    document.addEventListener('liga:languagechange', sync);
    picker.append(summary, options);
    field.appendChild(picker);
    field.classList.add('appearance-enhanced');
    sync();
  }
  enhance(pieces, true);
  enhance(boards, false);
})();
