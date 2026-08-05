(() => {
    "use strict";

    const dashboard = document.querySelector("[data-staff-dashboard]");
    if (!dashboard) {
        return;
    }

    const refreshUrl =
        dashboard.dataset.refreshUrl || "/staff/api/overview";

    const configuredSeconds = Number.parseInt(
        dashboard.dataset.refreshSeconds || "15",
        10
    );

    const refreshMilliseconds =
        Math.max(
            5,
            Number.isFinite(configuredSeconds)
                ? configuredSeconds
                : 15
        ) * 1000;

    const updateLabel = document.querySelector(
        "[data-staff-last-update]"
    );
    const liveDot = document.querySelector(
        ".professional-live-dot"
    );

    let running = false;

    const text = (value, fallback = "") =>
        String(value ?? fallback);

    const replaceRows = (
        selector,
        rows,
        emptyMessage,
        columnCount
    ) => {
        const body = document.querySelector(selector);
        if (!body) {
            return;
        }

        body.replaceChildren();

        if (!rows.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = columnCount;
            cell.textContent = emptyMessage;
            row.append(cell);
            body.append(row);
            return;
        }

        rows.forEach((values) => {
            const row = document.createElement("tr");

            values.forEach((value, index) => {
                const cell = document.createElement("td");

                if (index === 0) {
                    const code = document.createElement("code");
                    code.textContent = text(value);
                    cell.append(code);
                } else {
                    cell.textContent = text(value, "—");
                }

                row.append(cell);
            });

            body.append(row);
        });
    };

    const replaceCards = (
        selector,
        rows,
        emptyMessage,
        builder
    ) => {
        const container = document.querySelector(selector);
        if (!container) {
            return;
        }

        container.replaceChildren();

        if (!rows.length) {
            const paragraph = document.createElement("p");
            paragraph.textContent = emptyMessage;
            container.append(paragraph);
            return;
        }

        rows.forEach((item) => {
            container.append(builder(item));
        });
    };

    const markStatus = (ok, label) => {
        if (liveDot) {
            liveDot.classList.toggle("is-error", !ok);
        }

        if (updateLabel) {
            updateLabel.textContent = label;
        }
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
                headers: {
                    "Accept": "application/json",
                },
            });

            if (response.status === 401) {
                window.location.assign("/staff");
                return;
            }

            if (!response.ok) {
                markStatus(
                    false,
                    "Mise à jour momentanément indisponible"
                );
                return;
            }

            const data = await response.json();
            const totals = data.totals || {};

            const statValues = document.querySelectorAll(
                "[data-staff-stats] article strong"
            );

            const orderedTotals = [
                totals.active_tournaments,
                totals.registrations,
                totals.pending_results,
                totals.invalid_matches,
            ];

            statValues.forEach((element, index) => {
                element.textContent = text(
                    orderedTotals[index],
                    0
                );
            });

            replaceRows(
                "[data-staff-tournaments]",
                (data.active_tournaments || []).map((item) => [
                    item.code,
                    item.name,
                    item.format,
                    item.status,
                    `${item.participant_count || 0}/${item.max_players || 0}`,
                    `${item.current_round || 0}/${item.total_rounds || 0}`,
                ]),
                "Aucun tournoi actif.",
                6
            );

            replaceRows(
                "[data-staff-results]",
                (data.pending_results || []).map((item) => [
                    item.tournament_code,
                    `${item.match_kind}:${item.match_id}`,
                    `${item.player1_score || 0}–${item.player2_score || 0}`,
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
                    const article =
                        document.createElement("article");
                    article.className = "professional-issue";

                    const strong =
                        document.createElement("strong");
                    strong.textContent =
                        `${text(item.tournament_code)} · ` +
                        `Match #${text(item.id)}`;

                    const span =
                        document.createElement("span");
                    span.textContent =
                        `${text(item.player1_name, "?")} ` +
                        `contre ${text(item.player2_name, "?")}`;

                    const code =
                        document.createElement("code");
                    code.textContent = text(item.status);

                    article.append(strong, span, code);
                    return article;
                }
            );

            replaceCards(
                "[data-staff-audit]",
                data.recent_audit || [],
                "Aucune action enregistrée.",
                (item) => {
                    const article =
                        document.createElement("article");
                    article.className =
                        "professional-audit-entry";

                    const strong =
                        document.createElement("strong");
                    strong.textContent =
                        text(item.action, "Action");

                    const actor =
                        document.createElement("span");
                    actor.textContent = text(
                        item.actor_name || item.actor_id,
                        "Système"
                    );

                    const date =
                        document.createElement("time");
                    date.textContent =
                        text(item.created_at);

                    article.append(strong, actor, date);
                    return article;
                }
            );

            markStatus(
                true,
                `Mis à jour à ${
                    new Date().toLocaleTimeString("fr-FR")
                }`
            );
        } catch (error) {
            console.debug(
                "Tableau de bord staff indisponible.",
                error
            );
            markStatus(
                false,
                "Connexion au tableau de bord interrompue"
            );
        } finally {
            running = false;
        }
    };

    window.setInterval(refresh, refreshMilliseconds);
    window.addEventListener("focus", refresh);

    document.addEventListener(
        "visibilitychange",
        () => {
            if (!document.hidden) {
                refresh();
            }
        }
    );
})();
