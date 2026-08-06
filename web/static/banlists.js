(() => {
    "use strict";

    const page = document.querySelector("[data-banlists-page]");
    if (!page) {
        return;
    }

    const cards = Array.from(document.querySelectorAll("[data-banlist-card]"));
    const categorySections = Array.from(document.querySelectorAll("[data-banlist-category]"));
    const search = document.querySelector("[data-banlist-search]");
    const toolbar = document.querySelector("[data-banlist-toolbar]");
    const filters = Array.from(document.querySelectorAll("[data-banlist-filter]"));
    const shortcuts = Array.from(document.querySelectorAll("[data-banlist-category-shortcut]"));
    const results = document.querySelector("[data-banlist-results]");
    const empty = document.querySelector("[data-banlist-empty]");
    const liveStatus = document.querySelector("[data-banlist-live-status]");
    let activeFamily = "all";
    let currentRevision = page.dataset.banlistRevision || "local";

    const normalize = (value) => String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .trim();

    const pluralizeFormats = (count) => (
        `${count} format${count > 1 ? "s" : ""}`
    );

    const refresh = () => {
        const query = normalize(search ? search.value : "");
        let totalVisible = 0;
        let visibleCategories = 0;

        cards.forEach((card) => {
            const family = card.dataset.family || "other";
            const searchable = normalize(card.dataset.search || card.textContent);
            const familyMatches = activeFamily === "all" || family === activeFamily;
            const queryMatches = !query || searchable.includes(query);
            const show = familyMatches && queryMatches;
            card.hidden = !show;
            if (show) {
                totalVisible += 1;
            }
        });

        categorySections.forEach((section) => {
            const family = section.dataset.banlistCategory || "other";
            const sectionCards = Array.from(section.querySelectorAll("[data-banlist-card]"));
            const visibleCount = sectionCards.filter((card) => !card.hidden).length;
            const categoryAllowed = activeFamily === "all" || family === activeFamily;
            const showSection = categoryAllowed && visibleCount > 0;
            section.hidden = !showSection;

            const count = section.querySelector("[data-category-visible-count]");
            if (count) {
                count.textContent = pluralizeFormats(visibleCount);
            }
            if (showSection) {
                visibleCategories += 1;
            }
        });

        if (results) {
            results.textContent = (
                `${pluralizeFormats(totalVisible)} affiché${totalVisible > 1 ? "s" : ""} `
                + `dans ${visibleCategories} catégorie${visibleCategories > 1 ? "s" : ""}.`
            );
        }
        if (empty) {
            empty.hidden = totalVisible !== 0;
        }
    };

    const chooseFamily = (family, shouldScroll = false) => {
        activeFamily = family || "all";
        filters.forEach((item) => {
            item.classList.toggle(
                "is-active",
                (item.dataset.banlistFilter || "all") === activeFamily,
            );
        });
        refresh();

        if (!shouldScroll) {
            return;
        }
        const target = activeFamily === "all"
            ? toolbar
            : document.querySelector(`[data-banlist-category="${activeFamily}"]`);
        if (target) {
            window.requestAnimationFrame(() => {
                target.scrollIntoView({behavior: "smooth", block: "start"});
            });
        }
    };

    filters.forEach((button) => {
        button.addEventListener("click", () => {
            chooseFamily(button.dataset.banlistFilter || "all");
        });
    });

    shortcuts.forEach((button) => {
        button.addEventListener("click", () => {
            chooseFamily(button.dataset.banlistCategoryShortcut || "all", true);
        });
    });

    if (search) {
        search.addEventListener("input", refresh);
    }

    const statusLabels = {
        Banned: "Interdites",
        Forbidden: "Interdites",
        Limited: "Limitées",
        "Semi-Limited": "Semi-limitées",
    };

    const statusOrder = ["Banned", "Forbidden", "Limited", "Semi-Limited"];
    const providerCache = new Map();

    const createSection = (label, names) => {
        const section = document.createElement("section");
        section.className = "banlist-section";

        const title = document.createElement("div");
        title.className = "banlist-section-title";
        const heading = document.createElement("h3");
        heading.textContent = label;
        const count = document.createElement("span");
        count.textContent = String(names.length);
        title.append(heading, count);

        const list = document.createElement("ul");
        names.forEach((name) => {
            const item = document.createElement("li");
            const text = document.createElement("span");
            text.textContent = name;
            item.append(text);
            list.append(item);
        });

        section.append(title, list);
        return section;
    };

    const loadYgoprodeck = async (card) => {
        const banlist = card.dataset.providerBanlist;
        const field = card.dataset.providerField;
        const status = card.querySelector("[data-provider-status]");
        const output = card.querySelector("[data-provider-output]");
        const fallback = card.querySelector(".banlist-columns-static");
        if (!banlist || !field || !status || !output) {
            return;
        }

        const endpoint = `https://db.ygoprodeck.com/api/v7/cardinfo.php?banlist=${encodeURIComponent(banlist)}`;
        try {
            let promise = providerCache.get(endpoint);
            if (!promise) {
                promise = fetch(endpoint, {headers: {Accept: "application/json"}})
                    .then((response) => {
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}`);
                        }
                        return response.json();
                    });
                providerCache.set(endpoint, promise);
            }

            const payload = await promise;
            const groups = new Map();
            statusOrder.forEach((key) => groups.set(key, []));

            (payload.data || []).forEach((entry) => {
                const current = entry.banlist_info && entry.banlist_info[field];
                if (!current) {
                    return;
                }
                if (!groups.has(current)) {
                    groups.set(current, []);
                }
                groups.get(current).push(entry.name);
            });

            output.replaceChildren();
            statusOrder.forEach((key) => {
                const names = (groups.get(key) || []).sort((a, b) => a.localeCompare(b, "fr"));
                if (names.length) {
                    output.append(createSection(statusLabels[key] || key, names));
                }
            });

            const total = Array.from(groups.values()).reduce((sum, entries) => sum + entries.length, 0);
            status.textContent = `${total} cartes chargées automatiquement depuis la base YGOPRODeck.`;
            status.classList.add("is-ready");
            output.hidden = false;
            if (fallback) {
                fallback.hidden = true;
            }
            card.dataset.search += ` ${output.textContent}`;
            refresh();
        } catch (error) {
            status.textContent = "La liste automatique est momentanément indisponible. Utilise le bouton de source officielle ci-dessous.";
            status.classList.add("is-error");
            console.debug("Chargement de banlist impossible", error);
        }
    };

    cards
        .filter((card) => card.dataset.provider === "ygoprodeck")
        .forEach(loadYgoprodeck);

    const parameters = new URLSearchParams(window.location.search);
    const requestedCategory = parameters.get("category");
    const requestedFormat = parameters.get("format");

    if (requestedCategory) {
        chooseFamily(requestedCategory, true);
    } else {
        refresh();
    }

    if (requestedFormat) {
        const target = document.getElementById(requestedFormat);
        if (target) {
            const family = target.dataset.family || "all";
            chooseFamily(family);
            window.requestAnimationFrame(() => {
                target.scrollIntoView({behavior: "smooth", block: "start"});
            });
        }
    }

    // Restaure la recherche et la catégorie après un rechargement automatique.
    try {
        const savedState = JSON.parse(
            window.sessionStorage.getItem("hamtaro-banlists-state") || "null",
        );
        window.sessionStorage.removeItem("hamtaro-banlists-state");
        if (savedState && !requestedCategory && !requestedFormat) {
            if (search && typeof savedState.query === "string") {
                search.value = savedState.query;
            }
            chooseFamily(savedState.family || "all");
            window.requestAnimationFrame(() => {
                window.scrollTo({
                    top: Number(savedState.scrollY || 0),
                    behavior: "auto",
                });
            });
        }
    } catch (error) {
        console.debug("État précédent des banlists illisible.", error);
    }

    const savePageState = () => {
        try {
            window.sessionStorage.setItem(
                "hamtaro-banlists-state",
                JSON.stringify({
                    family: activeFamily,
                    query: search ? search.value : "",
                    scrollY: window.scrollY,
                }),
            );
        } catch (error) {
            console.debug("Impossible de mémoriser l’état de la page.", error);
        }
    };

    let versionCheckInProgress = false;
    const checkForServerUpdate = async () => {
        if (versionCheckInProgress || document.hidden) {
            return;
        }
        versionCheckInProgress = true;
        try {
            const response = await fetch(
                `/api/banlists/version.json?refresh=${Date.now()}`,
                {
                    cache: "no-store",
                    headers: {Accept: "application/json"},
                },
            );
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            if (liveStatus) {
                liveStatus.textContent = payload.sync_in_progress
                    ? "Une synchronisation serveur est en cours…"
                    : "Dernière vérification automatique effectuée.";
            }
            const nextRevision = String(payload.revision || "");
            if (
                nextRevision
                && nextRevision !== "local"
                && nextRevision !== currentRevision
            ) {
                if (liveStatus) {
                    liveStatus.textContent = "Nouvelle banlist détectée : actualisation de la page…";
                }
                savePageState();
                window.location.reload();
                return;
            }
            currentRevision = nextRevision || currentRevision;
        } catch (error) {
            if (liveStatus) {
                liveStatus.textContent = "La vérification automatique sera réessayée dans une minute.";
            }
            console.debug("Vérification des banlists indisponible.", error);
        } finally {
            versionCheckInProgress = false;
        }
    };

    window.setInterval(checkForServerUpdate, 60_000);
    window.setTimeout(checkForServerUpdate, 5_000);
    window.addEventListener("focus", checkForServerUpdate);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            checkForServerUpdate();
        }
    });
})();
