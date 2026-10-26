(() => {
  const form = document.querySelector('[data-order-form]');
  if (!form) return;
  const lines = form.querySelector('[data-order-lines]');
  const template = form.querySelector('[data-order-line-template]');
  const total = form.querySelector('[data-order-total]');
  const money = value => new Intl.NumberFormat('en-NG', {style: 'currency', currency: 'NGN'}).format(value / 100);

  function refresh() {
    let amount = 0;
    const rows = [...lines.querySelectorAll('[data-order-line]')];
    rows.forEach(row => {
      const option = row.querySelector('[data-variant]').selectedOptions[0];
      const quantity = Number(row.querySelector('[data-quantity]').value || 0);
      const line = Number(option?.dataset.price || 0) * quantity;
      amount += Number.isFinite(line) ? line : 0;
      row.querySelector('[data-line-total]').textContent = option?.value && quantity > 0 ? money(line) : '—';
      row.querySelector('[data-remove-line]').disabled = rows.length === 1;
    });
    total.textContent = money(amount);
    form.querySelector('[data-add-line]').disabled = rows.length >= 20;
  }

  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);
  form.addEventListener('click', event => {
    const add = event.target.closest('[data-add-line]');
    if (add) {
      if (lines.children.length >= 20) return;
      lines.append(template.content.cloneNode(true));
      lines.lastElementChild.querySelector('[data-variant]').focus();
      refresh();
      return;
    }
    const remove = event.target.closest('[data-remove-line]');
    if (remove && lines.children.length > 1) {
      remove.closest('[data-order-line]').remove();
      refresh();
    }
  });

  const customer = form.querySelector('[data-customer-select]');
  const hint = form.querySelector('[data-customer-hint]');
  customer?.addEventListener('change', () => {
    hint.textContent = customer.value
      ? "The linked customer's current details will be captured when this draft is saved."
      : 'Leave these blank for an anonymous or walk-in order.';
  });
  refresh();
})();
