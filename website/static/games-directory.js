/* Native details keeps every filter usable without JavaScript. */
(() => {
  const filters = document.querySelector('[data-games-filters]');
  if (!filters) return;
  const mobile = window.matchMedia('(max-width: 700px)');
  const adjust = () => { filters.open = !mobile.matches; };
  adjust();
  mobile.addEventListener('change', adjust);

  const dates = document.querySelectorAll('[data-game-date]');
  const localizeDates = () => {
    const english = (window.LigaI18n?.language || document.documentElement.lang) === 'en';
    const full = new Intl.DateTimeFormat(english ? 'en-GB' : 'pt-PT', {
      day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'
    });
    dates.forEach(element => {
      // The server has already converted the timestamp to its Lisbon calendar date.
      const date = new Date(element.dataset.calendarDate + 'T12:00:00Z');
      if (Number.isNaN(date.getTime())) return;
      element.textContent = full.format(date);
      element.title = full.format(date);
    });
  };
  localizeDates();
  document.addEventListener('liga:languagechange', localizeDates);
})();
