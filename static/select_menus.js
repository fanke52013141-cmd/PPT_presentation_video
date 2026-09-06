// Accessible in-page menus for ordinary single-value selects.  Native selects
// stay as the form/state source, so existing API payloads and inline handlers
// keep working while the browser's platform popup is no longer the visible UI.
(function () {
  'use strict';

  const menus = new Set();
  let refreshQueued = false;

  function eligible(select) {
    return select instanceof HTMLSelectElement
      && !select.multiple
      && !select.dataset.selectMenuNative
      && !select.classList.contains('creation-config-native-select')
      && !select.classList.contains('account-select-native')
      && select.getAttribute('aria-hidden') !== 'true';
  }

  function selectedLabel(select) {
    const option = select.selectedOptions?.[0];
    return option?.textContent?.trim() || select.options[0]?.textContent?.trim() || '请选择';
  }

  function closeOthers(current) {
    menus.forEach(menu => {
      if (menu !== current) menu.close();
    });
  }

  function decorate(select) {
    if (!eligible(select)) return null;
    const wrapper = document.createElement('div');
    wrapper.className = 'ppt-select-menu';
    wrapper.dataset.selectMenuFor = select.id || 'anonymous';
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'ppt-select-menu-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    const label = document.createElement('span');
    label.className = 'ppt-select-menu-label';
    const chevron = document.createElement('span');
    chevron.className = 'ppt-select-menu-chevron';
    chevron.setAttribute('aria-hidden', 'true');
    trigger.append(label, chevron);
    const list = document.createElement('div');
    list.className = 'ppt-select-menu-list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;

    select.dataset.selectMenuNative = 'true';
    select.parentNode?.insertBefore(wrapper, select);
    wrapper.append(select, trigger, list);

    const menu = {
      select,
      wrapper,
      trigger,
      list,
      lastSignature: '',
      close() {
        list.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
      },
      sync() {
        const signature = [...select.options].map(option => `${option.value}|${option.textContent}|${option.disabled}|${option.selected}`).join('\u0001');
        if (signature === this.lastSignature && label.textContent === selectedLabel(select)) {
          trigger.disabled = select.disabled;
          return;
        }
        this.lastSignature = signature;
        label.textContent = selectedLabel(select);
        trigger.disabled = select.disabled;
        list.replaceChildren();
        [...select.options].forEach(option => {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'ppt-select-menu-option';
          item.textContent = option.textContent;
          item.disabled = option.disabled;
          item.setAttribute('role', 'option');
          item.setAttribute('aria-selected', String(option.selected));
          if (option.selected) item.classList.add('is-selected');
          item.addEventListener('click', () => {
            if (option.disabled) return;
            select.value = option.value;
            select.dispatchEvent(new Event('input', { bubbles: true }));
            select.dispatchEvent(new Event('change', { bubbles: true }));
            this.lastSignature = '';
            this.sync();
            this.close();
          });
          list.append(item);
        });
      },
    };
    trigger.addEventListener('click', () => {
      menu.sync();
      const open = list.hidden;
      closeOthers(menu);
      list.hidden = !open;
      trigger.setAttribute('aria-expanded', String(open));
      if (open) list.querySelector('.is-selected, .ppt-select-menu-option:not([disabled])')?.focus();
    });
    trigger.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        trigger.click();
      }
    });
    list.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        menu.close();
        trigger.focus();
      }
    });
    select.addEventListener('change', () => { menu.lastSignature = ''; menu.sync(); });
    menus.add(menu);
    menu.sync();
    return menu;
  }

  function refresh() {
    refreshQueued = false;
    document.querySelectorAll('select').forEach(decorate);
    menus.forEach(menu => {
      if (!document.contains(menu.wrapper)) menus.delete(menu);
      else menu.sync();
    });
  }

  function scheduleRefresh() {
    if (refreshQueued) return;
    refreshQueued = true;
    window.requestAnimationFrame(refresh);
  }

  function init() {
    refresh();
    document.addEventListener('click', event => {
      menus.forEach(menu => {
        if (!menu.wrapper.contains(event.target)) menu.close();
      });
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') menus.forEach(menu => menu.close());
    });
    new MutationObserver(scheduleRefresh).observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['disabled', 'selected', 'hidden'],
    });
    // A few legacy modules set select.value without dispatching an event.
    // This tiny reconciliation keeps their visual trigger accurate.
    window.setInterval(scheduleRefresh, 500);
  }

  window.initPptSelectMenus = init;
  document.addEventListener('DOMContentLoaded', init, { once: true });
})();
