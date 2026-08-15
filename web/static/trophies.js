(() => {
  if (window.__HAMTARO_TROPHIES_JS_V2__) return;
  window.__HAMTARO_TROPHIES_JS_V2__ = true;

  const shell = document.querySelector('[data-trophy-viewer-shell]');

  if (shell) {
    const viewer = shell.querySelector('[data-trophy-model-viewer]');
    const placeholder = shell.querySelector('[data-trophy-placeholder]');
    const loadButton = shell.querySelector('[data-load-trophy-model]');
    const toolbar = shell.querySelector('[data-trophy-toolbar]');
    const loading = shell.querySelector('[data-trophy-loading]');
    const loadingText = shell.querySelector('[data-trophy-loading-text]');

    const isMobile =
      window.matchMedia('(max-width: 900px), (pointer: coarse)').matches ||
      /iPhone|iPad|iPod|Android/i.test(navigator.userAgent || '');

    let rotating = !isMobile;
    let loadingStarted = false;

    const setLoadingText = (text) => {
      if (loadingText) loadingText.textContent = text;
    };

    const setButtonLoading = (active) => {
      if (!loadButton) return;
      loadButton.disabled = active;
      loadButton.textContent = active
        ? 'Chargement du trophée…'
        : 'Charger le trophée en 3D';
    };

    const loadModel = () => {
      if (!viewer || !loadButton || loadingStarted || viewer.getAttribute('src')) {
        return;
      }

      const desktopSource = loadButton.dataset.modelSrc || '';
      const mobileSource =
        loadButton.dataset.modelMobileSrc ||
        desktopSource;

      const source = isMobile ? mobileSource : desktopSource;

      if (!source) {
        setLoadingText('Aucun modèle 3D n’est configuré pour ce trophée.');
        if (loading) loading.hidden = false;
        return;
      }

      loadingStarted = true;
      setButtonLoading(true);

      viewer.hidden = false;
      if (placeholder) placeholder.hidden = true;
      if (loading) loading.hidden = false;

      if (isMobile) {
        viewer.autoRotate = false;
        viewer.removeAttribute('auto-rotate');
        viewer.setAttribute('shadow-intensity', '0.45');
        viewer.setAttribute('shadow-softness', '0.5');
        viewer.setAttribute('interaction-prompt', 'none');
        viewer.setAttribute('touch-action', 'pan-y');
        setLoadingText('Chargement de la version mobile… 0%');
      } else {
        setLoadingText('Chargement du modèle 3D… 0%');
      }

      viewer.setAttribute('src', source);

      console.info('[Hamtaro trophies] viewer load', {
        trophy: loadButton.dataset.trophyId || '',
        mobile: isMobile,
        source,
      });
    };

    loadButton?.addEventListener('click', loadModel);

    viewer?.addEventListener('progress', (event) => {
      if (!event.detail) return;
      const pct = Math.round((event.detail.totalProgress || 0) * 100);

      setLoadingText(
        isMobile
          ? `Chargement de la version mobile… ${pct}%`
          : `Chargement du modèle 3D… ${pct}%`
      );
    });

    viewer?.addEventListener('load', () => {
      loadingStarted = false;
      if (loading) loading.hidden = true;
      if (toolbar) toolbar.hidden = false;
      setButtonLoading(false);
    });

    viewer?.addEventListener('error', (event) => {
      loadingStarted = false;
      setButtonLoading(false);
      if (loading) loading.hidden = false;

      const source = viewer.getAttribute('src') || '';

      setLoadingText(
        isMobile
          ? 'Le modèle mobile n’a pas pu être chargé. Recharge la page puis réessaie.'
          : 'Impossible de charger le modèle 3D. Recharge la page puis réessaie.'
      );

      console.error('[Hamtaro trophies] model-viewer error', {
        event,
        source,
        mobile: isMobile,
      });
    });

    shell.querySelector('[data-trophy-reset]')?.addEventListener('click', () => {
      if (!viewer) return;
      viewer.cameraOrbit = '0deg 75deg auto';
      viewer.cameraTarget = 'auto auto auto';
      viewer.fieldOfView = 'auto';
      viewer.jumpCameraToGoal?.();
    });

    shell.querySelector('[data-trophy-toggle-rotate]')?.addEventListener(
      'click',
      (event) => {
        if (!viewer) return;
        rotating = !rotating;
        viewer.autoRotate = rotating;
        event.currentTarget.textContent =
          rotating ? '⟳ Rotation' : '▶ Rotation';
      }
    );

    shell.querySelector('[data-trophy-fullscreen]')?.addEventListener(
      'click',
      async () => {
        try {
          if (!document.fullscreenElement) {
            await shell.requestFullscreen?.();
          } else {
            await document.exitFullscreen?.();
          }
        } catch (_) {
          // Le plein écran n'est pas disponible sur tous les navigateurs mobiles.
        }
      }
    );

    const params = new URLSearchParams(window.location.search);
    if (params.get('autoload') === '1') loadModel();
  }

  document.querySelectorAll('[data-player-trophies]').forEach(async (container) => {
    const discordId = container.dataset.discordId;
    if (!discordId) return;

    try {
      const response = await fetch(
        `/api/players/${encodeURIComponent(discordId)}/trophies`,
        { headers: { Accept: 'application/json' } }
      );

      if (!response.ok) return;

      const data = await response.json();
      const trophies = Array.isArray(data.trophies) ? data.trophies : [];

      if (!trophies.length) {
        container.innerHTML =
          '<p class="hx-muted">Aucun trophée dans la collection pour le moment.</p>';
        return;
      }

      container.innerHTML = `
        <div class="player-trophies-grid">
          ${trophies.map((trophy) => `
            <a class="player-trophy-mini-card" href="${escapeHtml(trophy.detail_url || '#')}">
              <span>${escapeHtml(trophy.id || '')}</span>
              <strong>${escapeHtml(trophy.tagline || trophy.title || trophy.name || trophy.id)}</strong>
              <small>${escapeHtml(trophy.rarity || '')}</small>
            </a>
          `).join('')}
        </div>`;
    } catch (_) {
      // Une panne de l'API trophées ne doit jamais casser un profil joueur.
    }
  });

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }
})();
