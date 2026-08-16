(() => {
    const root = document.getElementById("spider-catalog-controls");
    const gallery = document.getElementById("spider-card-gallery");
    const list = document.getElementById("spider-pool");
    const search = document.getElementById("spider-search");
    const countBox = document.getElementById("spider-search-count");
    const emptyBox = document.getElementById("spider-filter-empty");
    if (!root || !gallery || !list) return;

    const normalize = (value) => String(value || "")
        .toLocaleLowerCase("fr")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[’‘]/g, "'")
        .replace(/[–—]/g, "-")
        .replace(/[^a-z0-9]+/g, " ")
        .trim()
        .replace(/\s+/g, " ");

    const TYPE_LABELS = {
        all: "Toutes",
        normal: "Normal",
        effect: "Effet",
        ritual: "Rituel",
        fusion: "Fusion",
        synchro: "Synchro",
        xyz: "Xyz",
        link: "Lien",
        pendulum: "Pendule",
        spell: "Magie",
        trap: "Piège",
    };

    const TYPE_PRIORITY = ["link", "xyz", "synchro", "fusion", "ritual", "pendulum", "normal", "effect", "spell", "trap"];
    const state = {
        type: "all",
        zone: "",
        subtype: "",
        attribute: "",
        race: "",
        metric: "",
        archetype: "",
        visual: "",
        deck: "",
        image: "",
        sort: "name-asc",
    };

    const galleryEntries = [...gallery.querySelectorAll(".spider-gallery-card")];
    const listEntries = [...list.querySelectorAll("li[data-card-name]")];
    const galleryByName = new Map(galleryEntries.map((entry) => [normalize(entry.dataset.cardName), entry]));
    const listByName = new Map(listEntries.map((entry) => [normalize(entry.dataset.cardName), entry]));
    const cards = [];

    const selectors = {
        zone: document.getElementById("spider-filter-zone"),
        subtype: document.getElementById("spider-filter-subtype"),
        attribute: document.getElementById("spider-filter-attribute"),
        race: document.getElementById("spider-filter-race"),
        metric: document.getElementById("spider-filter-metric"),
        archetype: document.getElementById("spider-filter-archetype"),
        visual: document.getElementById("spider-filter-visual"),
        deck: document.getElementById("spider-filter-deck"),
        image: document.getElementById("spider-filter-image"),
        sort: document.getElementById("spider-sort"),
    };

    const typeButtons = [...root.querySelectorAll("[data-spider-type]")];
    const resetButton = document.getElementById("spider-reset-filters");
    const activeBox = document.getElementById("spider-active-filters");
    const statusBox = document.getElementById("spider-catalog-status");

    const appendOptions = (select, options) => {
        if (!select) return;
        const current = select.value;
        for (const option of options || []) {
            const element = document.createElement("option");
            element.value = option.value;
            element.textContent = `${option.label} (${option.count})`;
            select.appendChild(element);
        }
        if ([...select.options].some((option) => option.value === current)) select.value = current;
    };

    const primaryType = (meta) => {
        const keys = meta.type_keys || [];
        return TYPE_PRIORITY.find((key) => keys.includes(key)) || "";
    };

    const metricKey = (meta) => {
        const metric = meta.metric || {};
        return metric.kind && metric.value !== undefined ? `${metric.kind}:${metric.value}` : "";
    };

    const decorateCard = (entry, meta) => {
        const primary = primaryType(meta);
        if (primary) entry.dataset.spiderPrimary = primary;
        if (!entry.querySelector(".spider-card-meta")) {
            const metaBox = document.createElement("div");
            metaBox.className = "spider-card-meta";
            const labels = [];
            if (primary) labels.push(TYPE_LABELS[primary] || primary);
            if (meta.attribute_label) labels.push(meta.attribute_label);
            if (meta.metric?.label) labels.push(meta.metric.label);
            if (meta.race_label) labels.push(meta.race_label);
            for (const label of labels.slice(0, 4)) {
                const span = document.createElement("span");
                span.textContent = label;
                metaBox.appendChild(span);
            }
            entry.appendChild(metaBox);
        }
    };

    const readUrlState = () => {
        const params = new URLSearchParams(location.search);
        const mapping = {
            type: "spider_type", zone: "spider_zone", subtype: "spider_subtype",
            attribute: "spider_attribute", race: "spider_race", metric: "spider_metric",
            archetype: "spider_archetype", visual: "spider_visual", deck: "spider_deck",
            image: "spider_image", sort: "spider_sort",
        };
        for (const [key, param] of Object.entries(mapping)) {
            const value = params.get(param);
            if (value !== null && value !== "") state[key] = value;
        }
        const q = params.get("q");
        if (q !== null && search) search.value = q;
    };

    const writeUrlState = () => {
        const url = new URL(location.href);
        const mapping = {
            type: "spider_type", zone: "spider_zone", subtype: "spider_subtype",
            attribute: "spider_attribute", race: "spider_race", metric: "spider_metric",
            archetype: "spider_archetype", visual: "spider_visual", deck: "spider_deck",
            image: "spider_image", sort: "spider_sort",
        };
        for (const [key, param] of Object.entries(mapping)) {
            const value = state[key];
            const isDefault = (key === "type" && value === "all") || (key === "sort" && value === "name-asc") || !value;
            if (isDefault) url.searchParams.delete(param);
            else url.searchParams.set(param, value);
        }
        const q = search?.value?.trim() || "";
        if (q) url.searchParams.set("q", q);
        else url.searchParams.delete("q");
        history.replaceState(null, "", url);
    };

    const matches = (card, ignoreType = false) => {
        const meta = card.meta;
        const q = normalize(search?.value || "");
        if (q && !normalize(card.name).includes(q)) return false;
        if (!ignoreType && state.type !== "all" && !(meta.type_keys || []).includes(state.type)) return false;
        if (state.zone && meta.zone !== state.zone) return false;
        if (state.subtype && meta.spelltrap_subtype !== state.subtype) return false;
        if (state.attribute && meta.attribute !== state.attribute) return false;
        if (state.race && meta.race !== state.race) return false;
        if (state.metric && metricKey(meta) !== state.metric) return false;
        if (state.archetype && meta.archetype !== state.archetype) return false;
        if (state.visual && meta.visual_family !== state.visual) return false;
        if (state.deck && !(meta.deck_tags || []).includes(state.deck)) return false;
        if (state.image === "yes" && !meta.has_image) return false;
        if (state.image === "no" && meta.has_image) return false;
        return true;
    };

    const sortValue = (card) => {
        const meta = card.meta;
        switch (state.sort) {
            case "type": return `${primaryType(meta)} ${normalize(card.name)}`;
            case "metric-asc": return String((meta.metric?.value ?? 999)).padStart(3, "0") + " " + normalize(card.name);
            case "metric-desc": return String(999 - (meta.metric?.value ?? -1)).padStart(3, "0") + " " + normalize(card.name);
            case "attribute": return `${normalize(meta.attribute_label)} ${normalize(card.name)}`;
            case "archetype": return `${normalize(meta.archetype)} ${normalize(card.name)}`;
            case "name-desc": return normalize(card.name);
            default: return normalize(card.name);
        }
    };

    const applySort = () => {
        const ordered = [...cards].sort((a, b) => {
            if (state.sort === "name-desc") return sortValue(b).localeCompare(sortValue(a), "fr");
            return sortValue(a).localeCompare(sortValue(b), "fr", {numeric: true});
        });
        for (const card of ordered) {
            gallery.appendChild(card.gallery);
            list.appendChild(card.list);
        }
    };

    const updateTypeCounts = () => {
        for (const button of typeButtons) {
            const type = button.dataset.spiderType || "all";
            const number = cards.filter((card) => {
                if (!matches(card, true)) return false;
                return type === "all" || (card.meta.type_keys || []).includes(type);
            }).length;
            const box = button.querySelector("span");
            if (box) box.textContent = number;
        }
    };

    const labelForState = (key, value) => {
        if (!value) return "";
        if (key === "type") return TYPE_LABELS[value] || value;
        const select = selectors[key];
        if (!select) return value;
        const option = [...select.options].find((item) => item.value === value);
        return option ? option.textContent.replace(/\s+\(\d+\)$/, "") : value;
    };

    const renderActiveFilters = () => {
        if (!activeBox) return;
        activeBox.innerHTML = "";
        const fields = ["type", "zone", "subtype", "attribute", "race", "metric", "archetype", "visual", "deck", "image"];
        for (const key of fields) {
            const value = state[key];
            if (!value || (key === "type" && value === "all")) continue;
            const chip = document.createElement("span");
            chip.className = "spider-active-filter";
            chip.textContent = labelForState(key, value);
            activeBox.appendChild(chip);
        }
        const q = search?.value?.trim();
        if (q) {
            const chip = document.createElement("span");
            chip.className = "spider-active-filter";
            chip.textContent = `Recherche : ${q}`;
            activeBox.appendChild(chip);
        }
    };

    const apply = () => {
        let visible = 0;
        for (const card of cards) {
            const show = matches(card);
            card.gallery.hidden = !show;
            card.list.hidden = !show;
            if (show) visible += 1;
        }
        applySort();
        updateTypeCounts();
        renderActiveFilters();
        typeButtons.forEach((button) => button.classList.toggle("is-active", (button.dataset.spiderType || "all") === state.type));
        if (countBox) countBox.textContent = `${visible} carte${visible > 1 ? "s" : ""} affichée${visible > 1 ? "s" : ""}`;
        if (emptyBox) emptyBox.hidden = visible !== 0;
        writeUrlState();
    };

    const hydrate = (payload) => {
        const metadata = new Map((payload.cards || []).map((card) => [normalize(card.name), card]));
        cards.length = 0;
        for (const [name, galleryEntry] of galleryByName.entries()) {
            const listEntry = listByName.get(name);
            if (!listEntry) continue;
            const meta = metadata.get(name) || {
                name: galleryEntry.dataset.cardName,
                metadata_ok: false,
                type_keys: [], zone: "unknown", deck_tags: [], has_image: !!galleryEntry.querySelector("img"),
            };
            const card = {name: galleryEntry.dataset.cardName || meta.name, gallery: galleryEntry, list: listEntry, meta};
            cards.push(card);
            decorateCard(galleryEntry, meta);
        }

        appendOptions(selectors.subtype, payload.filters?.spelltrap_subtype);
        appendOptions(selectors.attribute, payload.filters?.attribute);
        appendOptions(selectors.race, payload.filters?.race);
        appendOptions(selectors.metric, payload.filters?.metric);
        appendOptions(selectors.archetype, payload.filters?.archetype);
        appendOptions(selectors.visual, payload.filters?.visual_family);
        appendOptions(selectors.deck, payload.filters?.deck_tag);

        readUrlState();
        for (const key of ["zone", "subtype", "attribute", "race", "metric", "archetype", "visual", "deck", "image", "sort"]) {
            if (selectors[key] && [...selectors[key].options].some((option) => option.value === state[key])) selectors[key].value = state[key];
        }
        if (!typeButtons.some((button) => button.dataset.spiderType === state.type)) state.type = "all";
        if (statusBox) {
            const missing = Number(payload.missing_metadata_count || 0);
            statusBox.textContent = missing
                ? `${payload.metadata_count || 0}/${payload.pool_count || cards.length} cartes classées automatiquement · ${missing} à compléter`
                : `${payload.pool_count || cards.length} cartes classées · filtres combinables`;
        }
        apply();
    };

    typeButtons.forEach((button) => button.addEventListener("click", () => {
        state.type = button.dataset.spiderType || "all";
        apply();
    }));

    for (const key of ["zone", "subtype", "attribute", "race", "metric", "archetype", "visual", "deck", "image", "sort"]) {
        selectors[key]?.addEventListener("change", () => {
            state[key] = selectors[key].value;
            apply();
        });
    }

    search?.addEventListener("input", apply);
    resetButton?.addEventListener("click", () => {
        Object.assign(state, {
            type: "all", zone: "", subtype: "", attribute: "", race: "", metric: "",
            archetype: "", visual: "", deck: "", image: "", sort: "name-asc",
        });
        if (search) search.value = "";
        for (const key of ["zone", "subtype", "attribute", "race", "metric", "archetype", "visual", "deck", "image", "sort"]) {
            if (selectors[key]) selectors[key].value = state[key];
        }
        apply();
    });

    fetch("/static/araignee/araignee_catalog.json", {cache: "no-cache"})
        .then((response) => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then(hydrate)
        .catch((error) => {
            if (statusBox) statusBox.textContent = "Catalogue détaillé indisponible — recherche simple conservée.";
            console.warn("Catalogue Araignée non chargé", error);
        });
})();
