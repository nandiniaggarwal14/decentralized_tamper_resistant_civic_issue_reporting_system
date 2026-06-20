// Lightweight client-side localization system
(function () {
  let translations = {};
  let currentLang = localStorage.getItem('lang') || 'en';

  // Load translation file from server
  async function loadTranslations(lang) {
    try {
      const response = await fetch(`/assets/lang/${lang}.json`);
      if (!response.ok) throw new Error(`Could not load ${lang}.json`);
      translations = await response.json();
      currentLang = lang;
      localStorage.setItem('lang', lang);
    } catch (error) {
      console.error('Localization loading error:', error);
      // Fallback to empty if it fails
      translations = {};
    }
  }

  // Translate all DOM elements with data-i18n
  function translatePage() {
    const elements = document.querySelectorAll('[data-i18n]');
    elements.forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (translations[key]) {
        // If it's an input or textarea with placeholder
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
          if (el.hasAttribute('placeholder')) {
            el.setAttribute('placeholder', translations[translations[key] ? key : el.getAttribute('placeholder')]);
          } else {
            el.value = translations[key];
          }
        } else {
          el.innerHTML = translations[key];
        }
      }
    });

    // Handle attributes like placeholders separately if needed
    const placeholderElements = document.querySelectorAll('[data-i18n-placeholder]');
    placeholderElements.forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      if (translations[key]) {
        el.setAttribute('placeholder', translations[key]);
      }
    });
  }

  // Translate single key manually
  function t(key, defaultValue = '') {
    return translations[key] || defaultValue || key;
  }

  // Setup Lang dropdown if present
  function initLangDropdown() {
    const select = document.getElementById('lang-select');
    if (select) {
      select.value = currentLang;
      select.addEventListener('change', async (e) => {
        await changeLanguage(e.target.value);
      });
    }
  }

  // Change active language
  async function changeLanguage(lang) {
    await loadTranslations(lang);
    translatePage();
    // Dispatch event so page-specific JS files can react
    window.dispatchEvent(new CustomEvent('languageChanged', { detail: { lang } }));
  }

  // Initialize on page load
  async function init() {
    await loadTranslations(currentLang);
    translatePage();
    initLangDropdown();
  }

  // Export globally
  window.i18n = {
    init,
    changeLanguage,
    t,
    translatePage,
    getCurrentLanguage: () => currentLang
  };

  // Run automatically when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
