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
