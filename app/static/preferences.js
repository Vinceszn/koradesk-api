const accountBody = document.body;
const failedForm = [...document.forms].find(form => document.body.dataset.errorPath && new URL(form.action).pathname === document.body.dataset.errorPath);
if (failedForm) {
  const details = failedForm.closest('details');
  if (details) details.open = true;
  const alert = document.querySelector('.account-error');
  if (alert) { failedForm.prepend(alert); alert.tabIndex = -1; alert.focus(); }
}
const deviceTheme = matchMedia('(prefers-color-scheme: light)');
const resolveTheme = value => {
  accountBody.dataset.resolvedTheme = value === 'system' ? (deviceTheme.matches ? 'light' : 'dark') : value;
};
resolveTheme(accountBody.dataset.theme);
deviceTheme.addEventListener('change', () => resolveTheme(accountBody.dataset.theme));
document.querySelector('[data-theme-preview]')?.addEventListener('change', event => resolveTheme(event.target.value));

const dirtyForms = new Set();
document.querySelectorAll('[data-unsaved]').forEach(form => {
  const initial = new URLSearchParams(new FormData(form)).toString();
  const update = () => {
    const dirty = new URLSearchParams(new FormData(form)).toString() !== initial;
    if (dirty) dirtyForms.add(form); else dirtyForms.delete(form);
    const status = form.querySelector('[data-form-status]');
    if (status) status.textContent = dirty ? 'Unsaved changes' : '';
  };
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  form.addEventListener('reset', () => {
    dirtyForms.delete(form);
    setTimeout(() => { update(); resolveTheme(accountBody.dataset.theme); }, 0);
  });
  form.addEventListener('submit', event => {
    const password = form.elements.namedItem('password');
    const confirmation = form.elements.namedItem('password_confirmation');
    if (password && confirmation && password.value !== confirmation.value) {
      event.preventDefault();
      confirmation.setCustomValidity('Passwords must match.');
      confirmation.reportValidity();
      if (event.submitter) { event.submitter.disabled = false; event.submitter.removeAttribute('aria-busy'); }
      return;
    }
    dirtyForms.delete(form);
  });
  form.elements.namedItem('password_confirmation')?.addEventListener('input', event => event.target.setCustomValidity(''));
});
window.addEventListener('beforeunload', event => { if (dirtyForms.size) { event.preventDefault(); event.returnValue = ''; } });
document.querySelectorAll('[data-account-confirm]').forEach(form => form.addEventListener('submit', event => {
  if (!confirm(form.dataset.accountConfirm)) {
    event.preventDefault();
    if (event.submitter) { event.submitter.disabled = false; event.submitter.removeAttribute('aria-busy'); }
  }
}));
document.querySelectorAll('[data-password-toggle]').forEach(button => button.addEventListener('click', () => {
  const input = button.previousElementSibling;
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  button.textContent = show ? 'Hide' : 'Show';
  button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
}));
function downloadFile(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = name;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.querySelector('[data-download-codes]')?.addEventListener('click', () => {
  const codes = [...document.querySelectorAll('#recovery-codes code')].map(node => node.textContent).join('\n');
  downloadFile(new Blob(['Kora Desk recovery codes — keep private. Each code works once.\n\n' + codes], {type:'text/plain;charset=utf-8'}), 'kora-recovery-codes.txt');
});
document.querySelectorAll('[data-download-form]').forEach(form => form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter;
  const status = form.querySelector('[data-download-status]');
  status.textContent = 'Preparing your download…';
  try {
    const response = await fetch(form.action, {method:'POST', body:new FormData(form)});
    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
      const text = await response.text();
      const page = new DOMParser().parseFromString(text, 'text/html');
      throw new Error(page.querySelector('[role=alert] p, .error-message')?.textContent || 'Download could not be prepared. Check your password and code, then try again.');
    }
    downloadFile(await response.blob(), 'kora-personal-data.json');
    status.textContent = 'Download ready. Keep your file private.';
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; button.removeAttribute('aria-busy'); }
}));

const cardKeys = (accountBody.dataset.cards || '').split(',');
document.querySelectorAll('[data-overview-card]').forEach(card => { card.hidden = !cardKeys.includes(card.dataset.overviewCard); });
cardKeys.forEach(key => {
  const card = document.querySelector(`[data-overview-card="${key}"]`);
  if (card) card.parentElement.append(card);
});
const firstChart = document.querySelector('.analytics-grid svg');
if (firstChart) {
  const ns = 'http://www.w3.org/2000/svg';
  const defs = document.createElementNS(ns, 'defs');
  const pattern = document.createElementNS(ns, 'pattern');
  pattern.id = 'kora-chart-pattern'; pattern.setAttribute('width', '8'); pattern.setAttribute('height', '8'); pattern.setAttribute('patternUnits', 'userSpaceOnUse');
  const background = document.createElementNS(ns, 'rect');
  background.setAttribute('width', '8'); background.setAttribute('height', '8'); background.setAttribute('fill', '#a892df');
  const line = document.createElementNS(ns, 'path');
  line.setAttribute('d', 'M-2 2L2 -2M0 8L8 0M6 10L10 6'); line.setAttribute('stroke', '#30213f'); line.setAttribute('stroke-width', '2');
  pattern.append(background, line); defs.append(pattern); firstChart.prepend(defs);
}
if (accountBody.dataset.accountLanguage === 'fr') {
  fetch('/assets/account.fr.json').then(response => response.json()).then(words => {
    const roots = [...document.querySelectorAll('.account-shell, .sidebar, .topbar')];
    const translate = text => words[text] || text;
    roots.forEach(root => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(node => {
        if (node.parentElement.closest('input, script, style, code, .business-access-title h3, .account-identity h2, .account-identity p, .security-event strong')) return;
        const source = node.textContent.trim();
        if (source && words[source]) node.textContent = node.textContent.replace(source, translate(source));
      });
      root.querySelectorAll('[aria-label]').forEach(node => node.setAttribute('aria-label', translate(node.getAttribute('aria-label'))));
    });
  }).catch(() => announce('French labels could not be loaded. English labels remain available.'));
}
