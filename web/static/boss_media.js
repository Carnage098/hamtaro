(() => {
    "use strict";

    const root = document.querySelector("[data-boss-soundtrack]");
    if (!root) return;

    const videoId = root.dataset.videoId || "iyGoea560lU";
    const button = root.querySelector("[data-boss-music-toggle]");
    const volume = root.querySelector("[data-boss-music-volume]");
    const playerWrap = root.querySelector("[data-boss-youtube-wrap]");
    const playerSlot = root.querySelector("[data-boss-youtube-player]");
    const status = root.querySelector("[data-boss-music-status]");

    if (!button || !volume || !playerWrap || !playerSlot) return;

    let player = null;
    let creating = false;
    let pendingPlay = false;

    const savedVolume = Number(localStorage.getItem("hamtaroBossMusicVolume"));
    if (Number.isFinite(savedVolume) && savedVolume >= 0 && savedVolume <= 100) {
        volume.value = String(savedVolume);
    }

    const setStatus = (text) => {
        if (status) status.textContent = text;
    };

    const setButton = (playing) => {
        button.textContent = playing
            ? "⏸ Mettre en pause"
            : "▶ Activer la musique";
        button.setAttribute("aria-pressed", playing ? "true" : "false");
    };

    const loadYouTubeAPI = () => {
        if (window.YT && window.YT.Player) {
            return Promise.resolve();
        }

        return new Promise((resolve, reject) => {
            const previous = window.onYouTubeIframeAPIReady;
            window.onYouTubeIframeAPIReady = () => {
                if (typeof previous === "function") {
                    try { previous(); } catch (_) {}
                }
                resolve();
            };

            if (document.querySelector('script[src="https://www.youtube.com/iframe_api"]')) {
                const check = window.setInterval(() => {
                    if (window.YT && window.YT.Player) {
                        window.clearInterval(check);
                        resolve();
                    }
                }, 100);
                window.setTimeout(() => {
                    window.clearInterval(check);
                    if (!(window.YT && window.YT.Player)) {
                        reject(new Error("YouTube API timeout"));
                    }
                }, 12000);
                return;
            }

            const script = document.createElement("script");
            script.src = "https://www.youtube.com/iframe_api";
            script.async = true;
            script.onerror = () => reject(new Error("YouTube API unavailable"));
            document.head.appendChild(script);
        });
    };

    const createPlayer = async () => {
        if (player || creating) return;
        creating = true;
        playerWrap.hidden = false;
        setStatus("Chargement de la musique…");

        try {
            await loadYouTubeAPI();

            player = new window.YT.Player(playerSlot, {
                width: 220,
                height: 220,
                videoId,
                playerVars: {
                    playsinline: 1,
                    controls: 1,
                    rel: 0,
                    loop: 1,
                    playlist: videoId,
                    enablejsapi: 1,
                    origin: window.location.origin,
                },
                events: {
                    onReady: (event) => {
                        const value = Number(volume.value) || 35;
                        event.target.setVolume(value);
                        setStatus("Red Wolf of Radagon · YouTube");
                        if (pendingPlay) {
                            pendingPlay = false;
                            event.target.playVideo();
                        }
                    },
                    onStateChange: (event) => {
                        const playing =
                            window.YT &&
                            event.data === window.YT.PlayerState.PLAYING;
                        setButton(playing);
                    },
                    onError: () => {
                        setStatus("Lecture YouTube indisponible pour le moment.");
                        setButton(false);
                    },
                },
            });
        } catch (error) {
            console.error("Boss soundtrack:", error);
            setStatus("Lecture YouTube indisponible pour le moment.");
            setButton(false);
        } finally {
            creating = false;
        }
    };

    button.addEventListener("click", async () => {
        if (!player) {
            pendingPlay = true;
            await createPlayer();
            return;
        }

        const state = player.getPlayerState();
        if (window.YT && state === window.YT.PlayerState.PLAYING) {
            player.pauseVideo();
        } else {
            player.playVideo();
        }
    });

    volume.addEventListener("input", () => {
        const value = Math.max(0, Math.min(100, Number(volume.value) || 0));
        localStorage.setItem("hamtaroBossMusicVolume", String(value));
        if (player && typeof player.setVolume === "function") {
            player.setVolume(value);
        }
    });

    setButton(false);
})();
