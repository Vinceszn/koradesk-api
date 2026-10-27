import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createFormTracker } from '../app/static/unsaved.mjs';

function control(name, value = '', type = 'text') {
  return { name, value, type, checked: false, autofilled: false, matches() { return this.autofilled; } };
}
function fixture(controls) {
  const handlers = new Map();
  const form = {elements: controls, addEventListener(name, listener) {handlers.set(name, listener);} };
  const changes = [];
  const tracker = createFormTracker(form, dirty => changes.push(dirty));
  const edit = (field, value, {autofill = false, trusted = true} = {}) => {
    field.value = value; field.autofilled = autofill;
    handlers.get('input')({target: field, isTrusted: trusted});
  };
  return {tracker, changes, edit, handlers};
}

test('hidden email and current-password autofill cannot block section navigation', () => {
  const email = control('email');
  const password = control('current_password', '', 'password');
  const {tracker, edit} = fixture([email, password]);
  edit(email, 'saved@example.com', {autofill: true});
  edit(password, 'saved-secret', {autofill: true});
  assert.equal(tracker.dirty, false);
});
test('authentication helpers and untrusted programmatic changes are not edits', () => {
  const password = control('current_password', '', 'password');
  const code = control('code');
  const email = control('email');
  const {tracker, edit} = fixture([password, code, email]);
  edit(password, 'typed-password'); edit(code, '123456');
  edit(email, 'injected@example.com', {trusted:false});
  assert.equal(tracker.dirty, false);
});
test('typing, reverting, and reset retain meaningful unsaved-change protection', () => {
  const name = control('display_name', 'Ada');
  const {tracker, edit, handlers} = fixture([name]);
  edit(name, 'Ada O'); assert.equal(tracker.dirty, true);
  edit(name, 'Ada'); assert.equal(tracker.dirty, false);
  edit(name, 'Edited'); handlers.get('reset')(); assert.equal(tracker.dirty, false);
});
test('real email and new-password edits are protected', () => {
  for (const name of ['email', 'password', 'password_confirmation']) {
    const field = control(name);
    const {tracker, edit} = fixture([field]);
    edit(field, 'user-entered-value'); assert.equal(tracker.dirty, true);
    tracker.clear(); assert.equal(tracker.dirty, false);
  }
});
test('preference selections and checkboxes can be changed and reverted', () => {
  const theme = control('theme', 'dark', 'select-one');
  const card = control('cards', 'units', 'checkbox'); card.checked = true;
  const {tracker, handlers, edit} = fixture([theme, card]);
  edit(theme, 'light'); assert.equal(tracker.dirty, true);
  edit(theme, 'dark'); assert.equal(tracker.dirty, false);
  card.checked = false; handlers.get('change')({target:card,isTrusted:true}); assert.equal(tracker.dirty,true);
  card.checked = true; handlers.get('change')({target:card,isTrusted:true}); assert.equal(tracker.dirty,false);
});
