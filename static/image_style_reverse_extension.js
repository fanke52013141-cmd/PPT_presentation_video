(function () {
  'use strict';

  function removeLegacyHeaderButton() {
    const legacy = document.getElementById('btn-image-style-reverse');
    if (legacy) legacy.remove();
  }

  function boot() {
    removeLegacyHeaderButton();
    const timer = setInterval(removeLegacyHeaderButton, 700);
    setTimeout(() => clearInterval(timer), 15000);
  }

  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
