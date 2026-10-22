// Track intentional edits, not password-manager autofill or authentication helpers.
const helpers = new Set(['csrf', 'username', 'current_password', 'code']);
const ignoredTypes = new Set(['hidden', 'submit', 'button', 'reset', 'file']);

function autofilled(control) {
  for (const selector of [':autofill', ':-webkit-autofill', ':-moz-autofill']) {
    try { if (control.matches(selector)) return true; } catch { /* Browser-specific selector. */ }
  }
  return false;
}

function value(control) {
  if (control.type === 'checkbox' || control.type === 'radio') return control.checked;
  if (control.multiple) return [...control.selectedOptions].map(option => option.value).join('\0');
  return control.value;
}

export function createFormTracker(form, changed) {
  const controls = [...form.elements].filter(control => control.name && !helpers.has(control.name) && !ignoredTypes.has(control.type));
  const baseline = new Map(controls.map(control => [control, value(control)]));
  const edited = new Set();
  let dirty = false;
  const update = () => {
    dirty = controls.some(control => edited.has(control) && !autofilled(control) && value(control) !== baseline.get(control));
    changed(dirty);
  };
  const input = event => {
    if (!event.isTrusted || !baseline.has(event.target) || autofilled(event.target)) return;
    edited.add(event.target);
    update();
  };
  form.addEventListener('input', input);
  form.addEventListener('change', input);
  form.addEventListener('reset', () => { edited.clear(); dirty = false; changed(false); });
  return {
    get dirty() { return dirty; },
    clear() { edited.clear(); dirty = false; changed(false); },
    refresh: update,
  };
}
