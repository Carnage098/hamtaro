/* HAMTARO RADAGON BOSS CONTROLLER START */
(() => {
  const DEFAULT_IDLE = "Radagon_Idle";

  const ONE_SHOTS = new Set([
    "Radagon_Observe",
    "Radagon_Intro",
    "Radagon_Ready",
    "Radagon_Victory",
    "Radagon_Defeat",
  ]);

  const KEYMAP = {
    "1": "Radagon_Idle",
    "2": "Radagon_Observe",
    "3": "Radagon_Intro",
    "4": "Radagon_Ready",
    "5": "Radagon_Victory",
    "6": "Radagon_Defeat",
  };

  function createController(root) {
    const model = root.querySelector("#radagonModel") || document.querySelector("#radagonModel");
    const buttons = [...root.querySelectorAll("[data-radagon-action]")];
    const status = root.querySelector("[data-radagon-status]");
    const current = root.querySelector("[data-radagon-current]");
    const dot = root.querySelector("[data-radagon-status-dot]");
    const speed = root.querySelector("[data-radagon-speed]");
    const pause = root.querySelector("[data-radagon-pause]");
    const autoObserve = root.querySelector("[data-radagon-auto-observe]");

    if (!model) return null;

    let currentAnimation = DEFAULT_IDLE;
    let paused = false;
    let observeTimer = null;
    let loadedAnimations = [];
    let playToken = 0;

    const setStatus = (text, kind = "ready") => {
      if (status) status.textContent = text;
      if (dot) {
        dot.classList.remove("is-ready", "is-error");
        if (kind === "ready") dot.classList.add("is-ready");
        if (kind === "error") dot.classList.add("is-error");
      }
    };

    const setActive = (name) => {
      buttons.forEach((button) => {
        button.classList.toggle("is-active", button.dataset.radagonAction === name);
      });
      if (current) current.textContent = name;
    };

    const hasAnimation = (name) => {
      if (!loadedAnimations.length) return true;
      return loadedAnimations.includes(name);
    };

    const clearObserveTimer = () => {
      if (observeTimer) {
        clearTimeout(observeTimer);
        observeTimer = null;
      }
    };

    const scheduleObserve = () => {
      clearObserveTimer();
      if (!autoObserve?.checked) return;
      if (currentAnimation !== DEFAULT_IDLE) return;

      const delay = 12000 + Math.round(Math.random() * 12000);
      observeTimer = setTimeout(() => {
        if (currentAnimation === DEFAULT_IDLE && autoObserve?.checked) {
          play("Radagon_Observe", { source: "ambient" });
        }
      }, delay);
    };

    const play = (name, options = {}) => {
      if (!hasAnimation(name)) {
        setStatus(`Animation absente : ${name}`, "error");
        console.warn("[Radagon] animation absente:", name, loadedAnimations);
        return false;
      }

      playToken += 1;
      const token = playToken;

      clearObserveTimer();
      currentAnimation = name;
      paused = false;

      model.pause();
      model.animationName = name;
      model.loop = name === DEFAULT_IDLE;
      model.currentTime = 0;
      model.timeScale = Number(speed?.value || 1);
      model.play();

      setActive(name);
      setStatus(options.source === "ambient" ? "Réaction ambiante" : "Animation en cours");

      // Safety fallback for viewers/browsers where the "finished" event is unreliable.
      if (ONE_SHOTS.has(name)) {
        const durations = {
          Radagon_Observe: 5000,
          Radagon_Intro: 6500,
          Radagon_Ready: 4000,
          Radagon_Victory: 5500,
          Radagon_Defeat: 7000,
        };

        window.setTimeout(() => {
          if (playToken !== token) return;
          if (currentAnimation !== name) return;
          backToIdle();
        }, durations[name] || 6000);
      } else {
        scheduleObserve();
      }

      return true;
    };

    const backToIdle = () => {
      if (currentAnimation === DEFAULT_IDLE) {
        scheduleObserve();
        return;
      }
      play(DEFAULT_IDLE, { source: "system" });
    };

    const togglePause = () => {
      if (paused) {
        model.play();
        paused = false;
        setStatus("Animation reprise");
      } else {
        model.pause();
        paused = true;
        setStatus("Animation en pause");
      }
    };

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        play(button.dataset.radagonAction, { source: "button" });
      });
    });

    speed?.addEventListener("change", () => {
      model.timeScale = Number(speed.value || 1);
      setStatus(`Vitesse ${speed.value}×`);
    });

    pause?.addEventListener("click", togglePause);

    autoObserve?.addEventListener("change", () => {
      if (autoObserve.checked) scheduleObserve();
      else clearObserveTimer();
    });

    model.addEventListener("load", () => {
      loadedAnimations = Array.isArray(model.availableAnimations)
        ? model.availableAnimations
        : [];

      if (loadedAnimations.length) {
        console.info("[Radagon] animations GLB:", loadedAnimations);
      }

      const missing = buttons
        .map((button) => button.dataset.radagonAction)
        .filter((name) => loadedAnimations.length && !loadedAnimations.includes(name));

      buttons.forEach((button) => {
        const name = button.dataset.radagonAction;
        const disabled = loadedAnimations.length && !loadedAnimations.includes(name);
        button.disabled = Boolean(disabled);
        button.title = disabled ? `Animation absente du GLB : ${name}` : "";
      });

      if (missing.length) {
        setStatus(`${missing.length} animation(s) absente(s) du GLB`, "error");
      } else {
        setStatus("Radagon prêt");
      }

      // Intro au premier chargement, puis Idle.
      if (hasAnimation("Radagon_Intro")) {
        play("Radagon_Intro", { source: "startup" });
      } else {
        play(DEFAULT_IDLE, { source: "startup" });
      }
    });

    model.addEventListener("finished", () => {
      if (ONE_SHOTS.has(currentAnimation)) {
        backToIdle();
      }
    });

    model.addEventListener("error", (event) => {
      console.error("[Radagon] model-viewer error", event);
      setStatus("Erreur de chargement du modèle", "error");
    });

    document.addEventListener("keydown", (event) => {
      if (
        event.ctrlKey || event.metaKey || event.altKey ||
        ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)
      ) return;

      const animation = KEYMAP[event.key];
      if (animation) {
        event.preventDefault();
        play(animation, { source: "keyboard" });
      }

      if (event.key === " ") {
        event.preventDefault();
        togglePause();
      }
    });

    const controller = {
      play,
      idle: () => play("Radagon_Idle"),
      observe: () => play("Radagon_Observe"),
      intro: () => play("Radagon_Intro"),
      ready: () => play("Radagon_Ready"),
      victory: () => play("Radagon_Victory"),
      defeat: () => play("Radagon_Defeat"),
      pause: () => model.pause(),
      resume: () => model.play(),
      get current() { return currentAnimation; },
      get animations() { return [...loadedAnimations]; },
      get model() { return model; },
    };

    return controller;
  }

  function boot() {
    const roots = [...document.querySelectorAll("[data-radagon-controller]")];
    if (!roots.length) return;

    const controllers = roots.map(createController).filter(Boolean);

    // API globale pour la logique du format Boss.
    // Exemples:
    // window.radagonController.victory()
    // window.radagonController.play("Radagon_Ready")
    window.radagonControllers = controllers;
    window.radagonController = controllers[0] || null;

    window.dispatchEvent(new CustomEvent("hamtaro:radagon-ready", {
      detail: { controller: window.radagonController }
    }));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
/* HAMTARO RADAGON BOSS CONTROLLER END */