/* Lightweight, dependency-free page localisation. Bundles live in i18n/. */
(function () {
    'use strict';
    const STORAGE_KEY = 'bank_preferred_language';
    const CACHE_PREFIX = 'bank_i18n_v2:';
    const DEFAULT_LANGUAGE = 'ro';
    const LANGUAGES = { ro: 'Română', en: 'English', uk: 'Українська', hu: 'Magyar', tr: 'Türkçe', it: 'Italiano', es: 'Español', fr: 'Français', de: 'Deutsch' };
    const bundles = new Map();
    const sourceText = new WeakMap();
    let activeBundle = {};

    function preferredLanguage() {
        const saved = localStorage.getItem(STORAGE_KEY);
        return Object.prototype.hasOwnProperty.call(LANGUAGES, saved) ? saved : DEFAULT_LANGUAGE;
    }
    async function loadBundle(language) {
        if (bundles.has(language)) return bundles.get(language);
        const cacheKey = `${CACHE_PREFIX}${language}`;
        try {
            const cached = localStorage.getItem(cacheKey);
            if (cached) { const bundle = JSON.parse(cached); bundles.set(language, bundle); return bundle; }
        } catch { /* Replace an invalid cache with the shipped bundle. */ }
        const response = await fetch(`i18n/${language}.json`, { cache: 'force-cache' });
        if (!response.ok) throw new Error(`Could not load language: ${language}`);
        const bundle = await response.json();
        // Feature bundles keep larger sections (such as Payments) maintainable
        // without delaying the shared authentication/dashboard bundle.
        const featureResponse = await fetch(`i18n/${language}.payments.json`, { cache: 'force-cache' });
        if (featureResponse.ok) Object.assign(bundle, await featureResponse.json());
        bundles.set(language, bundle);
        try { localStorage.setItem(cacheKey, JSON.stringify(bundle)); } catch { /* Storage is optional. */ }
        return bundle;
    }
    function translate(value) { return activeBundle[value] || value; }
    function translateTextNode(node) {
        if (!node.nodeValue.trim()) return;
        const parent = node.parentElement;
        if (!parent || parent.closest('script, style, .notranslate, [data-i18n-ignore]')) return;
        const original = sourceText.get(node) || node.nodeValue;
        sourceText.set(node, original);
        const leading = original.match(/^\s*/)[0], trailing = original.match(/\s*$/)[0];
        node.nodeValue = `${leading}${translate(original.trim())}${trailing}`;
    }
    function translateElement(element) {
        if (element.matches?.('.notranslate, [data-i18n-ignore]') || element.closest?.('.notranslate, [data-i18n-ignore]')) return;
        ['placeholder', 'title', 'aria-label'].forEach((attribute) => {
            if (!element.hasAttribute?.(attribute)) return;
            const source = `data-i18n-source-${attribute}`;
            const original = element.getAttribute(source) || element.getAttribute(attribute);
            element.setAttribute(source, original);
            element.setAttribute(attribute, translate(original));
        });
        element.childNodes.forEach((node) => { if (node.nodeType === Node.TEXT_NODE) translateTextNode(node); });
    }
    function translatePage(root = document.body) {
        if (!root) return;
        if (root.nodeType === Node.ELEMENT_NODE) translateElement(root);
        root.querySelectorAll?.('*').forEach(translateElement);
        const titleSource = document.documentElement.dataset.i18nTitle || document.title;
        document.documentElement.dataset.i18nTitle = titleSource;
        document.title = translate(titleSource);
    }
    async function activateLanguage(language) {
        activeBundle = await loadBundle(language);
        document.documentElement.lang = language;
        translatePage();
        document.documentElement.classList.remove('i18n-pending');
    }
    function addSelector() {
        const selector = document.createElement('div');
        selector.className = 'language-selector notranslate';
        selector.setAttribute('translate', 'no');
        selector.innerHTML = `<button type="button" class="language-selector-trigger" aria-label="Choose language" aria-haspopup="listbox" aria-expanded="false"><span class="language-selector-icon" aria-hidden="true">◎</span><span class="language-selector-current"></span><span class="language-selector-chevron" aria-hidden="true"></span></button><div class="language-selector-menu" role="listbox" aria-label="Choose language" hidden>${Object.entries(LANGUAGES).map(([code, name]) => `<button type="button" class="language-selector-option" role="option" data-language="${code}">${name}</button>`).join('')}</div>`;
        const trigger = selector.querySelector('.language-selector-trigger');
        const menu = selector.querySelector('.language-selector-menu');
        const current = selector.querySelector('.language-selector-current');
        const setSelected = (language) => { current.textContent = LANGUAGES[language]; selector.querySelectorAll('.language-selector-option').forEach((option) => option.setAttribute('aria-selected', String(option.dataset.language === language))); };
        const close = () => { menu.hidden = true; trigger.setAttribute('aria-expanded', 'false'); };
        setSelected(preferredLanguage());
        trigger.addEventListener('click', () => { menu.hidden = !menu.hidden; trigger.setAttribute('aria-expanded', String(!menu.hidden)); });
        selector.querySelectorAll('.language-selector-option').forEach((option) => option.addEventListener('click', async () => {
            const language = option.dataset.language;
            setSelected(language); close(); localStorage.setItem(STORAGE_KEY, language);
            await activateLanguage(language);
        }));
        document.addEventListener('click', (event) => { if (!selector.contains(event.target)) close(); });
        document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
        const actions = document.querySelector('.top-header .user-actions');
        const logout = actions?.querySelector('.logout-btn');
        if (logout) actions.insertBefore(selector, logout); else document.body.appendChild(selector);
    }
    window.t = (key, fallback = key) => translate(key) || fallback;
    window.refreshTranslations = () => translatePage();
    document.addEventListener('DOMContentLoaded', async () => {
        addSelector();
        new MutationObserver((mutations) => mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
            if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
            else if (node.nodeType === Node.ELEMENT_NODE) translatePage(node);
        }))).observe(document.body, { childList: true, subtree: true });
        const language = preferredLanguage();
        try { await activateLanguage(language); } catch { document.documentElement.classList.remove('i18n-pending'); }
        Object.keys(LANGUAGES).filter((code) => code !== language).forEach((code) => loadBundle(code).catch(() => {}));
    });
})();
