(() => {
  'use strict';
  const body = document.body;
  if (!body.classList.contains('precision-ui')) return;
  const safeStorage = {
    get(key) { try { return sessionStorage.getItem(key); } catch { return null; } },
    set(key,value) { try { sessionStorage.setItem(key,value); } catch { /* Optional state continuity. */ } }
  };
  const workspacePath = /^\/app\/\d+(?:\/[^?#]*)?(?:\?[^#]*)?(?:#.*)?$/;
  if (workspacePath.test(location.pathname)) safeStorage.set('kora:last-workspace',location.pathname+location.search);
  const directoryPath=location.pathname.match(/^\/app\/(\d+)\/(products|inventory|customers|suppliers|orders)$/);
  if (directoryPath) safeStorage.set('kora:directory:'+directoryPath[1]+':'+directoryPath[2],location.pathname+location.search);
  const merchant=location.pathname.match(/^\/app\/(\d+)/)?.[1];
  for (const link of document.querySelectorAll('[data-return-directory]')) {
    const previous=safeStorage.get('kora:directory:'+merchant+':'+link.dataset.returnDirectory);
    if (previous && previous.startsWith('/app/'+merchant+'/'+link.dataset.returnDirectory) && workspacePath.test(previous)) link.href=previous;
  }
  for (const link of document.querySelectorAll('[data-return-workspace]')) {
    const previous = safeStorage.get('kora:last-workspace');
    if (previous && workspacePath.test(previous)) link.href = previous;
  }

  const sidebarToggle = document.querySelector('.sidebar-toggle');
  if (sidebarToggle) {
    const backdrop = document.createElement('button');
    backdrop.type = 'button'; backdrop.className = 'sidebar-backdrop'; backdrop.setAttribute('aria-label','Close navigation'); backdrop.tabIndex = -1;
    backdrop.addEventListener('click',()=>{ if (!body.classList.contains('sidebar-collapsed')) sidebarToggle.click(); });
    body.append(backdrop);
  }

  // Native forms remain usable without enhancement. Only secondary creation tasks move into drawers.
  const panels = new Map();
  const discard = document.createElement('dialog');
  discard.className = 'precision-discard';
  discard.setAttribute('aria-labelledby','precision-discard-title');
  const discardContent = document.createElement('div'); discardContent.className = 'dialog-content';
  const discardTitle = document.createElement('h2'); discardTitle.id = 'precision-discard-title'; discardTitle.textContent = 'Discard these changes?';
  const discardCopy = document.createElement('p'); discardCopy.textContent = 'Keep this panel open to finish, or discard your edits and return to the list.';
  const actions = document.createElement('div'); actions.className = 'actions';
  const keep = document.createElement('button'); keep.type='button'; keep.className='button secondary'; keep.textContent='Keep editing';
  const abandon = document.createElement('button'); abandon.type='button'; abandon.className='button'; abandon.textContent='Discard edits';
  actions.append(keep,abandon); discardContent.append(discardTitle,discardCopy,actions); discard.append(discardContent); body.append(discard);
  let pendingClose = null;
  const signature = panel => JSON.stringify([...panel.querySelectorAll('form')].map(form=>[...new FormData(form).entries()].map(([key,value])=>[key,value instanceof File ? [value.name,value.size] : value])));
  keep.addEventListener('click',()=>discard.close());
  abandon.addEventListener('click',()=>{
    discard.close();
    if (pendingClose) {
      pendingClose.panel.querySelectorAll('form').forEach(form=>form.reset());
      pendingClose.panel.querySelectorAll('[data-inline-error]').forEach(error=>error.hidden=true);
      pendingClose.initial=signature(pendingClose.panel); pendingClose.dialog.close();
    }
  });
  for (const panel of document.querySelectorAll('[data-focus-panel]')) {
    const dialog = document.createElement('dialog'); dialog.className = 'focus-dialog';
    const heading = document.createElement('div'); heading.className = 'focus-dialog-heading';
    const title = document.createElement('h2'); title.textContent = panel.dataset.focusPanel; title.id = panel.id+'-title';
    const close = document.createElement('button'); close.type='button'; close.className='focus-dialog-close'; close.textContent='×'; close.setAttribute('aria-label','Close '+panel.dataset.focusPanel);
    heading.append(title,close); dialog.append(heading); dialog.setAttribute('aria-labelledby',title.id);
    panel.parentElement.insertBefore(dialog,panel); dialog.append(panel);
    const state = {dialog,panel,initial:signature(panel),trigger:null}; panels.set(panel.id,state);
    const requestClose = event => {
      if (event) event.preventDefault();
      if (signature(panel) !== state.initial) { pendingClose=state; discard.showModal(); keep.focus(); }
      else dialog.close();
    };
    close.addEventListener('click',requestClose); dialog.addEventListener('cancel',requestClose);
    dialog.addEventListener('close',()=>{ if (location.hash === '#'+panel.id) history.replaceState(null,'',location.pathname+location.search); state.trigger?.focus(); });
  }
  function openPanel(id,trigger) {
    const state = panels.get(id);
    if (!state || state.dialog.open) return;
    state.trigger = trigger || null;
    state.dialog.showModal();
    const field = state.panel.querySelector('input:not([type=hidden]),select,button');
    field?.focus();
  }
  document.addEventListener('click',event=>{
    const link = event.target.closest('a[href]');
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const url = new URL(link.href);
    if (url.origin === location.origin && url.pathname === location.pathname && panels.has(url.hash.slice(1))) {
      event.preventDefault(); history.replaceState(null,'',url.pathname+url.search+url.hash); openPanel(url.hash.slice(1),link);
    }
  });
  if (location.hash) openPanel(location.hash.slice(1));
  const importError=document.querySelector('.import-error');
  if (importError && panels.has('catalogue-import')) {
    panels.get('catalogue-import').panel.prepend(importError); openPanel('catalogue-import');
  }
  window.addEventListener('hashchange',()=>openPanel(location.hash.slice(1)));

  // Keep the merchant's working view when returning from a record.
  const viewKey = 'kora:view:'+location.pathname+location.search;
  let remembered = {};
  try { remembered = JSON.parse(safeStorage.get(viewKey) || '{}'); } catch { /* Old state may be ignored. */ }
  for (const list of document.querySelectorAll('[data-product-list]')) {
    const search = list.querySelector('[data-product-search]'), filter = list.querySelector('[data-stock-filter]');
    if (!search || !filter) continue;
    search.value = remembered.query || '';
    const requested = new URLSearchParams(location.search).get('filter') || remembered.filter;
    if ([...filter.options].some(option=>option.value === requested)) filter.value=requested;
    search.dispatchEvent(new Event('input')); filter.dispatchEvent(new Event('change'));
    const saveView = () => safeStorage.set(viewKey,JSON.stringify({query:search.value,filter:filter.value,scroll:scrollY}));
    search.addEventListener('input',saveView); filter.addEventListener('change',saveView); window.addEventListener('pagehide',saveView);
  }
  if (performance.getEntriesByType('navigation')[0]?.type === 'back_forward' && remembered.scroll) requestAnimationFrame(()=>scrollTo(0,remembered.scroll));
  for (const directory of document.querySelectorAll('[data-directory]')) {
    const search = directory.querySelector('[data-directory-search]');
    const rows = [...directory.querySelectorAll('[data-directory-row]')];
    const count = document.createElement('p'); count.className='directory-count'; count.setAttribute('aria-live','polite'); directory.append(count);
    const update = () => { const query=search.value.trim().toLocaleLowerCase(); let visible=0; for (const row of rows) { row.hidden=!row.dataset.match.includes(query); if (!row.hidden) visible++; } count.textContent=visible+' of '+rows.length+' suppliers'; };
    search.addEventListener('input',update); update();
  }

  const stockLayout = document.querySelector('.stock-task-layout');
  const stockNav = document.querySelector('[data-stock-tasks]');
  if (stockNav) {
    const taskDrafts=new Map();
    function activate(link,focus=false) {
      for (const item of stockNav.querySelectorAll('a')) { if (item===link) item.setAttribute('aria-current','page'); else item.removeAttribute('aria-current'); }
      for (const panel of stockLayout.querySelectorAll('[data-stock-panel]')) panel.hidden=panel.id !== link.dataset.stockTarget;
      const method = stockLayout.querySelector('select[name=kind]');
      if (link.dataset.stockKind && method) {
        if (method.value !== link.dataset.stockKind) {
          const form=method.closest('form');
          taskDrafts.set(method.value,{quantity:form.elements.quantity.value,reason:form.elements.reason.value});
          method.value=link.dataset.stockKind;
          const previous=taskDrafts.get(method.value);
          form.elements.quantity.value=previous?.quantity || ''; form.elements.reason.value=previous?.reason || '';
        }
        stockLayout.querySelector('[data-stock-task-title]').textContent=method.value==='recount'?'Physical recount':'Adjust stock';
        const field=method.closest('form').elements.quantity; field.min=method.value==='recount'?0:-1000000;
        method.dispatchEvent(new Event('change',{bubbles:true}));
      }
      stockLayout.querySelectorAll('.stock-method-field').forEach(label=>label.hidden=true);
      if (focus) stockLayout.querySelector('[data-stock-panel]:not([hidden]) input:not([type=hidden])')?.focus({preventScroll:true});
    }
    stockNav.addEventListener('click',event=>{ const link=event.target.closest('[data-stock-target]'); if (!link) return; event.preventDefault(); activate(link,true); });
    activate(stockNav.querySelector('a'));
    for (const form of stockLayout.querySelectorAll('[data-stock-preview]')) {
      const preview=document.createElement('p'); preview.className='stock-preview'; preview.setAttribute('aria-live','polite'); form.querySelector('button').before(preview);
      const update=()=>{
        const amount=Number(form.elements.quantity.value), current=Number(stockLayout.dataset.onHand), reserved=Number(stockLayout.dataset.reserved);
        const kind=form.elements.kind.value;
        const next=kind==='recount'?amount:current+amount;
        const invalid=form.elements.quantity.value!=='' && (!Number.isInteger(amount) || next<reserved);
        form.elements.quantity.setCustomValidity(invalid?'The resulting stock must be a whole number and cover reserved units.':'');
        preview.dataset.invalid=String(invalid);
        preview.textContent=form.elements.quantity.value===''?'Enter a quantity to preview the resulting stock.':invalid?'This change would not cover reserved stock or has a fractional quantity.':`After recording: ${next} on hand · ${reserved} reserved · ${next-reserved} available`;
      };
      form.addEventListener('input',update); form.addEventListener('change',update); update();
    }
  }

  // Keep rejected edits in place and announce a useful error instead of navigating away.
  for (const form of document.querySelectorAll('[data-inline-form]')) {
    let submitting=false;
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      if (submitting) return;
      submitting=true;
      let navigating=false;
      const submitter=event.submitter;
      const error=form.querySelector('[data-inline-error]') || document.createElement('div');
      error.className='inline-error'; error.dataset.inlineError=''; error.setAttribute('role','alert'); error.tabIndex=-1; error.hidden=true;
      if (!error.isConnected) form.prepend(error);
      if (submitter) { submitter.disabled=true; submitter.setAttribute('aria-busy','true'); }
      const initial=new FormData(form);
      if (submitter?.name) initial.set(submitter.name,submitter.value);
      try {
        const response=await fetch(form.action,{method:'POST',body:initial});
        if (response.ok && response.redirected && new URL(response.url).pathname !== '/login') {
          form.dispatchEvent(new Event('precision:saved'));
          for (const state of panels.values()) if (state.panel.contains(form)) state.initial=signature(state.panel);
          navigating=true; location.assign(response.url); return;
        }
        const page=new DOMParser().parseFromString(await response.text(),'text/html');
        error.textContent=new URL(response.url).pathname==='/login'?'Your session has expired. Sign in again in another tab, then return here to save your edits.':page.querySelector('.standalone section>p:not(.eyebrow), [role=alert] p, .order-error span')?.textContent || 'This change could not be saved. Review the details and try again.';
      } catch {
        error.textContent='We could not confirm this change. Your entries are kept here. Check the record after reconnecting before submitting again.';
      } finally {
        submitting=false; if (!navigating) { error.hidden=false; error.focus(); }
        if (submitter) { submitter.disabled=false; submitter.removeAttribute('aria-busy'); }
      }
    });
  }
})();
