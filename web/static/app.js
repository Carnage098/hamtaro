(() => {
    "use strict";

    const frame = document.querySelector("[data-tournament-id]");
    const image = document.querySelector("[data-bracket-image]");

    if (!frame || !image) {
        return;
    }

    const tournamentId = frame.dataset.tournamentId;
    let currentVersion = frame.dataset.bracketVersion || "";
    const refreshBracket = async () => {
        try {
            const response = await fetch(
                `/api/tournaments/${tournamentId}/version.json`,
                {
                    cache: "no-store",
                    headers: {
                        "Accept": "application/json",
                    },
                }
            );

            if (!response.ok) {
                return;
            }
            const data = await response.json();
            const version = String(data.version || "");

            if (!version || version === currentVersion) {
                return;
            }
            currentVersion = version;
            frame.dataset.bracketVersion = version;
            image.src = (
                `/api/tournaments/${tournamentId}/bracket.png`
                + `?v=${encodeURIComponent(version)}`
            );
        } catch (error) {
            console.debug("Actualisation du bracket indisponible.", error);
        }
    };

    window.setInterval(refreshBracket, 30_000);
})();
(() => {
    "use strict";
    const tabs = Array.from(
        document.querySelectorAll("[data-profile-tab]")
    );
    const panels = Array.from(
        document.querySelectorAll("[data-profile-panel]")
    );

    if (!tabs.length || !panels.length) {
        return;
    }
    const activate = (name) => {
        tabs.forEach((tab) => {
            const selected = tab.dataset.profileTab === name;
            tab.classList.toggle("is-active", selected);
            tab.setAttribute("aria-selected", String(selected));
        });

        panels.forEach((panel) => {
            const selected = panel.dataset.profilePanel === name;
            panel.classList.toggle("is-active", selected);
            panel.hidden = !selected;
        });
        const url = new URL(window.location.href);
        url.searchParams.set("section", name);
        window.history.replaceState({}, "", url);
    };

    tabs.forEach((tab) => {
        tab.addEventListener("click", () => {
            activate(tab.dataset.profileTab || "overview");
        });
    });

    const requested = new URL(window.location.href)
        .searchParams
        .get("section");
    if (requested && tabs.some(
        (tab) => tab.dataset.profileTab === requested
    )) {
        activate(requested);
    }
})();
(() => {
    "use strict";

    const guide = document.querySelector("[data-command-guide]");
    if (!guide) {
        return;
    }

    const searchInput = guide.querySelector("[data-command-search]");
    const roleButtons = Array.from(
        guide.querySelectorAll("[data-command-role-filter]")
    );
    const categoryButtons = Array.from(
        guide.querySelectorAll("[data-command-category-filter]")
    );
    const commandCards = Array.from(
        guide.querySelectorAll("[data-guide-command]")
    );
    const categorySections = Array.from(
        guide.querySelectorAll("[data-guide-category-section]")
    );
    const emptyState = guide.querySelector("[data-command-empty]");
    const visibleCounter = guide.querySelector("[data-command-visible-count]");
    const resetButton = guide.querySelector("[data-command-reset]");
    const copyButtons = Array.from(
        guide.querySelectorAll("[data-copy-command]")
    );

    if (!searchInput || !commandCards.length) {
        return;
    }

    let activeRole = "all";
    let activeCategory = "all";

    const normalise = (value) => (
        String(value || "")
            .toLocaleLowerCase("fr")
            .normalize("NFD")
            .replace(/\p{Diacritic}/gu, "")
            .trim()
    );

    const updateButtonState = (buttons, attribute, activeValue) => {
        buttons.forEach((button) => {
            const selected = button.dataset[attribute] === activeValue;
            button.classList.toggle("is-active", selected);
            button.setAttribute("aria-pressed", String(selected));
        });
    };

    const refresh = () => {
        const query = normalise(searchInput.value);
        let visibleCount = 0;

        commandCards.forEach((card) => {
            const role = card.dataset.commandRole || "community";
            const category = card.dataset.commandCategory || "other";
            const searchable = normalise(card.dataset.commandSearchText);

            const roleMatches = activeRole === "all" || role === activeRole;
            const categoryMatches = (
                activeCategory === "all"
                || category === activeCategory
            );
            const searchMatches = !query || searchable.includes(query);
            const visible = roleMatches && categoryMatches && searchMatches;

            card.hidden = !visible;
            if (visible) {
                visibleCount += 1;
            }
        });

        categorySections.forEach((section) => {
            const visibleCards = Array.from(
                section.querySelectorAll("[data-guide-command]")
            ).filter((card) => !card.hidden);

            section.hidden = visibleCards.length === 0;

            const count = section.querySelector("[data-category-visible-count]");
            if (count) {
                count.textContent = String(visibleCards.length);
            }

            const details = section.querySelector("details");
            if (details && (query || activeCategory !== "all")) {
                details.open = true;
            }
        });

        if (visibleCounter) {
            visibleCounter.textContent = String(visibleCount);
        }
        if (emptyState) {
            emptyState.hidden = visibleCount !== 0;
        }
    };

    roleButtons.forEach((button) => {
        button.addEventListener("click", () => {
            activeRole = button.dataset.commandRoleFilter || "all";
            updateButtonState(
                roleButtons,
                "commandRoleFilter",
                activeRole
            );
            refresh();
        });
    });

    categoryButtons.forEach((button) => {
        button.addEventListener("click", () => {
            activeCategory = button.dataset.commandCategoryFilter || "all";
            updateButtonState(
                categoryButtons,
                "commandCategoryFilter",
                activeCategory
            );
            refresh();
        });
    });

    copyButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            const value = button.dataset.copyCommand || "";
            if (!value) {
                return;
            }

            try {
                await navigator.clipboard.writeText(value);
                const original = button.textContent;
                button.textContent = "Copié !";
                window.setTimeout(() => {
                    button.textContent = original;
                }, 1200);
            } catch (error) {
                console.debug("Copie de la commande impossible.", error);
            }
        });
    });

    resetButton?.addEventListener("click", () => {
        searchInput.value = "";
        activeRole = "all";
        activeCategory = "all";
        updateButtonState(roleButtons, "commandRoleFilter", activeRole);
        updateButtonState(
            categoryButtons,
            "commandCategoryFilter",
            activeCategory
        );
        refresh();
        searchInput.focus();
    });

    searchInput.addEventListener("input", refresh);
    refresh();
})();
(() => {
    "use strict";
    const searchInput = document.querySelector(
        "[data-participant-search]"
    );
    const filterButtons = Array.from(
        document.querySelectorAll(
            "[data-participant-filter]"
        )
    );
    const cards = Array.from(
        document.querySelectorAll(
            "[data-participant-card]"
        )
    );
    const sections = Array.from(
        document.querySelectorAll(
            "[data-participant-section]"
        )
    );
    const emptyState = document.querySelector(
        "[data-participant-empty]"
    );
    if (!searchInput) {
        return;
    }

    let activeFilter = "all";

    const normalise = (value) => (
        String(value || "")
            .toLocaleLowerCase("fr")
            .normalize("NFD")
            .replace(/\p{Diacritic}/gu, "")
            .trim()
    );

    const refresh = () => {
        const query = normalise(searchInput.value);
        let visibleCards = 0;
        cards.forEach((card) => {
            const searchable = normalise(
                card.dataset.participantSearch
            );
            const kind = (
                card.dataset.participantKind
                || "all"
            );

            const searchMatches = (
                !query
                || searchable.includes(query)
            );

            const filterMatches = (
                activeFilter === "all"
                || kind === "regular"
            );
            const section = card.closest(
                "[data-participant-section]"
            );
            const sectionName = section
                ? section.dataset.participantSection
                : "all";

            const sectionMatches = (
                activeFilter === "all"
                ? sectionName === "all"
                : sectionName === "regular"
            );
            const visible = (
                searchMatches
                && filterMatches
                && sectionMatches
            );

            card.hidden = !visible;

            if (visible) {
                visibleCards += 1;
            }
        });

        sections.forEach((section) => {
            const sectionName = (
                section.dataset.participantSection
                || "all"
            );
            section.hidden = (
                activeFilter === "all"
                ? sectionName !== "all"
                : sectionName !== "regular"
            );
        });

        if (emptyState) {
            emptyState.hidden = (
                visibleCards !== 0
                || !cards.length
            );
        }
    };
    filterButtons.forEach((button) => {
        button.addEventListener("click", () => {
            activeFilter = (
                button.dataset.participantFilter
                || "all"
            );

            filterButtons.forEach((other) => {
                other.classList.toggle(
                    "is-active",
                    other === button
                );
            });

            refresh();
        });
    });
    searchInput.addEventListener("input", refresh);
    refresh();
})();

// Actualisation automatique de la liste générale des tournois.
(() => {
    "use strict";

    const page = document.querySelector("[data-tournaments-page]");

    if (!page) {
        return;
    }

    const selectors = [
        '[data-tournament-list="open"]',
        '[data-tournament-list="current"]',
        '[data-tournament-list="archives"]',
    ];

    let refreshInProgress = false;

    const refreshTournamentLists = async () => {
        if (refreshInProgress || document.hidden) {
            return;
        }

        refreshInProgress = true;

        try {
            const url = new URL("/tournaments", window.location.origin);
            url.searchParams.set("refresh", Date.now().toString());

            const response = await fetch(url, {
                cache: "no-store",
                headers: {
                    "Accept": "text/html",
                    "X-Requested-With": "fetch",
                },
            });

            if (!response.ok) {
                return;
            }

            const html = await response.text();
            const nextDocument = new DOMParser().parseFromString(
                html,
                "text/html"
            );

            selectors.forEach((selector) => {
                const currentList = document.querySelector(selector);
                const nextList = nextDocument.querySelector(selector);

                if (!currentList || !nextList) {
                    return;
                }

                if (currentList.innerHTML !== nextList.innerHTML) {
                    currentList.innerHTML = nextList.innerHTML;
                }
            });
        } catch (error) {
            console.debug(
                "Actualisation des tournois indisponible.",
                error
            );
        } finally {
            refreshInProgress = false;
        }
    };

    window.setInterval(refreshTournamentLists, 15_000);
    window.addEventListener("focus", refreshTournamentLists);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            refreshTournamentLists();
        }
    });

    refreshTournamentLists();
})();
