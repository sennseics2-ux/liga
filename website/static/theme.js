// Apply the preference before styles paint, then connect the accessible toggle.
(() => {
  const key = 'clubdraft.theme';
  const root = document.documentElement;
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const stored = () => { try { return localStorage.getItem(key); } catch (_) { return null; } };
  const preference = stored();
  root.dataset.theme = ['light', 'dark'].includes(preference) ? preference : (system.matches ? 'dark' : 'light');
  const sync = () => {
    const button = document.getElementById('theme-toggle');
    if (button) button.setAttribute('aria-pressed', String(root.dataset.theme === 'dark'));
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = root.dataset.theme === 'dark' ? '#151922' : '#171819';
  };
  document.addEventListener('DOMContentLoaded', () => {
    sync();
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(key, root.dataset.theme); } catch (_) {}
      sync();
    });
  });
  system.addEventListener('change', () => {
    if (!['light', 'dark'].includes(stored())) {
      root.dataset.theme = system.matches ? 'dark' : 'light';
      sync();
    }
  });
})();
