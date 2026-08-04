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
    const searchInput = document.querySelector(
        "[data-command-search]"
    );
    const filterButtons = Array.from(
        document.querySelectorAll("[data-command-filter]")
    );
    const commandCards = Array.from(
        document.querySelectorAll("[data-guide-command]")
    );
    const emptyState = document.querySelector(
        "[data-command-empty]"
    );

    if (!searchInput || !commandCards.length) {
        return;
    }

    let activeRole = "all";
    const normalise = (value) => (
        String(value || "")
            .toLocaleLowerCase("fr")
            .normalize("NFD")
            .replace(/\p{Diacritic}/gu, "")
            .trim()
    );

    const refresh = () => {
        const query = normalise(searchInput.value);
        let visibleCount = 0;
        commandCards.forEach((card) => {
            const role = card.dataset.commandRole || "community";
            const searchable = normalise(
                card.dataset.commandSearchText
            );

            const roleMatches = (
                activeRole === "all"
                || role === activeRole
            );

            const searchMatches = (
                !query
                || searchable.includes(query)
            );
            const visible = roleMatches && searchMatches;
            card.hidden = !visible;

            if (visible) {
                visibleCount += 1;
            }
        });

        if (emptyState) {
            emptyState.hidden = visibleCount !== 0;
        }
    };

    filterButtons.forEach((button) => {
        button.addEventListener("click", () => {
            activeRole = (
                button.dataset.commandFilter
                || "all"
            );
            filterButtons.forEach((otherButton) => {
                otherButton.classList.toggle(
                    "is-active",
                    otherButton === button
                );
            });

            refresh();
        });
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

// Tableau de bord staff : rafraîchissement protégé en arrière-plan.
(() => {
    "use strict";

    const dashboard = document.querySelector("[data-staff-dashboard]");
    if (!dashboard) {
        return;
    }

    const refreshUrl = dashboard.dataset.refreshUrl || "/staff/api/overview";
    const updateLabel = document.querySelector("[data-staff-last-update]");
    let running = false;

    const replaceRows = (selector, rows, emptyMessage, columns) => {
        const body = document.querySelector(selector);
        if (!body) {
            return;
        }
        body.replaceChildren();

        if (!rows.length) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = columns;
            td.textContent = emptyMessage;
            tr.append(td);
            body.append(tr);
            return;
        }

        rows.forEach((row) => {
            const tr = document.createElement("tr");
            row.forEach((value, index) => {
                const td = document.createElement("td");
                if (index === 0) {
                    const code = document.createElement("code");
                    code.textContent = String(value ?? "");
                    td.append(code);
                } else {
                    td.textContent = String(value ?? "");
                }
                tr.append(td);
            });
            body.append(tr);
        });
    };

    const replaceCards = (selector, rows, emptyMessage, builder) => {
        const container = document.querySelector(selector);
        if (!container) {
            return;
        }
        container.replaceChildren();
        if (!rows.length) {
            const p = document.createElement("p");
            p.textContent = emptyMessage;
            container.append(p);
            return;
        }
        rows.forEach((row) => container.append(builder(row)));
    };

    const refresh = async () => {
        if (running || document.hidden) {
            return;
        }
        running = true;
        try {
            const response = await fetch(refreshUrl, {
                cache: "no-store",
                credentials: "same-origin",
                headers: {"Accept": "application/json"},
            });
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            const totals = data.totals || {};
            const statValues = document.querySelectorAll(
                "[data-staff-stats] article strong"
            );
            const ordered = [
                totals.active_tournaments,
                totals.registrations,
                totals.pending_results,
                totals.invalid_matches,
            ];
            statValues.forEach((element, index) => {
                element.textContent = String(ordered[index] ?? 0);
            });

            replaceRows(
                "[data-staff-tournaments]",
                (data.active_tournaments || []).map((item) => [
                    item.code,
                    item.name,
                    item.status,
                    `${item.participant_count || 0}/${item.max_players || 0}`,
                    `${item.current_round || 0}/${item.total_rounds || 0}`,
                ]),
                "Aucun tournoi actif.",
                5
            );
            replaceRows(
                "[data-staff-results]",
                (data.pending_results || []).map((item) => [
                    item.tournament_code,
                    `${item.match_kind}:${item.match_id}`,
                    `${item.player1_score}-${item.player2_score}`,
                    item.status,
                ]),
                "Aucun résultat en attente.",
                4
            );

            replaceCards(
                "[data-staff-invalid]",
                data.invalid_matches || [],
                "Aucune incohérence détectée.",
                (item) => {
                    const article = document.createElement("article");
                    article.className = "professional-issue";
                    const strong = document.createElement("strong");
                    strong.textContent = `${item.tournament_code} · Match #${item.id}`;
                    const span = document.createElement("span");
                    span.textContent = `${item.player1_name || "?"} contre ${item.player2_name || "?"}`;
                    const code = document.createElement("code");
                    code.textContent = String(item.status || "");
                    article.append(strong, span, code);
                    return article;
                }
            );

            replaceCards(
                "[data-staff-audit]",
                data.recent_audit || [],
                "Aucune action enregistrée.",
                (item) => {
                    const article = document.createElement("article");
                    article.className = "professional-audit-entry";
                    const strong = document.createElement("strong");
                    strong.textContent = String(item.action || "Action");
                    const span = document.createElement("span");
                    span.textContent = String(
                        item.actor_name || item.actor_id || "Système"
                    );
                    const time = document.createElement("time");
                    time.textContent = String(item.created_at || "");
                    article.append(strong, span, time);
                    return article;
                }
            );

            if (updateLabel) {
                updateLabel.textContent = `Mis à jour à ${new Date().toLocaleTimeString("fr-FR")}`;
            }
        } catch (error) {
            console.debug("Tableau de bord staff indisponible.", error);
        } finally {
            running = false;
        }
    };

    window.setInterval(refresh, 15_000);
    window.addEventListener("focus", refresh);
})();


// Recherche locale et indication de synchronisation de la page Tournois.
(() => {
    "use strict";

    const search = document.querySelector("[data-tournament-search]");
    if (!search) {
        return;
    }
    const updateLabel = document.querySelector("[data-tournament-last-update]");

    const applyFilter = () => {
        const query = search.value.trim().toLocaleLowerCase("fr-FR");
        document.querySelectorAll("[data-tournament-card]").forEach((card) => {
            const haystack = String(card.dataset.search || "");
            card.hidden = Boolean(query) && !haystack.includes(query);
        });
    };

    search.addEventListener("input", applyFilter);
    const observer = new MutationObserver(() => {
        applyFilter();
        if (updateLabel) {
            updateLabel.textContent = `Mis à jour à ${new Date().toLocaleTimeString("fr-FR")}`;
        }
    });
    document.querySelectorAll("[data-tournament-list]").forEach((list) => {
        observer.observe(list, {childList: true, subtree: true});
    });
})();
