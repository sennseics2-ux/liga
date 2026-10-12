/* Native details keeps every filter usable without JavaScript. */
(() => {
  const filters = document.querySelector('[data-games-filters]');
  if (!filters) return;
  const mobile = window.matchMedia('(max-width: 700px)');
  const adjust = () => { filters.open = !mobile.matches; };
  adjust();
  mobile.addEventListener('change', adjust);
})();
