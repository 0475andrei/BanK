/* Lightweight, dependency-free page localisation. Bundles live in i18n/. */
(function () {
    'use strict';
    const STORAGE_KEY = 'bank_preferred_language';
    const CACHE_PREFIX = 'bank_i18n_v11:';
    const DEFAULT_LANGUAGE = 'ro';
    const LANGUAGES = { ro: 'Română', en: 'English', uk: 'Українська', hu: 'Magyar', tr: 'Türkçe', it: 'Italiano', es: 'Español', fr: 'Français', de: 'Deutsch' };
    const bundles = new Map();
    const sourceText = new WeakMap();
    let activeBundle = {};

    function setPath(target, path, value) {
        const parts = path.split('.');
        let cursor = target;
        parts.forEach((part, index) => {
            if (index === parts.length - 1) {
                cursor[part] = value;
                return;
            }
            if (!cursor[part] || typeof cursor[part] !== 'object') cursor[part] = {};
            cursor = cursor[part];
        });
    }

    function normalizeBundle(bundle) {
        const normalized = {};
        Object.entries(bundle || {}).forEach(([key, value]) => {
            setPath(normalized, key, value);
        });
        return normalized;
    }

    function mergeBundles(...parts) {
        const merged = {};
        parts.forEach((part) => {
            const normalized = normalizeBundle(part);
            Object.entries(normalized).forEach(([section, values]) => {
                if (values && typeof values === 'object' && !Array.isArray(values)) {
                    merged[section] = { ...(merged[section] || {}), ...values };
                } else {
                    merged[section] = values;
                }
            });
        });
        return merged;
    }

    function preferredLanguage() {
        const saved = localStorage.getItem(STORAGE_KEY);
        return Object.prototype.hasOwnProperty.call(LANGUAGES, saved) ? saved : DEFAULT_LANGUAGE;
    }
    async function loadBundle(language) {
        if (bundles.has(language)) return bundles.get(language);
        const cacheKey = `${CACHE_PREFIX}${language}`;
        try {
            const cached = localStorage.getItem(cacheKey);
            if (cached) { const bundle = normalizeBundle(JSON.parse(cached)); bundles.set(language, bundle); return bundle; }
        } catch { /* Replace an invalid cache with the shipped bundle. */ }
        const response = await fetch(`i18n/${language}.json`, { cache: 'force-cache' });
        if (!response.ok) throw new Error(`Could not load language: ${language}`);
        const bundle = await response.json();
        const normalizedBundle = mergeBundles(bundle);
        bundles.set(language, normalizedBundle);
        try { localStorage.setItem(cacheKey, JSON.stringify(normalizedBundle)); } catch { /* Storage is optional. */ }
        return normalizedBundle;
    }
    function translate(value) {
        if (!value) return value;
        const result = value.split('.').reduce((current, part) => current?.[part], activeBundle);
        if (typeof result === 'string') return result;
        if (typeof activeBundle.common?.[value] === 'string') return activeBundle.common[value];
        for (const section of Object.values(activeBundle)) {
            if (section && typeof section === 'object' && typeof section[value] === 'string') return section[value];
        }
        return value;
    }
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
        if (element.hasAttribute?.('data-i18n')) {
            const key = element.getAttribute('data-i18n');
            element.textContent = translate(key);
        }
        ['placeholder', 'title', 'aria-label'].forEach((attribute) => {
            if (!element.hasAttribute?.(attribute)) return;
            const source = `data-i18n-source-${attribute}`;
            const keyAttribute = `data-i18n-${attribute}`;
            const key = element.getAttribute(keyAttribute);
            const original = element.getAttribute(source) || element.getAttribute(attribute);
            element.setAttribute(source, original);
            element.setAttribute(attribute, key ? translate(key) : translate(original));
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
        window.dispatchEvent(new CustomEvent('languagechange', { detail: { language } }));
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
    window.t = (key, fallback = key, params = {}) => (translate(key) === key ? fallback : translate(key))
        .replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? `{${name}}`));
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
