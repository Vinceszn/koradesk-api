(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const root = $('#pos');
  if (!root) return;
  document.body.classList.add('pos-workspace');
  const products = [...document.querySelectorAll('#pos-catalogue span')].map(node => ({
    ...node.dataset, id:Number(node.dataset.id), price:Number(node.dataset.price), available:Number(node.dataset.available)
  }));
  const byId = new Map(products.map(product => [product.id, product]));
  const codes = new Map([...document.querySelectorAll('#pos-codes span')].map(node => [node.dataset.code, Number(node.dataset.id)]));
  const productCodes = new Map();
  for (const [code, id] of codes) productCodes.set(id, [...(productCodes.get(id) || []), code]);
  const search = $('#pos-search'), results = $('#pos-results'), form = $('#pos-checkout');
  const payment = $('#pos-payment'), cash = $('#pos-cash'), complete = $('#pos-complete');
  const customer = $('#pos-customer'), keyInput = form.elements.key;
  const basket = new Map(), favorites = new Set();
  const storageKey = 'kora-pos:' + location.pathname;
  const favoriteKey = storageKey + ':favorites';
  const money = value => new Intl.NumberFormat('en-NG', {style:'currency', currency:'NGN'}).format(value / 100);
  const itemName = product => product.name + ' · ' + product.label;
  let filter = 'all', total = 0, units = 0, busy = false, attempt = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function button(className, text, label, action) {
    const node = element('button', className, text);
    node.type = 'button';
    if (label) node.setAttribute('aria-label', label);
    node.addEventListener('click', action);
    return node;
  }
  function message(text, error = false) {
    $('#pos-status').textContent = text;
    $('#pos-status').dataset.error = String(error);
  }
  function save() {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({key:keyInput.value, rows:[...basket.values()], customer:customer.value, cash:cash.value, attempt}));
    } catch { message('This browser cannot save the basket. Keep this tab open until the sale completes.', true); }
  }
  function issue(row) {
    const product = byId.get(row.id);
    if (!product || product.archived === 'yes') return 'No longer available. Remove this item.';
    if (product.available < row.qty) return 'Only ' + Math.max(0, product.available) + ' available. Reduce the quantity.';
    if (product.price !== row.price) return 'Price changed to ' + money(product.price) + '. Update the basket.';
    return '';
  }
  try {
    for (const id of JSON.parse(localStorage.getItem(favoriteKey) || '[]')) favorites.add(Number(id));
  } catch { /* Favourites are optional when browser storage is unavailable. */ }
  try {
    // Consume the success marker, so refreshing this URL cannot erase a new sale.
    if (new URLSearchParams(location.search).has('sold')) {
      sessionStorage.removeItem(storageKey);
      history.replaceState(null, '', location.pathname);
    } else {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
      if (saved && /^[a-f0-9]{48}$/.test(saved.key) && Array.isArray(saved.rows)) {
        keyInput.value = saved.key;
        for (const row of saved.rows.slice(0,40)) {
          if (Number.isInteger(row.id) && Number.isInteger(row.qty) && row.qty > 0 && Number.isInteger(row.price)) {
            basket.set(row.id, {...row, ...(byId.get(row.id) || {}), price:row.price, qty:row.qty});
          }
        }
        customer.value = saved.customer || '';
        cash.value = saved.cash || '';
        attempt = saved.attempt || null;
        if (basket.size) message('Previous basket restored. Ready to continue.');
      }
    }
  } catch { message('Saved basket could not be restored. Start a new sale.', true); }

  function browse() {
    const query = search.value.trim().toLocaleLowerCase();
    const matches = products.filter(product => product.archived !== 'yes'
      && (filter !== 'available' || product.available > 0)
      && (filter !== 'favorites' || favorites.has(product.id))
      && (!query || [product.name,product.label,product.sku,...(productCodes.get(product.id) || [])].join(' ').toLocaleLowerCase().includes(query)))
      .sort((a,b) => Number(b.available > 0) - Number(a.available > 0) || a.name.localeCompare(b.name));
    results.replaceChildren();
    for (const product of matches) {
      const card = element('article', 'pos-product');
      card.dataset.tone = product.id % 4;
      const addButton = button('pos-product-add', undefined, 'Add ' + itemName(product) + ', ' + money(product.price), () => add(product));
      addButton.disabled = product.available < 1 || busy || !!attempt;
      const initials = product.name.split(/\s+/).filter(Boolean).slice(0,2).map(word => word[0]).join('').toUpperCase();
      const mark = element('span', 'pos-product-mark', initials);
      mark.setAttribute('aria-hidden','true');
      addButton.append(mark, element('span','pos-product-name',product.name), element('span','pos-product-label',product.label), element('span','pos-product-sku',product.sku), element('span','pos-product-price',money(product.price)));
      const remaining = product.available - (basket.get(product.id)?.qty || 0);
      addButton.append(element('span', 'pos-product-stock' + (remaining < 1 ? ' unavailable' : ''), product.counted !== 'yes' ? 'Stock not counted' : product.available < 1 ? 'Out of stock' : remaining === 0 ? 'All available units in basket' : remaining + ' available'));
      const favorite = button('pos-favorite', favorites.has(product.id) ? '★' : '☆', 'Favourite ' + itemName(product), () => {
        if (favorites.has(product.id)) favorites.delete(product.id); else favorites.add(product.id);
        try { localStorage.setItem(favoriteKey, JSON.stringify([...favorites])); } catch { message('Favourites will only last while this page is open.'); }
        browse();
      });
      favorite.setAttribute('aria-pressed',String(favorites.has(product.id)));
      card.append(addButton,favorite);
      if (basket.has(product.id)) card.append(element('span','pos-quantity-badge',basket.get(product.id).qty + ' in sale'));
      results.append(card);
    }
    $('#pos-result-count').textContent = matches.length + ' product variant' + (matches.length === 1 ? '' : 's');
    $('#pos-search-clear').hidden = !query;
    $('#pos-no-results').hidden = matches.length !== 0;
    results.hidden = !matches.length;
    $('#pos-empty-message').textContent = filter === 'favorites' && !query ? 'Use the star on a product to keep your regular items here. Favourites are saved on this browser.' : query ? 'Try a product name, variant, SKU or assigned barcode.' : 'Add products to your catalogue or try another filter.';
  }
  function setQuantity(id, qty) {
    if (busy || attempt) return;
    const row = basket.get(id), product = byId.get(id);
    if (!Number.isInteger(qty) || qty < 1 || qty > (product?.available || 0)) {
      message('Enter a whole quantity between 1 and ' + Math.max(0, product?.available || 0) + '.', true);
      render(); return;
    }
    const focusedLabel = document.activeElement?.getAttribute('aria-label');
    row.qty = qty; cash.value = ''; render();
    const replacement = [...document.querySelectorAll('#pos-lines [aria-label]')].find(node => node.getAttribute('aria-label') === focusedLabel);
    if (replacement && !replacement.disabled) replacement.focus({preventScroll:true});
  }
  function render() {
    const lines = $('#pos-lines');
    lines.replaceChildren(); total = 0; units = 0;
    let needsReview = false;
    for (const [id,row] of basket) {
      total += row.qty * row.price; units += row.qty;
      const line = element('div','pos-line'), info = element('div','pos-line-info');
      info.append(element('p','pos-line-name',row.name),element('p','pos-line-variant',row.label + ' · ' + row.sku),element('p','pos-line-variant',money(row.price) + ' each'));
      const stepper = element('div','pos-stepper');
      const minus = button('', '−', 'Decrease quantity for ' + itemName(row), () => setQuantity(id,row.qty-1));
      minus.disabled = row.qty <= 1 || busy || !!attempt;
      const qty = element('input');
      qty.type = 'number'; qty.inputMode = 'numeric'; qty.min = 1; qty.max = Math.max(row.qty,byId.get(id)?.available || 0); qty.value = row.qty;
      qty.setAttribute('aria-label','Quantity for ' + itemName(row)); qty.disabled = busy || !!attempt;
      qty.addEventListener('change', () => setQuantity(id,Number(qty.value)));
      const plus = button('', '+', 'Increase quantity for ' + itemName(row), () => setQuantity(id,row.qty+1));
      plus.disabled = row.qty >= (byId.get(id)?.available || 0) || busy || !!attempt;
      stepper.append(minus,qty,plus); info.append(stepper);
      const amount = element('div');
      const remove = button('pos-line-remove','Remove','Remove ' + itemName(row), () => { if (busy || attempt) return; basket.delete(id); cash.value=''; render(); message('Item removed.'); });
      remove.disabled = busy || !!attempt;
      amount.append(element('p','pos-line-price',money(row.price*row.qty)),remove); line.append(info,amount);
      const warning = issue(row);
      if (warning) { needsReview = true; line.append(element('p','pos-line-warning',warning)); }
      lines.append(line);
    }
    for (const selector of ['#pos-total','#pos-subtotal','#pos-charge-total','#pos-mobile-total','#pos-payment-total']) $(selector).textContent = money(total);
    $('#pos-unit-count').textContent = units + (units === 1 ? ' item' : ' items');
    $('#pos-line-count').textContent = basket.size;
    $('#pos-mobile-count').textContent = units;
    $('#pos-mobile-summary').textContent = 'View basket · ' + units + (units === 1 ? ' item' : ' items');
    $('#pos-mobile-basket').hidden = !basket.size;
    $('#pos-basket-empty').hidden = !!basket.size;
    $('#pos-review').hidden = !needsReview;
    $('#pos-clear').disabled = !basket.size || busy || !!attempt;
    customer.disabled = busy || !!attempt;
    $('#pos-pay').disabled = !basket.size || (needsReview && !attempt) || busy || !navigator.onLine;
    $('#pos-payment-summary').textContent = units + (units === 1 ? ' item' : ' items') + ' · ' + (customer.selectedOptions[0]?.textContent || 'Walk-in customer');
    $('#pos-payload').value = JSON.stringify([...basket.values()].map(row => ({id:row.id,qty:row.qty,price:row.price})));
    updateCash(); browse(); save();
  }
  function add(product, scanned = false) {
    if (busy || attempt) return;
    if (product.archived === 'yes' || product.available < 1) { message('This product has no available stock.',true); return; }
    if (!basket.has(product.id) && basket.size >= 40) { message('A sale can contain up to 40 different variants.',true); return; }
    const row = basket.get(product.id) || {...product,qty:0};
    if (row.qty >= product.available) { message('All available units are already in the basket.',true); return; }
    row.qty++; basket.set(product.id,row); cash.value='';
    if (scanned) search.value='';
    render(); message(itemName(product) + ' added · quantity ' + row.qty);
    // Desktop/scanner users can scan again without an extra click; touch stays put.
    if (matchMedia('(pointer:fine)').matches || scanned) search.focus({preventScroll:true});
  }
  function updateCash() {
    const received = Math.round(Number(cash.value) * 100);
    const valid = cash.value !== '' && cash.validity.valid && received >= total;
    $('#pos-change-label').textContent = received >= total ? 'Change to give' : 'Still to collect';
    $('#pos-change').textContent = money(Math.abs(received-total));
    $('.pos-change-row').dataset.short = String(received < total);
    complete.disabled = !basket.size || !valid || busy || !navigator.onLine;
    cash.readOnly = busy || !!attempt;
    $('#pos-payment-close').disabled = busy || !!attempt;
    for (const preset of document.querySelectorAll('#pos-cash-presets button')) {
      preset.disabled = busy || !!attempt;
      preset.setAttribute('aria-pressed',String(Number(preset.dataset.amount) === received));
    }
    complete.querySelector('span').textContent = busy ? 'Recording sale…' : attempt ? 'Retry sale confirmation' : 'Complete cash sale';
  }
  function paymentError(text) {
    $('#pos-payment-error').textContent = text;
    $('#pos-payment-error').hidden = !text;
  }
  function openPayment() {
    if (($('#pos-pay').disabled && !attempt) || busy || payment.open) return;
    $('#pos-cash-presets').replaceChildren();
    // Exact amount plus the next useful naira cash denominations.
    const amounts = new Set([total]);
    for (const denomination of [50000,100000,200000,500000,1000000]) {
      const amount = Math.ceil((total+1)/denomination)*denomination;
      if (amount <= 2000000000) amounts.add(amount);
      if (amounts.size >= 4) break;
    }
    for (const [index,amount] of [...amounts].entries()) {
      const preset = button('', index === 0 ? 'Exact amount' : money(amount), null, () => { cash.value=(amount/100).toFixed(2); updateCash(); save(); cash.focus(); });
      preset.dataset.amount = amount; $('#pos-cash-presets').append(preset);
    }
    if (!cash.value) cash.value=(total/100).toFixed(2);
    paymentError(attempt ? 'A previous sale needs confirmation. Retry the same payment to avoid recording it twice.' : '');
    $('#pos-reload').hidden = true;
    updateCash(); payment.showModal(); cash.focus(); cash.select();
  }
  function view(name) {
    root.dataset.view = name;
    for (const tab of document.querySelectorAll('[data-pos-view]')) tab.setAttribute('aria-pressed',String(tab.dataset.posView === name));
    if (name === 'basket') $('#pos-basket-title').scrollIntoView({block:'nearest'});
  }
  for (const tab of document.querySelectorAll('[data-pos-view]')) tab.addEventListener('click',()=>view(tab.dataset.posView));
  $('#pos-mobile-basket').addEventListener('click',()=>view('basket'));
  for (const tab of document.querySelectorAll('[data-pos-filter]')) tab.addEventListener('click',()=>{
    filter = tab.dataset.posFilter;
    for (const item of document.querySelectorAll('[data-pos-filter]')) item.setAttribute('aria-pressed',String(item === tab));
    browse();
  });
  $('#pos-list-toggle').addEventListener('click',event=>{
    const list = results.classList.toggle('list-view');
    event.currentTarget.setAttribute('aria-pressed',String(list));
    event.currentTarget.setAttribute('aria-label',list ? 'Show products as a grid' : 'Show products as a list');
    event.currentTarget.querySelector('span').textContent = list ? 'Grid view' : 'List view';
  });
  function resetSearch() { search.value=''; browse(); search.focus(); }
  $('#pos-search-clear').addEventListener('click',resetSearch);
  $('#pos-reset-filters').addEventListener('click',()=>{ $('[data-pos-filter="all"]').click(); resetSearch(); });
  search.addEventListener('input',browse);
  search.addEventListener('keydown',event=>{
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const value = search.value.trim();
    if (!value) return;
    const exact = codes.has(value) ? byId.get(codes.get(value)) : products.find(product=>product.sku.toLocaleLowerCase()===value.toLocaleLowerCase());
    if (exact) add(exact,true);
    else message('No exact barcode or SKU match. Select a search result, or check the barcode in Products.',true);
  });
  $('#pos-pay').addEventListener('click',openPayment);
  $('#pos-payment-close').addEventListener('click',()=>{ if (!busy && !attempt) payment.close(); });
  payment.addEventListener('cancel',event=>{ if (busy || attempt) event.preventDefault(); });
  payment.addEventListener('close',()=>{ if (matchMedia('(pointer:fine)').matches) search.focus({preventScroll:true}); });
  cash.addEventListener('input',()=>{ updateCash(); save(); });
  customer.addEventListener('change',()=>{ render(); });
  $('#pos-clear').addEventListener('click',()=>$('#pos-clear-dialog').showModal());
  $('#pos-keep').addEventListener('click',()=>$('#pos-clear-dialog').close());
  $('#pos-discard').addEventListener('click',()=>{
    basket.clear(); customer.value=''; cash.value=''; $('#pos-clear-dialog').close(); render(); message('Basket cleared. Ready for the next sale.'); view('products');
  });
  $('#pos-update-basket').addEventListener('click',()=>{
    if (busy || attempt) return;
    for (const [id,row] of basket) {
      const product = byId.get(id);
      if (!product || product.archived === 'yes' || product.available < 1) basket.delete(id);
      else basket.set(id,{...product,qty:Math.min(row.qty,product.available)});
    }
    cash.value=''; render(); message('Basket updated to current prices and stock. Unavailable items were removed. Review before charging.');
  });
  $('#pos-shortcuts').addEventListener('click',()=>$('#pos-help').showModal());
  $('#pos-help-close').addEventListener('click',()=>$('#pos-help').close());
  document.addEventListener('keydown',event=>{
    if (event.key === 'F2' && !document.querySelector('dialog[open]')) { event.preventDefault(); view('products'); search.focus(); search.select(); }
    if (event.key === 'F4' && !document.querySelector('dialog[open]')) { event.preventDefault(); openPayment(); }
    if (event.key === 'Escape' && document.activeElement === search) resetSearch();
    if (event.key === '?' && !event.target.closest('input,select,textarea') && !document.querySelector('dialog[open]')) $('#pos-help').showModal();
  });
  function connection() {
    $('#pos-connection').textContent = navigator.onLine ? 'Online' : 'Offline';
    $('#pos-connection').classList.toggle('offline',!navigator.onLine);
    if (!navigator.onLine) message('You are offline. Basket kept in this tab. Reconnect before completing a sale.',true);
    render();
  }
  window.addEventListener('online',connection); window.addEventListener('offline',connection);
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if (busy || complete.disabled) return;
    // Keep an ambiguous attempt unchanged until its idempotent replay resolves.
    if (!attempt) attempt = Object.fromEntries(new FormData(form).entries());
    busy = true; paymentError(''); render();
    try {
      const body = new FormData();
      for (const [key,value] of Object.entries(attempt)) body.set(key,value);
      // A refreshed session has a fresh CSRF value; the sale fields stay identical.
      body.set('csrf',form.elements.csrf.value);
      const response = await fetch(form.action,{method:'POST',body});
      const destination = new URL(response.url);
      if (response.ok && destination.pathname === location.pathname && destination.searchParams.has('sold')) {
        try { sessionStorage.removeItem(storageKey); } catch { /* The success URL clears the next load too. */ }
        location.assign(response.url); return;
      }
      if (response.status >= 400 && response.status < 500) {
        const page = new DOMParser().parseFromString(await response.text(),'text/html');
        const detail = page.querySelector('.standalone section>p:not(.eyebrow)')?.textContent || 'Sale could not be completed. Review the basket and try again.';
        attempt = null; paymentError(detail); $('#pos-reload').hidden = false;
      } else {
        paymentError(destination.pathname === '/login' ? 'Your session has expired. Sign in again, then return to this register to confirm the sale. Your basket is kept.' : 'Could not confirm the sale. Retry this same payment after reconnecting. Do not start another sale until it is confirmed.');
        $('#pos-reload').hidden = false;
      }
    } catch {
      paymentError('Could not confirm the sale. Your basket and payment are kept. Reconnect and retry this same payment to avoid recording it twice.');
    } finally {
      busy = false; complete.removeAttribute('aria-busy'); render();
    }
  });
  connection();
  if (attempt && basket.size && navigator.onLine) openPayment();
})();
