const announce = message => { document.getElementById('ui-announcement').textContent = message; };
document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const input = document.getElementById(button.dataset.copy);
    try { await navigator.clipboard.writeText(input.value); announce('Invitation link copied.'); button.querySelector('span').textContent = 'Copied!'; }
    catch { input.focus(); input.select(); announce('Select and copy the invitation link.'); }
  });
});
document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', () => { if (history.length > 1) history.back(); else location.assign('/'); }));
document.querySelectorAll('[data-tabs]').forEach(tablist => {
  const tabs = [...tablist.querySelectorAll('[data-tab]')];
  const activate = tab => {
    tabs.forEach(item => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
      const panel = document.getElementById(item.dataset.tab);
      panel.hidden = !active;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', item.id);
    });
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activate(tab));
    tab.addEventListener('keydown', event => {
      let target;
      if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
      if (event.key === 'ArrowLeft') target = tabs[(index + tabs.length - 1) % tabs.length];
      if (event.key === 'Home') target = tabs[0];
      if (event.key === 'End') target = tabs[tabs.length - 1];
      if (target) { event.preventDefault(); activate(target); target.focus(); }
    });
  });
  tablist.hidden = false;
  activate(tabs[0]);
});
document.querySelectorAll('[data-product-list]').forEach(list => {
  const search = list.querySelector('[data-product-search]');
  const filter = list.querySelector('[data-stock-filter]');
  const rows = [...list.querySelectorAll('[data-product-row]')];
  const update = () => {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    rows.forEach(row => {
      row.hidden = !(row.dataset.search.includes(query) && (filter.value === 'all' || row.dataset.stockStatus === filter.value));
      if (!row.hidden) visible++;
    });
    list.querySelector('[data-no-results]').hidden = visible !== 0 || rows.length === 0;
    list.querySelector('[data-filter-status]').textContent = visible + ' of ' + rows.length + ' variants shown';
  };
  list.querySelector('[data-search-controls]').hidden = false;
  search.addEventListener('input', update);
  filter.addEventListener('change', update);
  list.querySelector('[data-reset-search]').addEventListener('click', () => { search.value = ''; filter.value = 'all'; update(); search.focus(); });
});
const dialog = document.getElementById('confirm-action');
let pendingForm;
document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (form.dataset.confirmed) return;
    event.preventDefault();
    pendingForm = form;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else if (window.confirm('Remove this person’s access to this business?')) { form.dataset.confirmed = 'true'; form.requestSubmit(); }
  });
});
dialog.querySelector('[data-cancel]').addEventListener('click', () => dialog.close());
dialog.querySelector('[data-confirm-submit]').addEventListener('click', () => {
  if (!pendingForm) return;
  const form = pendingForm;
  dialog.close();
  form.dataset.confirmed = 'true';
  form.requestSubmit();
});
dialog.addEventListener('close', () => { pendingForm = null; });
document.querySelectorAll('form').forEach(form => form.addEventListener('submit', event => {
  if (event.defaultPrevented) return;
  const button = event.submitter;
  if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
}));
window.addEventListener('pageshow', () => document.querySelectorAll('button[aria-busy]').forEach(button => { button.disabled = false; button.removeAttribute('aria-busy'); }));
