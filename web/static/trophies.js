(() => {
  const shell = document.querySelector('[data-trophy-viewer-shell]');

  if (shell) {
    const viewer = shell.querySelector('[data-trophy-model-viewer]');
    const placeholder = shell.querySelector('[data-trophy-placeholder]');
    const loadButton = shell.querySelector('[data-load-trophy-model]');
    const toolbar = shell.querySelector('[data-trophy-toolbar]');
    const loading = shell.querySelector('[data-trophy-loading]');
    const loadingText = shell.querySelector('[data-trophy-loading-text]');
    let rotating = true;

    const loadModel = () => {
      if (!viewer || !loadButton || viewer.getAttribute('src')) return;
      const source = loadButton.dataset.modelSrc || '';
      if (!source) return;

      viewer.hidden = false;
      if (placeholder) placeholder.hidden = true;
      if (loading) loading.hidden = false;
      viewer.setAttribute('src', source);
    };

    loadButton?.addEventListener('click', loadModel);

    // Préchargement discret sur grand écran uniquement. Le modèle reste caché
    // jusqu'au clic, mais le navigateur peut déjà remplir son cache HTTP.
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    const saveData = Boolean(connection?.saveData);
    const slowConnection = ['slow-2g', '2g'].includes(connection?.effectiveType || '');
    const shouldWarmCache = window.matchMedia('(min-width: 900px)').matches && !saveData && !slowConnection;

    if (shouldWarmCache && loadButton?.dataset.modelSrc) {
      const source = loadButton.dataset.modelSrc;
      const warm = () => {
        if (document.visibilityState !== 'visible') return;
        fetch(source, { cache: 'force-cache', credentials: 'same-origin' }).catch(() => {});
      };
      if ('requestIdleCallback' in window) {
        window.requestIdleCallback(warm, { timeout: 2500 });
      } else {
        window.setTimeout(warm, 1500);
      }
    }

    viewer?.addEventListener('progress', (event) => {
      if (!loadingText || !event.detail) return;
      const pct = Math.round((event.detail.totalProgress || 0) * 100);
      loadingText.textContent = `Chargement du modèle 3D… ${pct}%`;
    });

    viewer?.addEventListener('load', () => {
      if (loading) loading.hidden = true;
      if (toolbar) toolbar.hidden = false;
    });

    viewer?.addEventListener('error', () => {
      if (loading) loading.hidden = false;
      if (loadingText) {
        loadingText.textContent = 'Impossible de charger le modèle 3D. Recharge la page pour réessayer.';
      }
    });

    shell.querySelector('[data-trophy-reset]')?.addEventListener('click', () => {
      if (!viewer) return;
      viewer.cameraOrbit = '0deg 75deg auto';
      viewer.cameraTarget = 'auto auto auto';
      viewer.fieldOfView = 'auto';
      viewer.jumpCameraToGoal?.();
    });

    shell.querySelector('[data-trophy-toggle-rotate]')?.addEventListener('click', (event) => {
      if (!viewer) return;
      rotating = !rotating;
      viewer.autoRotate = rotating;
      event.currentTarget.textContent = rotating ? '⟳ Rotation' : '▶ Rotation';
    });

    shell.querySelector('[data-trophy-fullscreen]')?.addEventListener('click', async () => {
      try {
        if (!document.fullscreenElement) {
          await shell.requestFullscreen?.();
        } else {
          await document.exitFullscreen?.();
        }
      } catch (_) {
        // Le plein écran n'est pas disponible sur tous les navigateurs mobiles.
      }
    });

    const params = new URLSearchParams(window.location.search);
    if (params.get('autoload') === '1') loadModel();
  }

  document.querySelectorAll('[data-player-trophies]').forEach(async (container) => {
    const discordId = container.dataset.discordId;
    if (!discordId) return;

    try {
      const response = await fetch(`/api/players/${encodeURIComponent(discordId)}/trophies`, {
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) return;

      const data = await response.json();
      const trophies = Array.isArray(data.trophies) ? data.trophies : [];

      if (!trophies.length) {
        container.innerHTML = '<p class="hx-muted">Aucun trophée dans la collection pour le moment.</p>';
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
