(() => {
    "use strict";

    const root = document.querySelector("[data-boss-soundtrack]");
    if (!root) return;

    const videoId = root.dataset.videoId || "iyGoea560lU";
    const button = root.querySelector("[data-boss-music-toggle]");
    const playerWrap = root.querySelector("[data-boss-youtube-wrap]");
    const playerSlot = root.querySelector("[data-boss-youtube-player]");
    const status = root.querySelector("[data-boss-music-status]");
    const volumeRow = root.querySelector(".boss-volume-row");

    if (!button || !playerWrap || !playerSlot) return;

    let active = false;

    const embedUrl =
        "https://www.youtube-nocookie.com/embed/" +
        encodeURIComponent(videoId) +
        "?autoplay=1&playsinline=1&controls=1&rel=0&loop=1&playlist=" +
        encodeURIComponent(videoId);

    const setStatus = (text) => {
        if (status) status.textContent = text;
    };

    const start = () => {
        playerSlot.innerHTML = "";

        const iframe = document.createElement("iframe");
        iframe.src = embedUrl;
        iframe.title = "Red Wolf of Radagon";
        iframe.loading = "lazy";
        iframe.allow = "autoplay; encrypted-media; picture-in-picture";
        iframe.referrerPolicy = "strict-origin-when-cross-origin";
        iframe.allowFullscreen = true;
        iframe.style.width = "100%";
        iframe.style.height = "100%";
        iframe.style.border = "0";

        playerSlot.appendChild(iframe);
        playerWrap.hidden = false;

        if (volumeRow) volumeRow.hidden = true;

        button.textContent = "⏹ Arrêter la musique";
        button.setAttribute("aria-pressed", "true");
        setStatus("Lecteur YouTube actif · règle le volume dans le lecteur.");
        active = true;
    };

    const stop = () => {
        playerSlot.innerHTML = "";
        playerWrap.hidden = true;

        button.textContent = "▶ Écouter la musique";
        button.setAttribute("aria-pressed", "false");
        setStatus("La musique est arrêtée.");
        active = false;
    };

    button.addEventListener("click", () => {
        if (active) stop();
        else start();
    });

    button.textContent = "▶ Écouter la musique";
    button.setAttribute("aria-pressed", "false");
})();
