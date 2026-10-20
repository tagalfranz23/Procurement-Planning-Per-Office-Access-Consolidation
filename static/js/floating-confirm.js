(function () {
  'use strict';

  const requests = [];
  let active = false;
  let nextId = 0;

  function processNext() {
    if (active || !requests.length || !document.body) return;
    active = true;
    const request = requests.shift();
    const options = request.options;
    const previousFocus = document.activeElement;
    const id = `floating-confirm-${++nextId}`;
    let settled = false;

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay open';
    overlay.style.zIndex = '6000';

    const dialog = document.createElement('div');
    dialog.className = 'modal';
    dialog.style.maxWidth = '480px';
    dialog.setAttribute('role', 'alertdialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', `${id}-title`);
    dialog.setAttribute('aria-describedby', `${id}-message`);
    dialog.tabIndex = -1;

    const header = document.createElement('div');
    header.className = 'modal-header';
    const title = document.createElement('div');
    title.id = `${id}-title`;
    title.className = 'modal-title';
    title.textContent = options.title == null ? 'Confirmation' : String(options.title);
    header.appendChild(title);

    const body = document.createElement('div');
    body.className = 'modal-body';
    const message = document.createElement('p');
    message.id = `${id}-message`;
    message.style.margin = '0';
    message.style.whiteSpace = 'pre-wrap';
    message.textContent = request.message;
    body.appendChild(message);

    const footer = document.createElement('div');
    footer.className = 'modal-footer';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn btn-ghost';
    cancel.textContent = options.cancelLabel == null ? 'Cancel' : String(options.cancelLabel);
    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'btn btn-primary';
    confirm.textContent = options.confirmLabel == null ? 'OK' : String(options.confirmLabel);
    footer.append(cancel, confirm);
    dialog.append(header, body, footer);
    overlay.appendChild(dialog);

    function focus(element) {
      try { element.focus({ preventScroll: true }); }
      catch (_) { element.focus(); }
    }

    function settle(value) {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKeyDown, true);
      document.removeEventListener('focusin', onFocusIn, true);
      overlay.remove();
      if (previousFocus && previousFocus.isConnected && typeof previousFocus.focus === 'function') {
        focus(previousFocus);
      }
      active = false;
      request.resolve(value === true);
      queueMicrotask(processNext);
    }

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        settle(false);
      } else if (event.key === 'Tab') {
        event.preventDefault();
        event.stopImmediatePropagation();
        const buttons = [cancel, confirm];
        const position = buttons.indexOf(document.activeElement);
        const next = position < 0 ? 0 : (position + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length;
        focus(buttons[next]);
      }
    }

    function onFocusIn(event) {
      if (!settled && !dialog.contains(event.target)) {
        event.stopImmediatePropagation();
        focus(cancel);
      }
    }

    function choose(event, value) {
      event.preventDefault();
      event.stopPropagation();
      settle(value);
    }

    cancel.addEventListener('click', event => choose(event, false));
    confirm.addEventListener('click', event => choose(event, true));
    overlay.addEventListener('pointerdown', event => {
      event.stopPropagation();
      if (event.target === overlay) event.preventDefault();
    });
    overlay.addEventListener('click', event => {
      event.stopPropagation();
      if (event.target === overlay) choose(event, false);
    });
    document.addEventListener('keydown', onKeyDown, true);
    document.addEventListener('focusin', onFocusIn, true);
    document.body.appendChild(overlay);
    focus(cancel);
  }

  window.showFloatingConfirm = function (message, options = {}) {
    return new Promise(resolve => {
      requests.push({
        message: message == null ? '' : String(message),
        options: options && typeof options === 'object' ? options : {},
        resolve,
      });
      if (document.body) processNext();
      else document.addEventListener('DOMContentLoaded', processNext, { once: true });
    });
  };
})();
