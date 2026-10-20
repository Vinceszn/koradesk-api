const toggle = document.querySelector('.sidebar-toggle');
if (toggle) {
  const mobile = matchMedia('(max-width:800px)');
  const applySidebar = collapsed => {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
  };
  let saved = false;
  try { saved = localStorage.getItem('kora-sidebar-collapsed') === 'true'; } catch {}
  applySidebar(mobile.matches || saved);
  toggle.hidden = false;
  toggle.addEventListener('click', () => {
    const collapsed = !document.body.classList.contains('sidebar-collapsed');
    applySidebar(collapsed);
    if (!mobile.matches) { saved = collapsed; try { localStorage.setItem('kora-sidebar-collapsed', String(collapsed)); } catch {} }
  });
  mobile.addEventListener('change', () => applySidebar(mobile.matches || saved));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && mobile.matches) { applySidebar(true); toggle.focus(); }
  });
}
const switches = document.querySelector('.chart-switch');
if (switches) {
  switches.hidden = false;
  switches.querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
    switches.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    document.querySelectorAll('[data-chart]').forEach(chart => { chart.hidden = chart.dataset.chart !== button.dataset.measure; });
    document.querySelector('.holdings .analytics-heading p').textContent = button.dataset.measure === 'units' ? 'Current quantities by variant' : 'On-hand stock at selling price';
  }));
}
