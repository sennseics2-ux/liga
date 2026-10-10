function refreshCountdowns() {
  for (const el of document.querySelectorAll('.countdown')) {
    const t = (key) => window.LigaI18n ? window.LigaI18n.t(key) : key;
    if (['closed','failed','cancelled'].includes(el.dataset.closeStatus)) {
      el.textContent = t(el.dataset.closeStatus === 'failed' ? 'Settlement failed' : el.dataset.closeStatus === 'cancelled' ? 'Auction cancelled' : 'Closed');
      continue;
    }
    const end = Date.parse(el.dataset.ends);
    if (!Number.isFinite(end)) { el.textContent = '—'; continue; }
    const remaining = Math.max(0, Math.floor((end - Date.now()) / 1000));
    if (remaining === 0) { el.textContent = t('Ended'); continue; }
    const d = Math.floor(remaining / 86400), h = Math.floor((remaining % 86400) / 3600),
          m = Math.floor((remaining % 3600) / 60), s = remaining % 60;
    el.textContent = d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${String(s).padStart(2, '0')}s`;
  }
}
refreshCountdowns();
setInterval(refreshCountdowns, 1000);
const toggle = document.querySelector('.mobile-toggle');
if (toggle) toggle.addEventListener('click', () => {
  const open = document.getElementById('nav-links').classList.toggle('open');
  toggle.setAttribute('aria-expanded', String(open));
});
for (const form of document.querySelectorAll('form[data-confirm]')) {
  form.addEventListener('submit', (event) => {
    if (!confirm(form.dataset.confirm)) event.preventDefault();
  });
}

// Accessible account menu: click to open, click elsewhere or press Escape to close.
const accountToggle = document.getElementById('account-toggle');
const accountMenu = document.getElementById('account-menu');
if (accountToggle && accountMenu) {
  const closeAccountMenu = (restoreFocus = false) => {
    accountMenu.hidden = true;
    accountToggle.setAttribute('aria-expanded', 'false');
    if (restoreFocus) accountToggle.focus();
  };
  accountToggle.addEventListener('click', () => {
    const shouldOpen = accountMenu.hidden;
    accountMenu.hidden = !shouldOpen;
    accountToggle.setAttribute('aria-expanded', String(shouldOpen));
    if (shouldOpen) {
      const languageMenu = document.getElementById('language-menu');
      const languageToggle = document.getElementById('language-toggle');
      if (languageMenu && languageToggle) {
        languageMenu.hidden = true;
        languageToggle.setAttribute('aria-expanded', 'false');
      }
    }
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.account-dropdown')) closeAccountMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !accountMenu.hidden) closeAccountMenu(true);
  });
  accountMenu.addEventListener('focusout', (event) => {
    if (event.relatedTarget && !accountMenu.contains(event.relatedTarget) && event.relatedTarget !== accountToggle)
      closeAccountMenu();
  });
}

// Refresh auction state on a modest interval and when returning to the app.
// Keep the user's unfinished forms intact; offer a reload for the full history.
(() => {
  const roots = [...document.querySelectorAll('[data-auction-id]')];
  if (!roots.length) return;
  const ids = [...new Set(roots.map(root => root.dataset.auctionId))].slice(0, 100);
  let pending = false;
  let lastUpdate = 0;
  const previous = new Map();
  const translate = (key) => window.LigaI18n ? window.LigaI18n.t(key) : key;
  const notice = (key) => {
    let box = document.querySelector('[data-auction-update-notice]');
    if (!box) {
      box = document.createElement('div');
      box.className = 'container notice notice-info';
      box.dataset.auctionUpdateNotice = '';
      box.setAttribute('role', 'status');
      const text = document.createElement('span');
      text.dataset.liveNoticeText = '';
      const reload = document.createElement('a');
      reload.className = 'text-link';
      reload.href = window.location.pathname + window.location.search;
      reload.dataset.i18n = 'Refresh auction';
      reload.textContent = translate('Refresh auction');
      box.append(text, document.createTextNode(' '), reload);
      document.querySelector('main').prepend(box);
    }
    const text = box.querySelector('[data-live-notice-text]');
    text.dataset.i18n = key;
    text.textContent = translate(key);
  };
  async function refresh(force = false) {
    if (pending || document.hidden || (!force && Date.now()-lastUpdate<25000)) return;
    pending = true;
    try {
      const response = await fetch('/api/auctions/snapshot?ids=' + ids.join(','), {
        credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}
      });
      if (!response.ok) throw new Error('Auction update unavailable');
      const data = await response.json();
      if (!Array.isArray(data.auctions)) throw new Error('Invalid auction update');
      for (const value of document.querySelectorAll('[data-live-total-available]')) value.textContent = data.available_credits ?? '—';
      for (const item of data.auctions) {
        const key = String(item.id);
        const before = previous.get(key);
        if (before && (before.status !== item.status || before.high_bid !== item.high_bid || before.bid_count !== item.bid_count)) {
          notice(item.status === 'closed' ? 'Auction closed' :
            item.my_bid && item.high_bid_team_id !== data.viewer_team_id ? 'You have been outbid.' :
              'Auction updated. Reload to see the latest bids.');
        }
        previous.set(key, item);
        for (const root of roots.filter(root => root.dataset.auctionId === key)) {
          for (const value of root.querySelectorAll('[data-live-high-bid]')) value.textContent = item.high_bid;
          for (const value of root.querySelectorAll('[data-live-bid-count]')) value.textContent = item.bid_count;
          for (const value of root.querySelectorAll('[data-live-minimum]')) value.textContent = item.minimum;
          for (const value of root.querySelectorAll('[data-live-available]')) value.textContent = item.available ?? '—';
          for (const value of root.querySelectorAll('[data-live-position]')) {
            const label = item.status !== 'open' ? 'Closed' : item.high_bid_team_id === data.viewer_team_id ? 'Leading' : 'Outbid';
            value.dataset.i18n = label;
            value.textContent = translate(label);
          }
          for (const countdown of root.querySelectorAll('.countdown')) countdown.dataset.closeStatus = item.status;
          for (const form of root.querySelectorAll('[data-live-bid-form]')) {
            const input = form.querySelector('[name="amount"]');
            if (!input) continue;
            const untouched = input.value === input.defaultValue;
            input.min = item.minimum;
            if (item.available != null) input.max = item.available;
            if (untouched) { input.value = item.minimum; input.defaultValue = item.minimum; }
            const disabled = item.status !== 'open' || !data.viewer_team_id || item.available < item.minimum;
            input.disabled = disabled;
            for (const button of form.querySelectorAll('button[type="submit"]')) button.disabled = disabled;
          }
        }
      }
      lastUpdate = Date.now();
      refreshCountdowns();
    } catch (error) {
      // Retry on the next tick; temporary connectivity must not erase a bid.
      lastUpdate = Date.now();
    } finally { pending = false; }
  }
  refresh(true);
  setInterval(() => refresh(), 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(true); });
  window.addEventListener('pageshow', () => refresh(true));
  window.addEventListener('online', () => refresh(true));
  window.addEventListener('liga:languagechange', refreshCountdowns);
})();

// CSP-compatible administration page selector.
document.querySelectorAll('[data-page-navigation]').forEach(select => {
  select.addEventListener('change', () => {
    if (select.value.startsWith('/admin')) window.location.assign(select.value);
  });
});

// Recovery secrets stay in the URL fragment and never enter access logs.
if (window.location.pathname === '/reset-password') {
  const tokenInput = document.querySelector('input[name="token"]');
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token');
  if (tokenInput && token && /^[A-Za-z0-9_-]{40,80}$/.test(token)) {
    tokenInput.value = token;
    window.history.replaceState(null, '', '/reset-password');
  }
}
