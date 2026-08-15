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
      viewer.hidden = false;
      if (placeholder) placeholder.hidden = true;
      if (loading) loading.hidden = false;
      viewer.setAttribute('src', loadButton.dataset.modelSrc || '');
    };

    if (loadButton) loadButton.addEventListener('click', loadModel);

    if (viewer) {
      viewer.addEventListener('progress', (event) => {
        if (!loadingText || !event.detail) return;
        const pct = Math.round((event.detail.totalProgress || 0) * 100);
        loadingText.textContent = `Chargement du modèle 3D… ${pct}%`;
      });

      viewer.addEventListener('load', () => {
        if (loading) loading.hidden = true;
        if (toolbar) toolbar.hidden = false;
      });

      viewer.addEventListener('error', () => {
        if (loadingText) loadingText.textContent = 'Impossible de charger le modèle 3D.';
      });
    }

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
      if (!document.fullscreenElement) {
        await shell.requestFullscreen?.();
      } else {
        await document.exitFullscreen?.();
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
            <a class="player-trophy-mini-card" href="${trophy.detail_url}">
              <span>🏆 ${trophy.id}</span>
              <strong>${escapeHtml(trophy.title || trophy.name || trophy.id)}</strong>
              <small>${escapeHtml(trophy.rarity || '')}</small>
            </a>
          `).join('')}
        </div>`;
    } catch (_) {
      // La section reste silencieuse : une panne de l'API trophées ne doit jamais casser le profil.
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
