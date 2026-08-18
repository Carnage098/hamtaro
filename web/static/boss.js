(() => {
    "use strict";

    const list = document.querySelector('[data-boss-sortable="1"]');
    if (!list) {
        return;
    }

    const status = document.querySelector("[data-boss-drag-status]");
    const reorderUrl = list.dataset.reorderUrl;
    const csrf = list.dataset.csrf;

    let dragged = null;
    let snapshot = [];

    const rows = () =>
        Array.from(
            list.querySelectorAll(".boss-program-row[data-challenger-id]")
        );

    const editableRows = () =>
        rows().filter((row) => row.getAttribute("draggable") === "true");

    const setStatus = (message, className = "") => {
        if (!status) {
            return;
        }
        status.classList.remove(
            "is-saving",
            "is-success",
            "is-error"
        );
        if (className) {
            status.classList.add(className);
        }
        status.textContent = message;
    };

    const refreshRanks = () => {
        rows().forEach((row, index) => {
            const rank = row.querySelector("[data-boss-rank]");
            if (rank) {
                rank.textContent = `#${index + 1}`;
            }
        });
    };

    const restoreSnapshot = () => {
        const byId = new Map(
            rows().map((row) => [row.dataset.challengerId, row])
        );
        snapshot.forEach((id) => {
            const row = byId.get(id);
            if (row) {
                list.appendChild(row);
            }
        });
        refreshRanks();
    };

    const persistOrder = async () => {
        const challengerIds = rows().map(
            (row) => Number(row.dataset.challengerId)
        );

        setStatus(
            "⏳ Enregistrement du nouvel ordre…",
            "is-saving"
        );

        try {
            const response = await fetch(reorderUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body: JSON.stringify({
                    csrf,
                    challenger_ids: challengerIds,
                }),
            });

            if (!response.ok) {
                const message = await response.text();
                throw new Error(
                    message || `HTTP ${response.status}`
                );
            }

            setStatus(
                "✅ Nouvel ordre enregistré.",
                "is-success"
            );
        } catch (error) {
            restoreSnapshot();
            setStatus(
                "❌ Impossible d'enregistrer l'ordre. "
                + "La liste a été restaurée.",
                "is-error"
            );
            console.error("Boss drag/drop:", error);
        }
    };

    list.addEventListener("dragstart", (event) => {
        const row = event.target.closest(
            '.boss-program-row[draggable="true"]'
        );
        if (!row) {
            return;
        }

        dragged = row;
        snapshot = rows().map(
            (item) => item.dataset.challengerId
        );

        row.classList.add("is-dragging");

        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData(
                "text/plain",
                row.dataset.challengerId
            );
        }
    });

    list.addEventListener("dragover", (event) => {
        if (!dragged) {
            return;
        }

        const target = event.target.closest(
            '.boss-program-row[draggable="true"]'
        );
        if (!target || target === dragged) {
            return;
        }

        event.preventDefault();

        editableRows().forEach((row) =>
            row.classList.remove("is-drop-target")
        );
        target.classList.add("is-drop-target");

        const rect = target.getBoundingClientRect();
        const after = event.clientY > rect.top + rect.height / 2;

        if (after) {
            target.after(dragged);
        } else {
            target.before(dragged);
        }

        refreshRanks();
    });

    list.addEventListener("drop", (event) => {
        if (dragged) {
            event.preventDefault();
        }
    });

    list.addEventListener("dragend", async () => {
        if (!dragged) {
            return;
        }

        editableRows().forEach((row) =>
            row.classList.remove(
                "is-dragging",
                "is-drop-target"
            )
        );

        dragged = null;
        refreshRanks();

        const current = rows().map(
            (item) => item.dataset.challengerId
        );

        if (current.join(",") !== snapshot.join(",")) {
            await persistOrder();
        } else {
            setStatus(
                "↕️ Mode staff : fais glisser un challenger "
                + "pour changer l'ordre."
            );
        }
    });
})();
