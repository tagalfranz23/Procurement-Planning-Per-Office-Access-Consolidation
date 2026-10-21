(() => {
  'use strict';

  const boundInputs = new WeakSet();

  function format(value) {
    return String(value ?? '').replace(/\S+/gu, word => {
      const [first, ...remaining] = Array.from(word);
      const [initial, ...expanded] = Array.from(first.toUpperCase());
      return initial + (expanded.join('') + remaining.join('')).toLowerCase();
    });
  }

  function normalizeInput(input, trim = false) {
    const previous = input.value;
    const formatted = format(previous);
    const next = trim ? formatted.trim() : formatted;
    if (next === previous) return next;

    const start = input.selectionStart, end = input.selectionEnd, direction = input.selectionDirection;
    const removedLeading = trim ? formatted.length - formatted.trimStart().length : 0;
    const position = offset => Math.max(0, Math.min(next.length, format(previous.slice(0, offset)).length - removedLeading));
    input.value = next;
    if (start !== null && end !== null) input.setSelectionRange(position(start), position(end), direction || 'none');
    return next;
  }

  function bindInput(input) {
    if (boundInputs.has(input)) return;
    boundInputs.add(input);
    let composing = false;
    input.addEventListener('compositionstart', () => { composing = true; });
    input.addEventListener('compositionend', () => {
      composing = false;
      normalizeInput(input);
    });
    const normalize = event => {
      if (!composing && !event.isComposing) normalizeInput(input);
    };
    ['input', 'change', 'focus', 'blur'].forEach(event => input.addEventListener(event, normalize));
    input.form?.addEventListener('submit', () => normalizeInput(input, true), true);
  }

  function bindAll() {
    document.querySelectorAll('input[data-username-format]').forEach(input => {
      bindInput(input);
      normalizeInput(input);
    });
  }

  window.UsernameFormat = Object.freeze({ format, normalizeInput });
  bindAll();
  document.addEventListener('DOMContentLoaded', bindAll);
  window.addEventListener('pageshow', bindAll);
})();
