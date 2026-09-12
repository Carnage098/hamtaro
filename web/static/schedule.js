(() => {
    "use strict";

    const tabs = [...document.querySelectorAll("[data-schedule-tab]")];
    const panels = [...document.querySelectorAll("[data-schedule-panel]")];

    const selectMonth = (key) => {
        tabs.forEach((tab) => {
            const active = tab.dataset.scheduleTab === key;
            tab.classList.toggle("is-active", active);
            tab.setAttribute("aria-selected", String(active));
            tab.tabIndex = active ? 0 : -1;
        });
        panels.forEach((panel) => {
            panel.hidden = panel.dataset.schedulePanel !== key;
        });
    };

    tabs.forEach((tab, index) => {
        tab.addEventListener("click", () => selectMonth(tab.dataset.scheduleTab));
        tab.addEventListener("keydown", (event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
                return;
            }
            event.preventDefault();
            let next = index;
            if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
            if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
            if (event.key === "Home") next = 0;
            if (event.key === "End") next = tabs.length - 1;
            tabs[next].focus();
            selectMonth(tabs[next].dataset.scheduleTab);
        });
    });

    const dialog = document.querySelector("[data-schedule-dialog]");
    if (!dialog) return;

    const field = (name) => dialog.querySelector(`[data-dialog-${name}]`);
    let opener = null;

    document.querySelectorAll("[data-schedule-slot]").forEach((button) => {
        button.addEventListener("click", () => {
            opener = button;
            const data = button.dataset;
            field("emoji").textContent = data.emoji;
            field("day").textContent = data.day;
            field("title").textContent = data.tournamentName || data.format;
            field("time").textContent = `${data.start}–${data.end}`;
            field("platform").textContent = data.platform;

            const linked = Boolean(data.tournamentId);
            ["id", "code", "players", "status"].forEach((name) => {
                field(`${name}-row`).hidden = !linked;
            });

            if (linked) {
                field("id").textContent = `#${data.tournamentId}`;
                field("code").textContent = data.tournamentCode;
                field("players").textContent = `${data.participants}/${data.capacity} joueurs`;
                field("status").textContent = data.tournamentStatus;
                field("message").textContent = "Ce créneau est relié au tournoi officiel Hamtaro.";
                field("link").href = `/tournaments/${data.tournamentId}`;
                field("link").hidden = false;
            } else {
                field("message").textContent = "Le tournoi n'est pas encore ouvert. Son ID, son code et les inscriptions apparaîtront ici dès sa création.";
                field("link").hidden = true;
                field("link").removeAttribute("href");
            }

            dialog.showModal();
        });
    });

    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () => opener?.focus());
})();
