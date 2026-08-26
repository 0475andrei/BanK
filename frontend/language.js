/* Lightweight, dependency-free page localisation. Bundles live in i18n/. */
(function () {
    'use strict';
    const STORAGE_KEY = 'bank_preferred_language';
    // Bump this whenever an i18n/*.json bundle's content changes. It drives both
    // the localStorage cache key below and the fetch cache-buster, so it's the
    // single place to touch - previously the two were hardcoded separately and
    // could drift out of sync, leaving browsers stuck on a stale bundle that
    // rendered raw "section.key" strings for any key added after their cache
    // was written.
    const I18N_VERSION = 19;
    const CACHE_PREFIX = `bank_i18n_v${I18N_VERSION}:`;
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

    function mergeObjects(target, source) {
        Object.entries(source || {}).forEach(([key, value]) => {
            if (value && typeof value === 'object' && !Array.isArray(value)) {
                target[key] = mergeObjects(
                    target[key] && typeof target[key] === 'object' ? target[key] : {},
                    value,
                );
            } else {
                target[key] = value;
            }
        });
        return target;
    }

    function mergeBundles(...parts) {
        return parts.reduce((merged, part) => mergeObjects(merged, normalizeBundle(part)), {});
    }

    function preferredLanguage() {
        let saved = null;
        try { saved = localStorage.getItem(STORAGE_KEY); } catch { /* Storage is optional. */ }
        if (Object.prototype.hasOwnProperty.call(LANGUAGES, saved)) return saved;
        const browserLanguages = navigator.languages?.length ? navigator.languages : [navigator.language];
        return browserLanguages.map((value) => value?.split('-')[0].toLowerCase())
            .find((value) => Object.prototype.hasOwnProperty.call(LANGUAGES, value)) || DEFAULT_LANGUAGE;
    }
    async function loadBundle(language) {
        if (bundles.has(language)) return bundles.get(language);
        const cacheKey = `${CACHE_PREFIX}${language}`;
        try {
            const cached = localStorage.getItem(cacheKey);
            if (cached) { const bundle = normalizeBundle(JSON.parse(cached)); bundles.set(language, bundle); return bundle; }
        } catch { /* Replace an invalid cache with the shipped bundle. */ }
        const response = await fetch(`i18n/${language}.json?v=${I18N_VERSION}`, { cache: 'force-cache' });
        if (!response.ok) throw new Error(`Could not load language: ${language}`);
        const bundle = await response.json();
        const normalizedBundle = mergeBundles(bundle);
        bundles.set(language, normalizedBundle);
        try { localStorage.setItem(cacheKey, JSON.stringify(normalizedBundle)); } catch { /* Storage is optional. */ }
        return normalizedBundle;
    }
    function interpolate(value, params = {}) {
        return String(value).replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? `{${name}}`));
    }
    function translate(value, params = {}) {
        if (!value) return value;
        const result = value.split('.').reduce((current, part) => current?.[part], activeBundle);
        if (typeof result === 'string') return interpolate(result, params);
        if (typeof activeBundle.common?.[value] === 'string') return interpolate(activeBundle.common[value], params);
        for (const section of Object.values(activeBundle)) {
            if (section && typeof section === 'object' && typeof section[value] === 'string') return interpolate(section[value], params);
        }
        return value;
    }
    function translateTextNode(node) {
        if (!node.nodeValue.trim()) return;
        const parent = node.parentElement;
        if (!parent || parent.closest('script, style, [data-i18n-ignore]') || (parent.closest('.notranslate') && !parent.closest('.language-selector'))) return;
        const original = sourceText.get(node) || node.nodeValue;
        sourceText.set(node, original);
        const leading = original.match(/^\s*/)[0], trailing = original.match(/\s*$/)[0];
        node.nodeValue = `${leading}${translate(original.trim())}${trailing}`;
    }
    function translateElement(element) {
        if (element.matches?.('[data-i18n-ignore]') || element.closest?.('[data-i18n-ignore]') || (element.matches?.('.notranslate, .notranslate *') && !element.closest?.('.language-selector'))) return;
        if (element.hasAttribute?.('data-i18n')) {
            const key = element.getAttribute('data-i18n');
            let params = {};
            try { params = element.dataset.i18nParams ? JSON.parse(element.dataset.i18nParams) : {}; } catch { /* Ignore malformed optional metadata. */ }
            element.textContent = translate(key, params);
        }
        ['placeholder', 'title', 'aria-label'].forEach((attribute) => {
            const source = `data-i18n-source-${attribute}`;
            const keyAttribute = `data-i18n-${attribute}`;
            if (!element.hasAttribute?.(attribute) && !element.hasAttribute?.(keyAttribute)) return;
            const key = element.getAttribute(keyAttribute);
            const original = element.getAttribute(source) || element.getAttribute(attribute);
            if (original) element.setAttribute(source, original);
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
        document.querySelectorAll('[data-i18n-content]').forEach((element) => {
            element.setAttribute('content', translate(element.dataset.i18nContent));
        });
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
        selector.innerHTML = `<button type="button" class="language-selector-trigger" data-i18n-aria-label="common.Alege limba" aria-haspopup="listbox" aria-expanded="false"><span class="language-selector-icon" aria-hidden="true">◎</span><span class="language-selector-current"></span><span class="language-selector-chevron" aria-hidden="true"></span></button><div class="language-selector-menu" role="listbox" data-i18n-aria-label="common.Alege limba" hidden>${Object.entries(LANGUAGES).map(([code, name]) => `<button type="button" class="language-selector-option" role="option" data-language="${code}">${name}</button>`).join('')}</div>`;
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
        window.addEventListener('languagechange', () => { translateElement(trigger); translateElement(menu); setSelected(preferredLanguage()); });
        document.addEventListener('click', (event) => { if (!selector.contains(event.target)) close(); });
        document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
        const actions = document.querySelector('.top-header .user-actions');
        const logout = actions?.querySelector('.logout-btn');
        if (logout) actions.insertBefore(selector, logout); else document.body.appendChild(selector);
    }
    window.t = (key, fallback = key, params = {}) => translate(key, params) === key
        ? interpolate(fallback, params)
        : translate(key, params);
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
