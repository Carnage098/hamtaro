(() => {
    "use strict";

    const normalise = (value) => (
        String(value || "")
            .toLocaleLowerCase("fr")
            .normalize("NFD")
            .replace(/\p{Diacritic}/gu, "")
            .trim()
    );

    let toastTimeout = null;
    const showToast = (message) => {
        let toast = document.querySelector("[data-hx-toast]");
        if (!toast) {
            toast = document.createElement("div");
            toast.className = "hx-toast";
            toast.dataset.hxToast = "";
            toast.setAttribute("role", "status");
            toast.setAttribute("aria-live", "polite");
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add("is-visible");
        window.clearTimeout(toastTimeout);
        toastTimeout = window.setTimeout(() => {
            toast.classList.remove("is-visible");
        }, 2600);
    };

    const absoluteUrl = (value) => {
        try {
            return new URL(value || window.location.href, window.location.origin).href;
        } catch {
            return window.location.href;
        }
    };

    const share = async ({url, title, text} = {}) => {
        const targetUrl = absoluteUrl(url);
        const payload = {
            title: title || document.title,
            text: text || "Découvre cette page sur Hamtaro.",
            url: targetUrl,
        };
        if (navigator.share) {
            try {
                await navigator.share(payload);
                return;
            } catch (error) {
                if (error && error.name === "AbortError") {
                    return;
                }
            }
        }
        try {
            await navigator.clipboard.writeText(targetUrl);
            showToast("Lien copié dans le presse-papiers.");
        } catch {
            window.prompt("Copie ce lien :", targetUrl);
        }
    };

    document.querySelectorAll("[data-share-page]").forEach((button) => {
        button.addEventListener("click", () => share());
    });

    document.querySelectorAll("[data-share-url]").forEach((button) => {
        button.addEventListener("click", () => {
            share({
                url: button.dataset.shareUrl,
                title: button.dataset.shareTitle,
            });
        });
    });

    document.querySelectorAll("[data-copy-text]").forEach((button) => {
        button.addEventListener("click", async () => {
            const text = button.dataset.copyText || "";
            try {
                await navigator.clipboard.writeText(text);
                showToast(`Copié : ${text}`);
            } catch {
                window.prompt("Copie cette référence :", text);
            }
        });
    });

    const mobileButton = document.querySelector(
        "[data-mobile-menu-toggle]"
    );
    const mobileLinks = document.querySelector(
        "[data-mobile-navigation-links]"
    );
    if (mobileButton && mobileLinks) {
        mobileButton.addEventListener("click", () => {
            const open = mobileLinks.classList.toggle("is-open");
            mobileButton.setAttribute("aria-expanded", String(open));
            mobileButton.setAttribute(
                "aria-label",
                open ? "Fermer le menu" : "Ouvrir le menu"
            );
        });
    }

    const floatingShare = document.querySelector("[data-site-share]");
    if (floatingShare) {
        floatingShare.addEventListener("click", () => share());
    }

    // Une commande ouverte depuis la recherche globale est directement
    // injectée dans le champ du guide existant.
    const guideSearch = document.querySelector("[data-command-search]");
    const requestedGuideSearch = new URL(window.location.href)
        .searchParams
        .get("search");
    if (guideSearch && requestedGuideSearch) {
        guideSearch.value = requestedGuideSearch;
        guideSearch.dispatchEvent(new Event("input", {bubbles: true}));
        guideSearch.scrollIntoView({behavior: "smooth", block: "center"});
    }

    // ----------------------------------------------------------
    // Page des matchs
    // ----------------------------------------------------------
    const matchPage = document.querySelector("[data-live-matches-page]");
    if (matchPage) {
        const cards = Array.from(
            document.querySelectorAll("[data-live-match]")
        );
        const sections = Array.from(
            document.querySelectorAll("[data-match-section]")
        );
        const searchInput = document.querySelector("[data-match-search]");
        const stageSelect = document.querySelector(
            "[data-match-stage-filter]"
        );
        const formatSelect = document.querySelector(
            "[data-match-format-filter]"
        );
        const tournamentSelect = document.querySelector(
            "[data-match-tournament-filter]"
        );
        const typeSelect = document.querySelector(
            "[data-match-type-filter]"
        );
        const resetButton = document.querySelector(
            "[data-match-filter-reset]"
        );
        const emptyState = document.querySelector(
            "[data-match-filter-empty]"
        );

        const refreshFilters = () => {
            const query = normalise(searchInput ? searchInput.value : "");
            const stage = stageSelect ? stageSelect.value : "all";
            const formatName = formatSelect ? formatSelect.value : "all";
            const tournament = (
                tournamentSelect ? tournamentSelect.value : "all"
            );
            const matchType = typeSelect ? typeSelect.value : "all";
            let totalVisible = 0;

            cards.forEach((card) => {
                const visible = (
                    (!query || normalise(
                        card.dataset.matchSearchText
                    ).includes(query))
                    && (stage === "all"
                        || card.dataset.matchStage === stage)
                    && (formatName === "all"
                        || card.dataset.matchFormat === formatName)
                    && (tournament === "all"
                        || card.dataset.matchTournament === tournament)
                    && (matchType === "all"
                        || card.dataset.matchType === matchType)
                );
                card.hidden = !visible;
                if (visible) {
                    totalVisible += 1;
                }
            });

            sections.forEach((section) => {
                const visibleCards = Array.from(
                    section.querySelectorAll("[data-live-match]")
                ).filter((card) => !card.hidden);
                section.hidden = (
                    stage !== "all"
                    && section.dataset.matchSection !== stage
                ) || visibleCards.length === 0;

                const count = section.querySelector("[data-section-count]");
                if (count) {
                    count.textContent = String(visibleCards.length);
                }
            });

            if (emptyState) {
                emptyState.hidden = totalVisible !== 0;
            }
        };

        [searchInput, stageSelect, formatSelect, tournamentSelect, typeSelect]
            .filter(Boolean)
            .forEach((input) => {
                input.addEventListener(
                    input.tagName === "INPUT" ? "input" : "change",
                    refreshFilters
                );
            });

        if (resetButton) {
            resetButton.addEventListener("click", () => {
                if (searchInput) searchInput.value = "";
                [stageSelect, formatSelect, tournamentSelect, typeSelect]
                    .filter(Boolean)
                    .forEach((select) => {
                        select.value = "all";
                    });
                refreshFilters();
            });
        }
        refreshFilters();

        const initialSignature = cards
            .map((card) => [
                card.dataset.matchType,
                card.querySelector("code")?.textContent || "",
                card.dataset.matchStage,
            ].join(":"))
            .sort()
            .join("|");

        let checking = false;
        const checkUpdates = async () => {
            if (checking || document.hidden) return;
            checking = true;
            try {
                const response = await fetch("/api/matches/live", {
                    cache: "no-store",
                    headers: {"Accept": "application/json"},
                });
                if (!response.ok) return;
                const data = await response.json();
                const nextSignature = (data.all || [])
                    .map((item) => [
                        item.match_type,
                        item.reference,
                        item.stage,
                    ].join(":"))
                    .sort()
                    .join("|");
                if (nextSignature !== initialSignature) {
                    window.location.reload();
                }
            } catch (error) {
                console.debug(
                    "Actualisation des matchs indisponible.",
                    error
                );
            } finally {
                checking = false;
            }
        };
        window.setInterval(checkUpdates, 20_000);
        window.addEventListener("focus", checkUpdates);
    }

    // ----------------------------------------------------------
    // Recherche locale des decks
    // ----------------------------------------------------------
    const deckSearch = document.querySelector("[data-deck-search]");
    const deckCards = Array.from(
        document.querySelectorAll("[data-deck-card]")
    );
    if (deckSearch && deckCards.length) {
        const count = document.querySelector("[data-deck-visible-count]");
        const empty = document.querySelector("[data-deck-search-empty]");
        const refreshDecks = () => {
            const query = normalise(deckSearch.value);
            let visible = 0;
            deckCards.forEach((card) => {
                const matches = (
                    !query
                    || normalise(card.dataset.deckSearchText).includes(query)
                );
                card.hidden = !matches;
                if (matches) visible += 1;
            });
            if (count) count.textContent = String(visible);
            if (empty) empty.hidden = visible !== 0;
        };
        deckSearch.addEventListener("input", refreshDecks);
        refreshDecks();
    }

    // ----------------------------------------------------------
    // Courbe ELO sans dépendance externe
    // ----------------------------------------------------------
    const chart = document.querySelector("[data-rating-chart]");
    if (chart) {
        const script = chart.querySelector('script[type="application/json"]');
        const svg = chart.querySelector("svg");
        const empty = chart.querySelector("[data-chart-empty]");
        let rows = [];
        try {
            rows = JSON.parse(script ? script.textContent : "[]");
        } catch {
            rows = [];
        }
        rows = rows.filter((row) => Number.isFinite(Number(row.new_rating)));
        if (!svg || rows.length < 2) {
            if (svg) svg.hidden = true;
            if (empty) empty.hidden = false;
        } else {
            const width = 800;
            const height = 260;
            const padding = 30;
            const values = rows.map((row) => Number(row.new_rating));
            let minimum = Math.min(...values);
            let maximum = Math.max(...values);
            if (minimum === maximum) {
                minimum -= 25;
                maximum += 25;
            }
            const x = (index) => (
                padding
                + (index / Math.max(1, rows.length - 1))
                * (width - padding * 2)
            );
            const y = (value) => (
                height - padding
                - ((value - minimum) / (maximum - minimum))
                * (height - padding * 2)
            );
            const points = values.map(
                (value, index) => `${x(index)},${y(value)}`
            ).join(" ");

            const namespace = "http://www.w3.org/2000/svg";
            [0, 1, 2, 3, 4].forEach((step) => {
                const line = document.createElementNS(namespace, "line");
                const lineY = padding + (
                    step / 4
                ) * (height - padding * 2);
                line.setAttribute("x1", String(padding));
                line.setAttribute("x2", String(width - padding));
                line.setAttribute("y1", String(lineY));
                line.setAttribute("y2", String(lineY));
                line.setAttribute("class", "hx-chart-grid");
                svg.appendChild(line);
            });

            const area = document.createElementNS(namespace, "polygon");
            area.setAttribute(
                "points",
                `${padding},${height - padding} ${points} `
                + `${width - padding},${height - padding}`
            );
            area.setAttribute("class", "hx-chart-area");
            svg.appendChild(area);

            const polyline = document.createElementNS(
                namespace,
                "polyline"
            );
            polyline.setAttribute("points", points);
            polyline.setAttribute("class", "hx-chart-line");
            svg.appendChild(polyline);

            values.forEach((value, index) => {
                const point = document.createElementNS(namespace, "circle");
                point.setAttribute("cx", String(x(index)));
                point.setAttribute("cy", String(y(value)));
                point.setAttribute("r", "6");
                point.setAttribute("class", "hx-chart-point");
                const title = document.createElementNS(namespace, "title");
                title.textContent = `${value} ELO`;
                point.appendChild(title);
                svg.appendChild(point);
            });
        }
    }
})();
