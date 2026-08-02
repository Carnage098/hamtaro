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
