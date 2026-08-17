(() => {
    const root = document.querySelector('[data-deck-builder-root]');
    if (!root) return;

    const $ = (selector) => root.querySelector(selector);
    const $$ = (selector) => [...root.querySelectorAll(selector)];
    const esc = (value) => String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');

    const money = (value) => {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return 'Prix inconnu';
        return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(Number(value));
    };
    const frDate = (value) => {
        if (!value) return '—';
        const parts = String(value).split('-').map(Number);
        if (parts.length !== 3 || parts.some(Number.isNaN)) return String(value);
        return new Intl.DateTimeFormat('fr-FR').format(new Date(parts[0], parts[1] - 1, parts[2]));
    };

    const ownedKey = 'hamtaro-deck-builder-owned-v8';
    const previousOwnedKey = 'hamtaro-deck-builder-owned-v7';
    const constraintsKey = 'hamtaro-deck-builder-constraints-v8';
    const emptyZones = () => ({ main: {}, extra: {}, side: {} });
    const emptyExcluded = () => ({ main: [], extra: [], side: [] });
    const state = {
        analysis: null,
        generated: null,
        query: '',
        variant: '',
        zone: 'main',
        mode: 'standard',
        freespotProfile: 'auto',
        shown: 24,
        owned: {},
        locked: emptyZones(),
        excluded: emptyExcluded(),
        requestSerial: 0,
    };

    try {
        const current = localStorage.getItem(ownedKey);
        const legacy = localStorage.getItem(previousOwnedKey);
        state.owned = JSON.parse(current || legacy || '{}') || {};
        if (!current && legacy) localStorage.setItem(ownedKey, JSON.stringify(state.owned));
    } catch (_) {
        state.owned = {};
    }
    try {
        const legacyConstraints = localStorage.getItem('hamtaro-deck-builder-constraints-v7') || localStorage.getItem('hamtaro-deck-builder-constraints-v6') || localStorage.getItem('hamtaro-deck-builder-constraints-v5');
        const currentConstraints = localStorage.getItem(constraintsKey);
        const stored = JSON.parse(currentConstraints || legacyConstraints || '{}') || {};
        state.locked = { ...emptyZones(), ...(stored.locked || {}) };
        state.excluded = { ...emptyExcluded(), ...(stored.excluded || {}) };
        if (!currentConstraints && legacyConstraints) localStorage.setItem(constraintsKey, JSON.stringify(stored));
    } catch (_) {
        state.locked = emptyZones();
        state.excluded = emptyExcluded();
    }
    const saveOwned = () => localStorage.setItem(ownedKey, JSON.stringify(state.owned));
    const saveConstraints = () => localStorage.setItem(constraintsKey, JSON.stringify({ locked: state.locked, excluded: state.excluded }));

    const els = {
        form: $('[data-db-search-form]'),
        query: $('[data-db-query]'),
        suggestions: $('[data-db-suggestions]'),
        empty: $('[data-db-empty-state]'),
        loading: $('[data-db-loading]'),
        error: $('[data-db-error]'),
        results: $('[data-db-results]'),
        budgetWrap: $('[data-db-budget-wrap]'),
        budget: $('[data-db-budget]'),
        freespotProfile: $('[data-db-freespot-profile]'),
        days: $('[data-db-days]'),
        limit: $('[data-db-limit]'),
        tournamentOnly: $('[data-db-tournament-only]'),
        title: $('[data-db-title]'),
        subtitle: $('[data-db-subtitle]'),
        samples: $('[data-db-samples]'),
        tournaments: $('[data-db-tournaments]'),
        confidence: $('[data-db-confidence]'),
        confidenceLabel: $('[data-db-confidence-label]'),
        basePrice: $('[data-db-base-price]'),
        corePrice: $('[data-db-core-price]'),
        priceDate: $('[data-db-price-date]'),
        engineCount: $('[data-db-engine-count]'),
        newestSource: $('[data-db-newest-source]'),
        sourceWindow: $('[data-db-source-window]'),
        banlistStatus: $('[data-db-banlist-status]'),
        banlistDate: $('[data-db-banlist-date]'),
        warnings: $('[data-db-warnings]'),
        variantsPanel: $('[data-db-variants-panel]'),
        variants: $('[data-db-variants]'),
        clearVariant: $('[data-db-clear-variant]'),
        enginePanel: $('[data-db-engine-panel]'),
        engines: $('[data-db-engines]'),
        packagePanel: $('[data-db-package-panel]'),
        packages: $('[data-db-packages]'),
        engineComparePanel: $('[data-db-engine-compare-panel]'),
        engineComparisons: $('[data-db-engine-comparisons]'),
        configurationsPanel: $('[data-db-configurations-panel]'),
        configurations: $('[data-db-configurations]'),
        flexPanel: $('[data-db-flex-panel]'),
        flexGrid: $('[data-db-flex-grid]'),
        freespotPanel: $('[data-db-freespot-panel]'),
        freespotStats: $('[data-db-freespot-stats]'),
        freespotCategories: $('[data-db-freespot-categories]'),
        profilePanel: $('[data-db-profile-panel]'),
        profileGrid: $('[data-db-profile-grid]'),
        compositionPanel: $('[data-db-composition-panel]'),
        compositionGrid: $('[data-db-composition-grid]'),
        importance: $('[data-db-importance-filter]'),
        ownedFilter: $('[data-db-owned-filter]'),
        cardList: $('[data-db-card-list]'),
        loadMore: $('[data-db-load-more]'),
        constraintsPanel: $('[data-db-constraints-panel]'),
        constraintsSummary: $('[data-db-constraints-summary]'),
        resetConstraints: $('[data-db-reset-constraints]'),
        alternativesPanel: $('[data-db-alternatives-panel]'),
        alternativesTitle: $('[data-db-alternatives-title]'),
        alternativesNote: $('[data-db-alternatives-note]'),
        alternativesGrid: $('[data-db-alternatives-grid]'),
        closeAlternatives: $('[data-db-close-alternatives]'),
        synergyPanel: $('[data-db-synergy-panel]'),
        synergyTitle: $('[data-db-synergy-title]'),
        synergyNote: $('[data-db-synergy-note]'),
        synergyGrid: $('[data-db-synergy-grid]'),
        closeSynergy: $('[data-db-close-synergy]'),
        mainTotal: $('[data-db-main-total]'),
        extraTotal: $('[data-db-extra-total]'),
        sideTotal: $('[data-db-side-total]'),
        ownedSummary: $('[data-db-owned-summary]'),
        ownedCount: $('[data-db-owned-count]'),
        remainingCost: $('[data-db-remaining-cost]'),
        generatedPanel: $('[data-db-generated-panel]'),
        generatedTitle: $('[data-db-generated-title]'),
        generatedNote: $('[data-db-generated-note]'),
        generatedMainCount: $('[data-db-generated-main-count]'),
        generatedExtraCount: $('[data-db-generated-extra-count]'),
        generatedSideCount: $('[data-db-generated-side-count]'),
        generatedPrice: $('[data-db-generated-price]'),
        generatedPurchase: $('[data-db-generated-purchase]'),
        generatedSavings: $('[data-db-generated-savings]'),
        generationWarnings: $('[data-db-generation-warnings]'),
        budgetChanges: $('[data-db-budget-changes]'),
        generatedZones: $('[data-db-generated-zones]'),
        sourceCount: $('[data-db-source-count]'),
        sources: $('[data-db-sources]'),
        degraded: $('[data-db-degraded]'),
        fallbackGrid: $('[data-db-fallback-grid]'),
        compareInput: $('[data-db-compare-input]'),
        compareFile: $('[data-db-compare-file]'),
        compareButton: $('[data-db-compare-button]'),
        compareResults: $('[data-db-compare-results]'),
        legalityCard: $('[data-db-legality-card]'),
        upgradePanel: $('[data-db-upgrade-panel]'),
        readinessPanel: $('[data-db-readiness-panel]'),
        openingPanel: $('[data-db-opening-panel]'),
        diagnosticsPanel: $('[data-db-diagnostics-panel]'),
        purchasePlan: $('[data-db-purchase-plan]'),
    };

    const setBusy = (busy) => {
        els.loading.hidden = !busy;
        els.empty.hidden = true;
        if (busy) {
            els.error.hidden = true;
            els.results.hidden = true;
        }
    };

    const showError = (message, preserveResults = false) => {
        els.loading.hidden = true;
        if (!preserveResults) els.results.hidden = true;
        els.error.textContent = message || 'Une erreur est survenue.';
        els.error.hidden = false;
    };

    const buildParams = (includeGeneration = false) => {
        const params = new URLSearchParams();
        params.set('q', state.query || els.query.value.trim());
        if (els.limit.value) params.set('limit', els.limit.value);
        if (els.days.value) params.set('days', els.days.value);
        if (els.tournamentOnly.checked) params.set('tournament_only', '1');
        if (state.variant) params.set('variant', state.variant);
        if (includeGeneration) {
            params.set('mode', state.mode);
            params.set('freespot_profile', state.freespotProfile || 'auto');
            const budget = els.budget.value.trim();
            if (state.mode === 'budget' && budget) params.set('budget', budget);
        }
        return params;
    };

    const fetchJson = async (url, options = {}) => {
        const response = await fetch(url, {
            ...options,
            headers: {
                Accept: 'application/json',
                ...(options.body ? { 'Content-Type': 'application/json' } : {}),
                ...(options.headers || {}),
            },
        });
        let payload = {};
        try { payload = await response.json(); } catch (_) {}
        if (!response.ok) throw new Error(payload.error || `Erreur HTTP ${response.status}`);
        return payload;
    };

    const renderWarnings = (warnings, target = els.warnings) => {
        const values = (warnings || []).filter(Boolean);
        target.hidden = values.length === 0;
        target.innerHTML = values.map((value) => `<div>${esc(value)}</div>`).join('');
    };

    const priceSummary = (obj) => {
        if (!obj) return '—';
        const total = money(obj.known_total);
        return obj.unknown_price_lines ? `${total} + ${obj.unknown_price_lines} inconnu(s)` : total;
    };

    const renderVariants = () => {
        const variants = state.analysis?.variants || [];
        els.variantsPanel.hidden = variants.length <= 1;
        els.clearVariant.hidden = !state.variant;
        els.variants.innerHTML = variants.slice(0, 12).map((variant) => {
            const active = state.variant && variant.name === state.variant;
            const suffix = variant.aggregate ? `${variant.count} listes` : `${variant.count} liste${variant.count > 1 ? 's' : ''}`;
            return `<button type="button" class="${active ? 'is-active' : ''}" data-db-variant="${esc(variant.name)}">${esc(variant.name)} · ${esc(suffix)}</button>`;
        }).join('');
    };

    const renderEngines = () => {
        const engines = state.analysis?.engines || [];
        els.engineCount.textContent = String(engines.length);
        els.enginePanel.hidden = engines.length === 0;
        els.engines.innerHTML = engines.map((engine) => {
            const cards = (engine.cards || []).slice(0, 8).map((card) => (
                `<li><span>${esc(card.zone.toUpperCase())}</span><strong>${esc(card.name)}</strong><small>${esc(card.frequency_pct)} % · ×${esc(card.recommended_copies)}</small></li>`
            )).join('');
            return `
                <article class="db-engine-card">
                    <div class="db-engine-head">
                        <div><span>Moteur détecté</span><strong>${esc(engine.name)}</strong></div>
                        <b>${esc(engine.average_frequency_pct)} % moy.</b>
                    </div>
                    <small>${esc(engine.main_cards)} Main · ${esc(engine.extra_cards)} Extra · ${esc(engine.side_cards)} Side</small>
                    <ul>${cards}</ul>
                </article>`;
        }).join('');
    };

    const renderPackages = () => {
        const packages = state.analysis?.packages || [];
        els.packagePanel.hidden = packages.length === 0;
        els.packages.innerHTML = packages.map((pack, index) => `
            <article class="db-package-card" data-package-index="${index}">
                <div class="db-package-head"><strong>${esc(pack.name)}</strong><span>${esc(pack.cohesion_pct)} % cohésion · lift ×${esc(pack.lift)}</span></div>
                <div class="db-package-cards">${(pack.cards || []).map((card) => `<span><b>${esc(card.zone.toUpperCase())}</b>${esc(card.name)} <small>×${esc(card.recommended_copies)}</small></span>`).join('')}</div>
                <div class="db-package-foot"><small>${esc(pack.note || '')}</small><button type="button" data-db-apply-package="${index}">Verrouiller ce package</button></div>
            </article>`).join('');
    };

    const renderEngineComparisons = () => {
        const comparisons = state.analysis?.engine_comparisons || [];
        els.engineComparePanel.hidden = comparisons.length === 0;
        els.engineComparisons.innerHTML = comparisons.map((item) => `
            <article class="db-engine-compare-card">
                <div class="db-package-head"><strong>Avec / sans ${esc(item.engine)}</strong><span>${esc(item.with_count)} avec · ${esc(item.without_count)} sans</span></div>
                <div class="db-compare-columns">
                    <div><b>Plus fréquent avec</b>${(item.with_signature || []).length ? `<ul>${item.with_signature.map((card) => `<li><span>${esc(card.zone.toUpperCase())}</span><strong>${esc(card.name)}</strong><small>${esc(card.with_pct)} % vs ${esc(card.without_pct)} %</small></li>`).join('')}</ul>` : '<small>Pas de signature nette.</small>'}</div>
                    <div><b>Plus fréquent sans</b>${(item.without_signature || []).length ? `<ul>${item.without_signature.map((card) => `<li><span>${esc(card.zone.toUpperCase())}</span><strong>${esc(card.name)}</strong><small>${esc(card.without_pct)} % vs ${esc(card.with_pct)} %</small></li>`).join('')}</ul>` : '<small>Pas de signature nette.</small>'}</div>
                </div>
            </article>`).join('');
    };

    const renderConfigurations = () => {
        const configurations = state.analysis?.configurations || [];
        els.configurationsPanel.hidden = configurations.length === 0;
        els.configurations.innerHTML = configurations.map((item, index) => `
            <article class="db-configuration-card" data-config-index="${index}">
                <div class="db-package-head"><strong>${esc(item.name)}</strong><span>${esc(item.share_pct)} % de l'échantillon · ${esc(item.sample_count)} listes</span></div>
                <div class="db-configuration-signature">${(item.signature_cards || []).slice(0, 6).map((card) => `<span><b>${esc(card.zone.toUpperCase())}</b>${esc(card.name)}<small>${esc(card.inside_pct)} % · Δ ${Number(card.delta_pct) >= 0 ? '+' : ''}${esc(card.delta_pct)} pts</small></span>`).join('')}</div>
                <div class="db-package-foot"><small>${esc(item.tournament_count)} liste(s) de tournoi dans ce groupe.</small>${(item.lock_cards || []).length ? `<button type="button" data-db-apply-configuration="${index}">Appliquer les pièces stables</button>` : ''}</div>
            </article>`).join('');
    };

    const renderFlexChoices = () => {
        const choices = state.analysis?.flex_choices || [];
        els.flexPanel.hidden = choices.length === 0;
        els.flexGrid.innerHTML = choices.map((choice, index) => `
            <article class="db-flex-card" data-flex-index="${index}">
                <div class="db-package-head"><strong>${esc(choice.zone.toUpperCase())} · ${esc(choice.role)}</strong><span>${esc(choice.exclusivity_pct)} % d'exclusivité · ${esc(choice.coverage_pct)} % de couverture</span></div>
                <div class="db-flex-options">${(choice.options || []).map((option, optionIndex) => `
                    <div>
                        ${option.image_url ? `<img src="${esc(option.image_url)}" loading="lazy" alt="${esc(option.name)}">` : ''}
                        <span><strong>${esc(option.name)}</strong><small>${esc(option.frequency_pct)} % · ×${esc(option.recommended_copies)} · ${option.cardmarket_price === null ? 'prix inconnu' : money(option.cardmarket_price)}</small></span>
                        <button type="button" data-db-choose-flex="${index}:${optionIndex}">Choisir</button>
                    </div>`).join('')}</div>
                <small>${esc(choice.note || '')}</small>
            </article>`).join('');
    };

    const renderProfile = () => {
        const profile = state.analysis?.deck_profile || {};
        const labels = { main: 'Main Deck', extra: 'Extra Deck', side: 'Side Deck' };
        const zones = ['main', 'extra', 'side'].filter((zone) => profile[zone]);
        els.profilePanel.hidden = zones.length === 0;
        els.profileGrid.innerHTML = zones.map((zone) => {
            const item = profile[zone];
            return `
                <article class="db-profile-card">
                    <strong>${labels[zone]}</strong>
                    <div><span>Core estimé</span><b>${esc(item.core_slots)} slots</b></div>
                    <div><span>Fréquentes</span><b>${esc(item.frequent_slots)} slots</b></div>
                    <div><span>Flex estimé</span><b>${esc(item.flex_slots_estimate)} slots</b></div>
                    <small>${esc(item.observed_unique_cards)} cartes différentes observées</small>
                </article>`;
        }).join('');
    };

    const renderComposition = () => {
        const composition = state.analysis?.composition || {};
        const labels = { main: 'Main Deck', extra: 'Extra Deck', side: 'Side Deck' };
        const zones = ['main', 'extra', 'side'].filter((zone) => (composition[zone] || []).length);
        els.compositionPanel.hidden = zones.length === 0;
        els.compositionGrid.innerHTML = zones.map((zone) => {
            const rows = (composition[zone] || []).slice(0, 8);
            return `
                <article class="db-composition-card">
                    <strong>${labels[zone]}</strong>
                    <div>${rows.map((row) => `<span><b>${esc(row.role)}</b><small>${esc(row.slots)} pts · ${esc(row.share_pct)} %</small></span>`).join('')}</div>
                </article>`;
        }).join('');
    };

    const importanceAllowed = (row) => {
        const filter = els.importance.value;
        const rank = { core: 0, frequent: 1, option: 2, rare: 3 };
        if (filter === 'all') return true;
        const max = filter === 'core' ? 0 : filter === 'frequent' ? 1 : 2;
        return (rank[row.importance] ?? 3) <= max;
    };

    const ownedQty = (id) => Math.max(0, Number(state.owned[String(id)] || 0));
    const lockedQty = (zone, id) => Math.max(0, Number((state.locked?.[zone] || {})[String(id)] || 0));
    const isExcluded = (zone, id) => (state.excluded?.[zone] || []).map(String).includes(String(id));
    const clearGenerated = () => {
        state.generated = null;
        els.generatedPanel.hidden = true;
    };

    const renderConstraints = () => {
        const items = [];
        ['main', 'extra', 'side'].forEach((zone) => {
            Object.entries(state.locked?.[zone] || {}).forEach(([id, qty]) => {
                const row = (state.analysis?.zones?.[zone] || []).find((card) => String(card.id) === String(id));
                items.push({ zone, id, type: 'locked', qty, name: row?.name || `Carte ${id}` });
            });
            (state.excluded?.[zone] || []).forEach((id) => {
                const row = (state.analysis?.zones?.[zone] || []).find((card) => String(card.id) === String(id));
                items.push({ zone, id, type: 'excluded', qty: 0, name: row?.name || `Carte ${id}` });
            });
        });
        els.constraintsPanel.hidden = items.length === 0;
        els.constraintsSummary.innerHTML = items.map((item) => `
            <span class="db-constraint-chip ${item.type}">
                <b>${item.type === 'locked' ? 'Garder' : 'Écarter'}</b>
                ${esc(item.zone.toUpperCase())} · ${esc(item.name)}${item.type === 'locked' ? ` ×${esc(item.qty)}` : ''}
            </span>`).join('');
    };

    const trendMarkup = (row) => {
        const value = row.price_change_7d_pct;
        if (value === null || value === undefined) return '';
        const cls = value > 0 ? 'positive' : value < 0 ? 'negative' : '';
        const sign = value > 0 ? '+' : '';
        return `<small class="db-price-trend ${cls}">${sign}${esc(value)} % sur 7 j</small>`;
    };

    const cardRow = (row) => {
        const owned = ownedQty(row.id);
        const recommended = Number(row.recommended_copies || 0);
        const distribution = Object.entries(row.copy_distribution_pct || {})
            .map(([qty, pct]) => `×${qty}: ${pct}%`).join(' · ');
        const price = row.cardmarket_price === null ? 'Inconnu' : money(row.cardmarket_price);
        const img = row.image_url
            ? `<img class="db-card-image" src="${esc(row.image_url)}" loading="lazy" alt="${esc(row.name)}">`
            : `<span class="db-card-image" aria-hidden="true"></span>`;
        const locked = lockedQty(state.zone, row.id) > 0;
        const excluded = isExcluded(state.zone, row.id);
        return `
            <article class="db-card-row ${locked ? 'is-locked' : ''} ${excluded ? 'is-excluded' : ''}" data-card-id="${esc(row.id)}">
                ${img}
                <div class="db-card-main">
                    <strong title="${esc(row.name)}">${esc(row.name)}</strong>
                    ${row.source_name && row.source_name !== row.name ? `<small class="db-source-name">EN : ${esc(row.source_name)}</small>` : ''}
                    <div class="db-card-meta">
                        <span class="db-pill ${esc(row.importance)}">${esc(row.importance_label)}</span>
                        <span class="db-pill">${esc(row.relation)}</span>
                        ${row.freespot_category_label ? `<span class="db-pill db-freespot-pill">${esc(row.freespot_category_label)}</span>` : ''}
                        ${row.ban_tcg ? `<span class="db-pill">${esc(row.ban_tcg)}</span>` : ''}
                    </div>
                    <small class="db-card-why">${esc(row.why_played || '')}</small>
                    <div class="db-card-links">
                        <a href="${esc(row.cardmarket_url)}" target="_blank" rel="noopener noreferrer">Cardmarket</a>
                        <a href="${esc(row.neuron_url)}" target="_blank" rel="noopener noreferrer">Neuron</a>
                        <button type="button" data-db-find-alternatives>Alternatives</button>
                    <button type="button" data-db-find-synergy>Souvent jouée avec…</button>
                    </div>
                    <div class="db-card-constraints">
                        <button type="button" class="${locked ? 'is-active' : ''}" data-db-lock-card>${locked ? `✓ Garder ×${esc(lockedQty(state.zone, row.id))}` : `Garder ×${esc(recommended)}`}</button>
                        <button type="button" class="${excluded ? 'is-active danger' : ''}" data-db-exclude-card>${excluded ? '✓ Écartée' : 'Écarter'}</button>
                    </div>
                </div>
                <div class="db-stat db-usage-stat">
                    <span>Utilisation</span>
                    <strong>${esc(row.frequency_pct)} %</strong>
                    <small>${esc(row.sample_appearances)}/${esc(row.sample_denominator)} listes</small>
                </div>
                <div class="db-stat db-copies-stat">
                    <span>Quantité habituelle</span>
                    <strong>×${esc(recommended)}</strong>
                    <small title="${esc(distribution)}">moy. ${esc(row.average_copies)}</small>
                </div>
                <div class="db-stat db-role-stat">
                    <span>Rôle indicatif</span>
                    <strong>${esc((row.role_tags || [row.role]).join(" · "))}</strong>
                    <small>${esc(row.archetype || row.type || '')}</small>
                </div>
                <div class="db-stat db-price-stat">
                    <span>Prix / carte</span>
                    <strong>${esc(price)}</strong>
                    ${trendMarkup(row)}
                </div>
                <div class="db-owned-control" title="Quantité que tu possèdes">
                    <button class="db-qty-button" type="button" data-owned-delta="-1" aria-label="Retirer un exemplaire">−</button>
                    <output>${esc(owned)}</output>
                    <button class="db-qty-button" type="button" data-owned-delta="1" aria-label="Ajouter un exemplaire">+</button>
                </div>
            </article>`;
    };

    const renderCards = () => {
        const zones = state.analysis?.zones || {};
        const rows = zones[state.zone] || [];
        els.mainTotal.textContent = String((zones.main || []).length);
        els.extraTotal.textContent = String((zones.extra || []).length);
        els.sideTotal.textContent = String((zones.side || []).length);
        const filtered = rows.filter((row) => {
            if (!importanceAllowed(row)) return false;
            if (els.ownedFilter.checked && ownedQty(row.id) >= Number(row.recommended_copies || 0)) return false;
            return true;
        });
        const visible = filtered.slice(0, state.shown);
        els.cardList.innerHTML = visible.length
            ? visible.map(cardRow).join('')
            : '<div class="db-state-card"><strong>Aucune carte avec ces filtres.</strong><span>Essaie d’afficher davantage de catégories.</span></div>';
        els.loadMore.hidden = filtered.length <= state.shown;
        renderOwnedSummary();
        renderConstraints();
    };

    const renderOwnedSummary = () => {
        const zones = state.analysis?.zones;
        if (!zones) { els.ownedSummary.hidden = true; return; }
        let ownedCopies = 0;
        let remainingKnown = 0;
        let unknown = 0;
        const seen = new Set();
        ['main', 'extra', 'side'].forEach((zone) => {
            (zones[zone] || []).forEach((row) => {
                if (!['core', 'frequent'].includes(row.importance)) return;
                const key = `${zone}:${row.id}`;
                if (seen.has(key)) return;
                seen.add(key);
                const target = Number(row.recommended_copies || 0);
                const have = Math.min(target, ownedQty(row.id));
                ownedCopies += have;
                const missing = Math.max(0, target - have);
                if (!missing) return;
                if (row.cardmarket_price === null || row.cardmarket_price === undefined) unknown += 1;
                else remainingKnown += Number(row.cardmarket_price) * missing;
            });
        });
        els.ownedSummary.hidden = ownedCopies === 0;
        els.ownedCount.textContent = String(ownedCopies);
        els.remainingCost.textContent = unknown
            ? `${money(remainingKnown)} + ${unknown} inconnu(s)`
            : money(remainingKnown);
    };

    const renderSources = () => {
        const sources = state.analysis?.sources || [];
        els.sourceCount.textContent = String(sources.length);
        els.sources.innerHTML = sources.length ? sources.map((source) => {
            const details = [
                source.tournament ? 'Tournoi' : 'Communautaire',
                source.published ? frDate(source.published) : null,
                source.placement || null,
                `${source.main_count}/${source.extra_count}/${source.side_count}`,
            ].filter(Boolean).join(' · ');
            return `<div class="db-source-item"><a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title)}</a><small>${esc(details)}</small></div>`;
        }).join('') : '<p>Aucune source exploitable avec les filtres actuels.</p>';
    };

    const renderFallback = () => {
        const cards = state.analysis?.fallback_archetype_cards || [];
        els.degraded.hidden = !state.analysis?.degraded;
        els.fallbackGrid.innerHTML = cards.map((card) => `
            <article class="db-fallback-card">
                ${card.image_url ? `<img src="${esc(card.image_url)}" loading="lazy" alt="${esc(card.name)}">` : '<span></span>'}
                <div><strong>${esc(card.name)}</strong><small>${esc(card.zone)} · ${card.cardmarket_price === null ? 'Prix inconnu' : money(card.cardmarket_price)}</small></div>
            </article>`).join('');
    };

    const renderFreespots = () => {
        const data = state.analysis?.freespots;
        if (!data || !(data.categories || []).length) {
            els.freespotPanel.hidden = true;
            return;
        }
        els.freespotPanel.hidden = false;
        els.freespotStats.innerHTML = `
            <article><span>Slots génériques moyens (Main)</span><strong>${esc(data.main_generic_slots_average)}</strong><small>médiane ${esc(data.main_generic_slots_median)} · plage ${esc(data.main_generic_slots_min)}–${esc(data.main_generic_slots_max)}</small></article>
            <article><span>Profil de génération</span><strong>${esc((data.profiles || []).find((p) => p.key === state.freespotProfile)?.label || 'Automatique')}</strong><small>Le core reste prioritaire.</small></article>`;
        els.freespotCategories.innerHTML = (data.categories || []).map((category) => {
            const cardChip = (row, zone) => `<button type="button" class="db-freespot-card" data-db-freespot-card="${esc(zone)}:${esc(row.id)}" title="${esc(row.why_played || '')}">
                <span>${esc(row.name)}</span><small>${esc(row.frequency_pct)} % · ×${esc(row.recommended_copies)} · ${row.cardmarket_price == null ? 'prix inconnu' : esc(money(row.cardmarket_price))}</small>
            </button>`;
            const main = (category.main_candidates || []).slice(0, 7);
            const side = (category.side_candidates || []).slice(0, 5);
            return `<article class="db-freespot-category">
                <div class="db-freespot-category-head"><strong>${esc(category.label)}</strong><span>${esc(category.main_unique)} Main · ${esc(category.side_unique)} Side</span></div>
                ${main.length ? `<div><b>Main</b><div class="db-freespot-card-list">${main.map((row) => cardChip(row, 'main')).join('')}</div></div>` : ''}
                ${side.length ? `<div><b>Side</b><div class="db-freespot-card-list">${side.map((row) => cardChip(row, 'side')).join('')}</div></div>` : ''}
            </article>`;
        }).join('');
    };

    const renderAnalysis = () => {
        const a = state.analysis;
        if (!a) return;
        els.loading.hidden = true;
        els.error.hidden = true;
        els.results.hidden = false;
        els.title.textContent = a.variant || a.query;
        els.subtitle.textContent = a.degraded
            ? 'Aucune decklist exploitable : Hamtaro affiche uniquement les cartes reconnues sans inventer de statistiques.'
            : `${a.samples_analyzed} listes uniques après dédoublonnage et filtres.`;
        els.samples.textContent = String(a.samples_analyzed);
        els.tournaments.textContent = `${a.tournament_samples} tournoi${a.tournament_samples > 1 ? 's' : ''} · ${a.side_samples} liste${a.side_samples > 1 ? 's' : ''} avec Side`;
        const confidence = a.confidence || {};
        els.confidence.textContent = confidence.score === undefined ? '—' : `${confidence.score}/100`;
        els.confidenceLabel.textContent = confidence.label || '—';
        els.basePrice.textContent = priceSummary(a.base_price);
        els.corePrice.textContent = priceSummary(a.core_price);
        els.priceDate.textContent = `Données récupérées le ${frDate(a.price_checked_on)}`;
        const freshness = a.source_freshness || {};
        els.newestSource.textContent = freshness.newest ? frDate(freshness.newest) : '—';
        els.sourceWindow.textContent = freshness.oldest && freshness.newest
            ? `Échantillon daté du ${frDate(freshness.oldest)} au ${frDate(freshness.newest)}`
            : `${freshness.dated_samples || 0} liste(s) datée(s)`;
        const banlist = a.banlist || {};
        els.banlistStatus.textContent = banlist.verified ? 'Vérifiée' : 'À confirmer';
        els.banlistDate.textContent = banlist.effective_from
            ? `Effective depuis le ${frDate(banlist.effective_from)} · source Konami`
            : 'Source officielle Konami non joignable lors de cette analyse';
        renderWarnings(a.warnings);
        renderVariants();
        renderEngines();
        renderPackages();
        renderEngineComparisons();
        renderConfigurations();
        renderFlexChoices();
        renderFreespots();
        renderProfile();
        renderComposition();
        renderCards();
        renderSources();
        renderFallback();
        if (!state.generated) els.generatedPanel.hidden = true;
    };

    const generatedZone = (title, rows) => `
        <section class="db-generated-zone">
            <h4>${esc(title)}</h4>
            <ul>${rows.map((row) => {
                const line = row.line_price === null ? '—' : money(row.line_price);
                const purchase = row.purchase_price === null ? '—' : money(row.purchase_price);
                return `<li><strong>×${esc(row.copies)}</strong><span>${esc(row.name)}</span><span title="Valeur totale : ${esc(line)}">${esc(purchase)}</span></li>`;
            }).join('')}</ul>
        </section>`;

    const renderBudgetChanges = (changes) => {
        const rows = changes || [];
        els.budgetChanges.hidden = rows.length === 0;
        if (!rows.length) { els.budgetChanges.innerHTML = ''; return; }
        els.budgetChanges.innerHTML = `
            <strong>Substitutions budget appliquées</strong>
            <p>Hamtaro n'utilise que des cartes réellement observées dans les listes analysées.</p>
            <ul>${rows.slice(0, 20).map((change) => `<li><span>${esc(change.zone.toUpperCase())}</span><del>${esc(change.removed)}</del><b>→</b><ins>${esc(change.added)}</ins><small>−${money(change.saving_per_copy)}</small></li>`).join('')}</ul>`;
    };

    const renderLegality = (legality) => {
        if (!legality) { els.legalityCard.hidden = true; return; }
        els.legalityCard.hidden = false;
        const violations = legality.violations || [];
        els.legalityCard.classList.toggle('is-legal', !!legality.legal);
        els.legalityCard.classList.toggle('is-illegal', !legality.legal);
        els.legalityCard.innerHTML = legality.legal
            ? `<strong>✓ Légalité TCG globale : aucun conflit détecté</strong><span>Les limites sont contrôlées sur Main + Extra + Side réunis.</span>`
            : `<strong>⚠ Légalité à vérifier</strong><ul>${violations.map((v) => {
                if (v.type === 'tcg_limit') return `<li>${esc(v.name)} : ×${esc(v.count)} pour une limite ×${esc(v.limit)}</li>`;
                if (v.type === 'main_size') return `<li>Main Deck : ${esc(v.count)} cartes</li>`;
                return `<li>${esc(v.type)} : ${esc(v.count)}</li>`;
            }).join('')}</ul>`;
    };

    const renderUpgradePaths = (paths) => {
        const rows = paths || [];
        els.upgradePanel.hidden = rows.length === 0;
        if (!rows.length) { els.upgradePanel.innerHTML = ''; return; }
        els.upgradePanel.innerHTML = `
            <strong>Parcours d'amélioration</strong>
            <p>Tu peux voir ce qui change si tu passes vers une version plus ambitieuse.</p>
            <div class="db-upgrade-grid">${rows.map((path) => `
                <article>
                    <div><b>${esc(path.label)}</b><span>${path.unknown_price_lines ? `${money(path.additional_known_purchase)} + prix inconnus` : `≈ ${money(path.additional_known_purchase)} de plus`}</span></div>
                    <small>${esc(path.change_count)} changement(s) de quantité</small>
                    <ul>${(path.changes || []).slice(0, 8).map((change) => `<li><span>${esc(change.zone.toUpperCase())}</span><strong>${esc(change.name)}</strong><small>×${esc(change.from)} → ×${esc(change.to)}</small></li>`).join('')}</ul>
                </article>`).join('')}</div>`;
    };

    const renderCompare = (payload) => {
        const data = payload?.import;
        if (!data) { els.compareResults.hidden = true; return; }
        const missing = data.missing_core || [];
        const legality = data.legality || {};
        const statusLabel = { standard: 'Standard', unusual: 'Atypique', wrong_zone: 'Zone inhabituelle', unseen: 'Non observée' };
        const unusual = ['main', 'extra', 'side'].flatMap((zone) => (data.zones?.[zone] || []).filter((row) => row.status !== 'standard').map((row) => ({ ...row, zone })));
        els.compareResults.hidden = false;
        els.compareResults.innerHTML = `
            <div class="db-compare-summary">
                <article><span>Alignement Core/fréquent</span><strong>${esc(data.alignment_score)} %</strong></article>
                <article><span>Format importé</span><strong>${esc(data.main_count)} / ${esc(data.extra_count)} / ${esc(data.side_count)}</strong><small>Main / Extra / Side</small></article>
                <article><span>Légalité</span><strong>${legality.legal ? 'OK' : 'À corriger'}</strong><small>${esc((legality.violations || []).length)} conflit(s)</small></article>
                <article><span>Core manquants</span><strong>${esc(missing.length)}</strong></article>
            </div>
            ${missing.length ? `<div class="db-compare-block"><strong>Core manquants</strong><ul>${missing.slice(0, 16).map((row) => `<li><span>${esc(row.zone.toUpperCase())}</span><b>${esc(row.name)}</b><small>tu as ×${esc(row.have)} · conseillé ×${esc(row.recommended)}</small></li>`).join('')}</ul></div>` : ''}
            ${unusual.length ? `<div class="db-compare-block"><strong>Choix à regarder</strong><ul>${unusual.slice(0, 20).map((row) => `<li><span>${esc(row.zone.toUpperCase())}</span><b>${esc(row.name)}</b><small>${esc(statusLabel[row.status] || row.status)}${row.frequency_pct !== null && row.frequency_pct !== undefined ? ` · ${esc(row.frequency_pct)} %` : ''}</small></li>`).join('')}</ul></div>` : '<p class="db-success-note">Ta liste ne contient aucun choix atypique détecté dans l’échantillon analysé.</p>'}`;
    };

    const renderReadiness = (readiness) => {
        if (!readiness) { els.readinessPanel.hidden = true; els.readinessPanel.innerHTML = ''; return; }
        els.readinessPanel.hidden = false;
        els.readinessPanel.innerHTML = `
            <div class="db-readiness-head"><div><span>Score de préparation</span><strong>${esc(readiness.score)}/100 · ${esc(readiness.label)}</strong></div><meter min="0" max="100" value="${esc(readiness.score)}"></meter></div>
            <div class="db-readiness-checks">${(readiness.checks || []).map((check) => `
                <span class="${check.ok ? 'ok' : 'warn'}"><b>${check.ok ? '✓' : '!'}</b><strong>${esc(check.label)}</strong><small>${esc(check.detail)}</small></span>`).join('')}</div>`;
    };

    const renderPurchasePlan = (phases) => {
        const rows = phases || [];
        els.purchasePlan.hidden = rows.length === 0;
        if (!rows.length) { els.purchasePlan.innerHTML = ''; return; }
        els.purchasePlan.innerHTML = `
            <div class="db-section-heading compact"><div><span class="db-kicker">Ordre d'achat conseillé</span><h3>Construire le deck progressivement</h3><p>Les cartes déjà possédées sont retirées de cette liste.</p></div></div>
            <div class="db-purchase-grid">${rows.map((phase, index) => `
                <article><div class="db-phase-title"><span>Étape ${index + 1}</span><strong>${esc(phase.title)}</strong><b>${phase.unknown_price_lines ? `${money(phase.known_total)} + inconnu` : money(phase.known_total)}</b></div>
                <ul>${(phase.cards || []).slice(0, 16).map((card) => `<li><span>${esc(card.zone.toUpperCase())}</span><strong>${esc(card.name)}</strong><small>à acheter ×${esc(card.missing)} · ${card.line_price === null ? 'prix inconnu' : money(card.line_price)}</small></li>`).join('')}</ul></article>`).join('')}</div>`;
    };

    const showAlternatives = async (row) => {
        if (!state.query || !row) return;
        els.alternativesPanel.hidden = false;
        els.alternativesTitle.textContent = `Alternatives à ${row.name}`;
        els.alternativesNote.textContent = 'Recherche des alternatives observées…';
        els.alternativesGrid.innerHTML = '';
        try {
            const params = buildParams(false);
            params.set('card_id', String(row.id));
            params.set('zone', state.zone);
            const payload = await fetchJson(`/api/deck-builder/alternatives?${params}`);
            const alternatives = payload.alternatives || [];
            els.alternativesNote.textContent = payload.note || '';
            els.alternativesGrid.innerHTML = alternatives.length ? alternatives.map((alt) => `
                <article data-alt-id="${esc(alt.id)}" data-source-id="${esc(row.id)}">
                    ${alt.image_url ? `<img src="${esc(alt.image_url)}" loading="lazy" alt="${esc(alt.name)}">` : ''}
                    <div><strong>${esc(alt.name)}</strong><small>${esc(alt.frequency_pct)} % · ×${esc(alt.recommended_copies)} · ${alt.cardmarket_price === null ? 'prix inconnu' : money(alt.cardmarket_price)}</small><p>${esc(alt.reason || '')}</p></div>
                    <button type="button" data-db-apply-alternative>Utiliser cette option</button>
                </article>`).join('') : '<p>Aucune alternative suffisamment proche n’a été observée avec les filtres actuels.</p>';
            els.alternativesPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } catch (error) {
            els.alternativesNote.textContent = error.message;
        }
    };

    const showSynergy = async (row) => {
        if (!state.query || !row) return;
        els.synergyPanel.hidden = false;
        els.synergyTitle.textContent = `Cartes souvent jouées avec ${row.name}`;
        els.synergyNote.textContent = 'Calcul des associations dans les decklists analysées…';
        els.synergyGrid.innerHTML = '';
        try {
            const params = buildParams(false);
            params.set('card_id', String(row.id));
            params.set('zone', state.zone);
            const payload = await fetchJson(`/api/deck-builder/synergy?${params}`);
            const rows = payload.synergies || [];
            els.synergyNote.textContent = payload.note || '';
            els.synergyGrid.innerHTML = rows.length ? rows.map((item) => `
                <article>
                    ${item.image_url ? `<img src="${esc(item.image_url)}" loading="lazy" alt="${esc(item.name)}">` : ''}
                    <div><strong>${esc(item.name)}</strong><small>${esc(item.zone.toUpperCase())} · ×${esc(item.recommended_copies)} · ${item.cardmarket_price === null ? 'prix inconnu' : money(item.cardmarket_price)}</small><p><b>${esc(item.strength_label)}</b> · ${esc(item.together_pct)} % avec la carte source, ${esc(item.overall_pct)} % au total · lift ×${esc(item.lift)}</p></div>
                </article>`).join('') : '<p>Aucune association suffisamment nette n’a été trouvée dans cet échantillon.</p>';
            els.synergyPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } catch (error) {
            els.synergyNote.textContent = error.message;
        }
    };

    const renderDiagnostics = (diagnostics) => {
        if (!diagnostics) { els.diagnosticsPanel.hidden = true; els.diagnosticsPanel.innerHTML = ''; return; }
        const mismatch = diagnostics.ratio_mismatches || [];
        const packages = diagnostics.package_health || [];
        const roles = diagnostics.role_summary || [];
        els.diagnosticsPanel.hidden = false;
        els.diagnosticsPanel.innerHTML = `
            <div class="db-section-heading compact"><div><span class="db-kicker">Diagnostic de cohérence</span><h3>Écart au consensus observé</h3><p>${esc(diagnostics.note || '')}</p></div></div>
            <div class="db-diagnostics-summary">
                <article><span>Alignement des ratios</span><strong>${esc(diagnostics.ratio_alignment_score)} / 100</strong><small>Mesure descriptive, pas une note de puissance.</small></article>
                <article><span>Choix flex</span><strong>${esc(diagnostics.flex_lines)}</strong><small>${esc(diagnostics.rare_lines)} ligne(s) rarement observée(s).</small></article>
            </div>
            ${(diagnostics.signals || []).length ? `<div class="db-diagnostic-signals">${diagnostics.signals.map((signal) => `<div><strong>${esc(signal.label)}</strong><small>${esc(signal.detail)}</small></div>`).join('')}</div>` : ''}
            ${mismatch.length ? `<details><summary>Ratios stables différents du consensus (${mismatch.length})</summary><div class="db-diagnostic-list">${mismatch.map((item) => `<span><b>${esc(item.zone.toUpperCase())}</b>${esc(item.name)} <small>×${esc(item.selected)} ici · ×${esc(item.usual)} habituellement · confiance ${esc(item.ratio_confidence_pct)} %</small></span>`).join('')}</div></details>` : ''}
            ${packages.length ? `<details><summary>État des packages détectés (${packages.length})</summary><div class="db-diagnostic-list">${packages.map((item) => `<span class="${item.status === 'partial' ? 'warn' : 'ok'}"><b>${item.status === 'partial' ? 'Partiel' : 'Complet'}</b>${esc(item.name)} <small>${esc(item.present)}/${esc(item.total)} cartes · ${esc(item.coverage_pct)} %</small></span>`).join('')}</div></details>` : ''}
            ${roles.length ? `<details><summary>Rôles présents dans le Main</summary><div class="db-role-chips">${roles.map((item) => `<span><b>${esc(item.role)}</b>${esc(item.copies)} copies</span>`).join('')}</div></details>` : ''}`;
    };

    const renderOpeningHand = (opening) => {
        if (!opening?.available) { els.openingPanel.hidden = true; els.openingPanel.innerHTML = ''; return; }
        els.openingPanel.hidden = false;
        els.openingPanel.innerHTML = `
            <div class="db-section-heading compact"><div><span class="db-kicker">Main de départ estimée</span><h3>Probabilités sur 5 cartes</h3><p>${esc(opening.note || '')}</p></div></div>
            <div class="db-opening-grid">
                <article><span>Starter / Searcher</span><strong>${esc(opening.starter_open_pct)} %</strong><small>${esc(opening.starter_copies)} cartes détectées dans ${esc(opening.deck_size)}</small><meter min="0" max="100" value="${esc(opening.starter_open_pct)}"></meter></article>
                <article><span>Interaction</span><strong>${esc(opening.interaction_open_pct)} %</strong><small>${esc(opening.interaction_copies)} cartes détectées dans ${esc(opening.deck_size)}</small><meter min="0" max="100" value="${esc(opening.interaction_open_pct)}"></meter></article>
            </div>`;
    };

    const renderGenerated = (payload) => {
        state.generated = payload.generated_deck || null;
        if (!state.generated) {
            els.generatedPanel.hidden = false;
            els.generatedTitle.textContent = 'Impossible de générer une liste fiable';
            els.generatedNote.textContent = payload.generation_error || 'Pas assez de données.';
            els.generatedZones.innerHTML = '';
            els.generatedPurchase.textContent = '—';
            els.generatedSavings.textContent = '—';
            renderBudgetChanges([]);
            renderLegality(null);
            renderUpgradePaths([]);
            renderReadiness(null);
            renderOpeningHand(null);
            renderDiagnostics(null);
            renderPurchasePlan([]);
            renderWarnings(payload.generation_warnings || [payload.generation_error], els.generationWarnings);
            return;
        }
        const d = state.generated;
        els.generatedPanel.hidden = false;
        els.generatedTitle.textContent = `${payload.query} · ${d.mode === 'budget' ? 'Budget' : d.mode === 'optimal' ? 'Optimal' : 'Standard'} · ${d.freespot_profile_label || 'Automatique'}`;
        const budgetText = d.budget !== null && d.budget !== undefined
            ? (d.within_budget === true
                ? `Le coût restant à acheter rentre dans ton budget de ${money(d.budget)}.`
                : d.within_budget === false
                    ? `Le coût restant dépasse encore ton budget de ${money(d.budget_overrun)}.`
                    : 'Budget impossible à confirmer car certains prix sont inconnus.')
            : 'Liste synthétisée à partir des cartes et quantités réellement observées.';
        els.generatedNote.textContent = budgetText;
        els.generatedMainCount.textContent = `${d.main_count} / 40`;
        els.generatedExtraCount.textContent = `${d.extra_count} / 15`;
        els.generatedSideCount.textContent = `${d.side_count} / 15`;
        els.generatedPrice.textContent = d.unknown_price_lines
            ? `${money(d.known_total_price)} + ${d.unknown_price_lines} inconnu(s)`
            : money(d.known_total_price);
        els.generatedPurchase.textContent = d.unknown_purchase_lines
            ? `${money(d.known_purchase_price)} + ${d.unknown_purchase_lines} inconnu(s)`
            : money(d.known_purchase_price);
        els.generatedSavings.textContent = money(d.owned_savings || 0);
        renderWarnings(payload.generation_warnings || [], els.generationWarnings);
        renderBudgetChanges(d.budget_substitutions || []);
        renderLegality(d.legality);
        renderUpgradePaths(d.upgrade_paths || []);
        renderReadiness(d.readiness);
        renderOpeningHand(d.opening_hand);
        renderDiagnostics(d.diagnostics);
        renderPurchasePlan(d.purchase_plan || []);
        els.generatedZones.innerHTML = [
            generatedZone('Main Deck', d.main || []),
            generatedZone('Extra Deck', d.extra || []),
            generatedZone('Side Deck', d.side || []),
        ].join('');
        els.generatedPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const analyze = async ({ preserveVariant = false } = {}) => {
        const query = els.query.value.trim();
        if (query.length < 2) return showError('Entre au moins 2 caractères pour rechercher un deck.');
        const queryChanged = state.query && state.query !== query;
        state.query = query;
        if (!preserveVariant) state.variant = '';
        if (queryChanged) {
            state.locked = emptyZones();
            state.excluded = emptyExcluded();
            saveConstraints();
        }
        els.alternativesPanel.hidden = true;
        els.synergyPanel.hidden = true;
        state.generated = null;
        state.shown = 24;
        const serial = ++state.requestSerial;
        setBusy(true);
        try {
            const payload = await fetchJson(`/api/deck-builder/analyze?${buildParams(false)}`);
            if (serial !== state.requestSerial) return;
            state.analysis = payload;
            renderAnalysis();
            syncUrl(false);
        } catch (error) {
            if (serial !== state.requestSerial) return;
            showError(error.message);
        }
    };

    const generationBody = () => {
        const budgetRaw = els.budget.value.trim();
        return {
            q: state.query || els.query.value.trim(),
            mode: state.mode,
            freespot_profile: state.freespotProfile || 'auto',
            budget: state.mode === 'budget' && budgetRaw ? Number(budgetRaw) : null,
            limit: els.limit.value ? Number(els.limit.value) : null,
            days: els.days.value ? Number(els.days.value) : null,
            tournament_only: els.tournamentOnly.checked,
            variant: state.variant || null,
            owned_cards: state.owned,
            locked_cards: state.locked,
            excluded_cards: state.excluded,
        };
    };

    const generate = async () => {
        if (!state.query) return analyze();
        if (state.mode === 'budget' && !els.budget.value.trim()) {
            return showError('Indique ton budget restant avant de générer la version Budget.', true);
        }
        const serial = ++state.requestSerial;
        const button = $('[data-db-generate]');
        button.disabled = true;
        try {
            const payload = await fetchJson('/api/deck-builder/generate', {
                method: 'POST',
                body: JSON.stringify(generationBody()),
            });
            if (serial !== state.requestSerial) return;
            state.analysis = payload;
            renderAnalysis();
            renderGenerated(payload);
            syncUrl(false);
        } catch (error) {
            showError(error.message, true);
        } finally {
            button.disabled = false;
        }
    };

    const compareDeck = async () => {
        if (!state.query) return showError('Analyse d’abord un deck avant de comparer ta liste.', true);
        const deckInput = els.compareInput.value.trim();
        if (!deckInput) return showError('Colle un code YDKE ou un fichier .ydk dans la zone de comparaison.', true);
        els.compareButton.disabled = true;
        const old = els.compareButton.textContent;
        els.compareButton.textContent = 'Comparaison…';
        try {
            const payload = await fetchJson('/api/deck-builder/compare', {
                method: 'POST',
                body: JSON.stringify({
                    q: state.query,
                    deck_input: deckInput,
                    limit: els.limit.value ? Number(els.limit.value) : null,
                    days: els.days.value ? Number(els.days.value) : null,
                    tournament_only: els.tournamentOnly.checked,
                    variant: state.variant || null,
                }),
            });
            renderCompare(payload);
            els.compareResults.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } catch (error) {
            showError(error.message, true);
        } finally {
            els.compareButton.disabled = false;
            els.compareButton.textContent = old;
        }
    };

    const syncUrl = (copy = false) => {
        const params = buildParams(true);
        const url = new URL(window.location.href);
        url.search = params.toString();
        history.replaceState(null, '', url);
        if (copy && navigator.clipboard) {
            navigator.clipboard.writeText(url.toString()).then(() => {
                const button = $('[data-db-share]');
                const old = button.textContent;
                button.textContent = 'Lien copié !';
                setTimeout(() => { button.textContent = old; }, 1400);
            }).catch(() => {});
        }
    };

    let suggestionTimer = null;
    const loadSuggestions = () => {
        clearTimeout(suggestionTimer);
        const q = els.query.value.trim();
        if (q.length < 1) { els.suggestions.hidden = true; return; }
        suggestionTimer = setTimeout(async () => {
            try {
                const payload = await fetchJson(`/api/deck-builder/suggestions?q=${encodeURIComponent(q)}`);
                const values = payload.suggestions || [];
                els.suggestions.innerHTML = values.map((value) => `<button type="button" data-db-suggestion="${esc(value)}">${esc(value)}</button>`).join('');
                els.suggestions.hidden = values.length === 0;
            } catch (_) {
                els.suggestions.hidden = true;
            }
        }, 200);
    };

    els.form.addEventListener('submit', (event) => { event.preventDefault(); analyze(); });
    els.query.addEventListener('input', loadSuggestions);
    els.query.addEventListener('keydown', (event) => { if (event.key === 'Escape') els.suggestions.hidden = true; });

    document.addEventListener('click', (event) => {
        const suggestion = event.target.closest?.('[data-db-suggestion]');
        if (suggestion && root.contains(suggestion)) {
            els.query.value = suggestion.dataset.dbSuggestion;
            els.suggestions.hidden = true;
            analyze();
        }
    });

    $$('[data-db-quick-query]').forEach((button) => button.addEventListener('click', () => {
        els.query.value = button.dataset.dbQuickQuery;
        analyze();
    }));

    $$('[data-db-mode]').forEach((button) => button.addEventListener('click', () => {
        state.mode = button.dataset.dbMode;
        $$('[data-db-mode]').forEach((other) => other.classList.toggle('is-active', other === button));
        els.budgetWrap.hidden = state.mode !== 'budget';
        syncUrl(false);
    }));

    els.freespotProfile.addEventListener('change', () => {
        state.freespotProfile = els.freespotProfile.value || 'auto';
        clearGenerated();
        renderFreespots();
        syncUrl(false);
    });

    $$('[data-db-zone]').forEach((button) => button.addEventListener('click', () => {
        state.zone = button.dataset.dbZone;
        state.shown = 24;
        $$('[data-db-zone]').forEach((other) => other.classList.toggle('is-active', other === button));
        renderCards();
    }));

    els.importance.addEventListener('change', () => { state.shown = 24; renderCards(); });
    els.ownedFilter.addEventListener('change', renderCards);
    els.loadMore.addEventListener('click', () => { state.shown += 24; renderCards(); });
    $('[data-db-generate]').addEventListener('click', generate);
    $('[data-db-share]').addEventListener('click', () => syncUrl(true));
    els.compareButton.addEventListener('click', compareDeck);

    [els.days, els.limit, els.tournamentOnly].forEach((control) => control.addEventListener('change', () => {
        if (state.query) analyze({ preserveVariant: false });
    }));

    els.variants.addEventListener('click', (event) => {
        const button = event.target.closest('[data-db-variant]');
        if (!button) return;
        const value = button.dataset.dbVariant;
        state.variant = value === state.query ? '' : value;
        analyze({ preserveVariant: true });
    });
    els.clearVariant.addEventListener('click', () => { state.variant = ''; analyze({ preserveVariant: true }); });

    els.cardList.addEventListener('click', (event) => {
        const rowEl = event.target.closest('[data-card-id]');
        if (!rowEl) return;
        const id = String(rowEl.dataset.cardId);
        const dataRow = (state.analysis?.zones?.[state.zone] || []).find((card) => String(card.id) === id);
        if (!dataRow) return;

        const ownedButton = event.target.closest('[data-owned-delta]');
        if (ownedButton) {
            const delta = Number(ownedButton.dataset.ownedDelta || 0);
            state.owned[id] = Math.max(0, Math.min(3, ownedQty(id) + delta));
            if (!state.owned[id]) delete state.owned[id];
            saveOwned();
            clearGenerated();
            renderCards();
            return;
        }
        if (event.target.closest('[data-db-lock-card]')) {
            state.locked[state.zone] ||= {};
            state.excluded[state.zone] ||= [];
            if (lockedQty(state.zone, id)) {
                delete state.locked[state.zone][id];
            } else {
                state.locked[state.zone][id] = Math.max(1, Number(dataRow.recommended_copies || 1));
                state.excluded[state.zone] = state.excluded[state.zone].filter((value) => String(value) !== id);
            }
            saveConstraints();
            clearGenerated();
            renderCards();
            return;
        }
        if (event.target.closest('[data-db-exclude-card]')) {
            state.locked[state.zone] ||= {};
            state.excluded[state.zone] ||= [];
            if (isExcluded(state.zone, id)) {
                state.excluded[state.zone] = state.excluded[state.zone].filter((value) => String(value) !== id);
            } else {
                state.excluded[state.zone].push(Number(id));
                delete state.locked[state.zone][id];
            }
            saveConstraints();
            clearGenerated();
            renderCards();
            return;
        }
        if (event.target.closest('[data-db-find-alternatives]')) {
            showAlternatives(dataRow);
            return;
        }
        if (event.target.closest('[data-db-find-synergy]')) {
            showSynergy(dataRow);
        }
    });

    els.freespotCategories.addEventListener('click', (event) => {
        const button = event.target.closest('[data-db-freespot-card]');
        if (!button) return;
        const [zone, id] = String(button.dataset.dbFreespotCard || '').split(':');
        if (!['main', 'side'].includes(zone) || !id) return;
        state.zone = zone;
        state.shown = 120;
        $$('[data-db-zone]').forEach((tab) => tab.classList.toggle('is-active', tab.dataset.dbZone === zone));
        els.importance.value = 'all';
        renderCards();
        requestAnimationFrame(() => root.querySelector(`[data-card-id="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    });

    els.configurations.addEventListener('click', (event) => {
        const button = event.target.closest('[data-db-apply-configuration]');
        if (!button) return;
        const item = (state.analysis?.configurations || [])[Number(button.dataset.dbApplyConfiguration)];
        if (!item) return;
        (item.lock_cards || []).forEach((card) => {
            const zone = card.zone;
            const id = String(card.id);
            state.locked[zone] ||= {};
            state.excluded[zone] ||= [];
            state.locked[zone][id] = Math.max(1, Math.min(3, Number(card.copies || 1)));
            state.excluded[zone] = state.excluded[zone].filter((value) => String(value) !== id);
        });
        saveConstraints();
        clearGenerated();
        renderCards();
        renderConstraints();
        button.textContent = 'Construction appliquée ✓';
    });

    els.flexGrid.addEventListener('click', (event) => {
        const button = event.target.closest('[data-db-choose-flex]');
        if (!button) return;
        const [groupIndexRaw, optionIndexRaw] = String(button.dataset.dbChooseFlex || '').split(':');
        const group = (state.analysis?.flex_choices || [])[Number(groupIndexRaw)];
        const option = group?.options?.[Number(optionIndexRaw)];
        if (!group || !option) return;
        const zone = group.zone;
        state.locked[zone] ||= {};
        state.excluded[zone] ||= [];
        (group.options || []).forEach((candidate) => {
            const id = String(candidate.id);
            delete state.locked[zone][id];
            if (String(candidate.id) !== String(option.id) && !state.excluded[zone].map(String).includes(id)) {
                state.excluded[zone].push(Number(candidate.id));
            }
        });
        const chosenId = String(option.id);
        state.excluded[zone] = state.excluded[zone].filter((value) => String(value) !== chosenId);
        state.locked[zone][chosenId] = Math.max(1, Math.min(3, Number(option.recommended_copies || 1)));
        saveConstraints();
        clearGenerated();
        renderCards();
        renderConstraints();
        button.textContent = 'Choisie ✓';
    });

    els.packages.addEventListener('click', (event) => {
        const button = event.target.closest('[data-db-apply-package]');
        if (!button) return;
        const pack = (state.analysis?.packages || [])[Number(button.dataset.dbApplyPackage)];
        if (!pack) return;
        (pack.cards || []).forEach((card) => {
            const zone = card.zone;
            const id = String(card.id);
            state.locked[zone] ||= {};
            state.excluded[zone] ||= [];
            state.locked[zone][id] = Math.max(1, Math.min(3, Number(card.recommended_copies || 1)));
            state.excluded[zone] = state.excluded[zone].filter((value) => String(value) !== id);
        });
        saveConstraints();
        clearGenerated();
        renderCards();
        renderConstraints();
        button.textContent = 'Package verrouillé ✓';
    });
    els.closeSynergy.addEventListener('click', () => { els.synergyPanel.hidden = true; });

    els.resetConstraints.addEventListener('click', () => {
        state.locked = emptyZones();
        state.excluded = emptyExcluded();
        saveConstraints();
        clearGenerated();
        renderCards();
    });
    els.closeAlternatives.addEventListener('click', () => { els.alternativesPanel.hidden = true; });
    els.alternativesGrid.addEventListener('click', (event) => {
        const button = event.target.closest('[data-db-apply-alternative]');
        const card = event.target.closest('[data-alt-id]');
        if (!button || !card) return;
        const altId = String(card.dataset.altId);
        const sourceId = String(card.dataset.sourceId);
        const altRow = (state.analysis?.zones?.[state.zone] || []).find((row) => String(row.id) === altId);
        if (!altRow) return;
        state.excluded[state.zone] ||= [];
        if (!state.excluded[state.zone].map(String).includes(sourceId)) state.excluded[state.zone].push(Number(sourceId));
        state.locked[state.zone] ||= {};
        delete state.locked[state.zone][sourceId];
        state.locked[state.zone][altId] = Math.max(1, Number(altRow.recommended_copies || 1));
        state.excluded[state.zone] = state.excluded[state.zone].filter((id) => String(id) !== altId);
        saveConstraints();
        clearGenerated();
        renderCards();
        els.alternativesPanel.hidden = true;
    });

    $('[data-db-copy-list]').addEventListener('click', () => {
        if (!state.generated?.text || !navigator.clipboard) return;
        navigator.clipboard.writeText(state.generated.text).catch(() => {});
    });
    $('[data-db-copy-ydke]').addEventListener('click', () => {
        if (!state.generated?.ydke || !navigator.clipboard) return;
        navigator.clipboard.writeText(state.generated.ydke).catch(() => {});
    });
    $('[data-db-download-ydk]').addEventListener('click', () => {
        if (!state.generated?.ydk) return;
        const blob = new Blob([state.generated.ydk], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        const base = (state.query || 'deck').toLowerCase().replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'deck';
        link.href = url;
        link.download = `${base}-${state.generated.mode || 'hamtaro'}.ydk`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 500);
    });
    els.compareFile.addEventListener('change', async () => {
        const file = els.compareFile.files?.[0];
        if (!file) return;
        try {
            els.compareInput.value = await file.text();
        } catch (_) {
            showError('Impossible de lire ce fichier .ydk.', true);
        }
    });

    const initial = new URLSearchParams(window.location.search);
    const initialQuery = initial.get('q') || '';
    const initialMode = initial.get('mode') || 'standard';
    const modeButton = $(`[data-db-mode="${CSS.escape(initialMode)}"]`);
    if (modeButton) modeButton.click();
    if (initial.get('budget')) els.budget.value = initial.get('budget');
    const initialFreespot = initial.get('freespot_profile') || 'auto';
    if ([...els.freespotProfile.options].some((opt) => opt.value === initialFreespot)) {
        els.freespotProfile.value = initialFreespot;
        state.freespotProfile = initialFreespot;
    }
    if (initial.get('days') !== null) els.days.value = initial.get('days');
    if (initial.get('limit')) els.limit.value = initial.get('limit');
    els.tournamentOnly.checked = initial.get('tournament_only') === '1';
    state.variant = initial.get('variant') || '';
    if (initialQuery) {
        els.query.value = initialQuery;
        state.query = initialQuery;
        analyze({ preserveVariant: true }).then(() => {
            if (initial.get('autogenerate') === '1') generate();
        });
    }
})();
