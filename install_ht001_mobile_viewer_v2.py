from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent

BASE_TEMPLATE = ROOT / "web" / "templates" / "base.html"
DETAIL_TEMPLATE = ROOT / "web" / "templates" / "trophy_detail.html"
TROPHIES_JS = ROOT / "web" / "static" / "trophies.js"
TROPHIES_JSON = ROOT / "web" / "data" / "trophies.json"

MODEL_DIR = ROOT / "web" / "static" / "models" / "trophies"
SOURCE_MODEL = MODEL_DIR / "ht-001-web-light.glb"
MOBILE_MODEL = MODEL_DIR / "ht-001-mobile.glb"

MOBILE_URL = "/static/models/trophies/ht-001-mobile.glb?v=20260815-mobile-v2"


def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")


def backup(path: Path) -> None:
    target = path.with_suffix(path.suffix + ".before-ht001-mobile-v2.bak")
    if not target.exists():
        shutil.copy2(path, target)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        fail(f"Patch introuvable : {label}")
    return text.replace(old, new, 1)


def run(args: list[str]) -> None:
    print("→", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def build_mobile_model() -> None:
    if MOBILE_MODEL.exists() and MOBILE_MODEL.stat().st_size > 1024:
        print(
            f"✅ Version mobile déjà présente : "
            f"{MOBILE_MODEL.relative_to(ROOT)} ({size_mb(MOBILE_MODEL):.1f} Mo)"
        )
        return

    if not SOURCE_MODEL.exists():
        fail(f"Modèle source absent : {SOURCE_MODEL.relative_to(ROOT)}")

    npx = shutil.which("npx")
    if not npx:
        fail(
            "npx est introuvable. Node.js/npm est nécessaire uniquement "
            "pour fabriquer la version mobile du GLB."
        )

    work = MODEL_DIR / ".ht001-mobile-build"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    welded = work / "01-welded.glb"
    simplified = work / "02-simplified.glb"
    resized = work / "03-resized.glb"
    final = work / "04-mobile.glb"

    print()
    print("🐹 Création du GLB mobile HT-001")
    print(f"Source : {size_mb(SOURCE_MODEL):.1f} Mo")

    run([
        npx, "--yes", "@gltf-transform/cli",
        "weld",
        str(SOURCE_MODEL),
        str(welded),
    ])

    run([
        npx, "--yes", "@gltf-transform/cli",
        "simplify",
        str(welded),
        str(simplified),
        "--ratio", "0.45",
        "--error", "0.0015",
    ])

    run([
        npx, "--yes", "@gltf-transform/cli",
        "resize",
        str(simplified),
        str(resized),
        "--width", "1024",
        "--height", "1024",
    ])

    run([
        npx, "--yes", "@gltf-transform/cli",
        "draco",
        str(resized),
        str(final),
        "--method", "edgebreaker",
    ])

    shutil.copy2(final, MOBILE_MODEL)
    shutil.rmtree(work)

    print(
        f"✅ Mobile : {size_mb(MOBILE_MODEL):.1f} Mo "
        f"(desktop conservé à {size_mb(SOURCE_MODEL):.1f} Mo)"
    )


def patch_base_template() -> None:
    text = BASE_TEMPLATE.read_text(encoding="utf-8")

    text = text.replace(
        '<script src="/static/trophies.js?v=20260815-2" defer></script>',
        '<script src="/static/trophies.js?v=20260815-mobile-v2" defer></script>',
    )

    text = text.replace(
        '<link rel="stylesheet" href="/static/trophies.css?v=20260815-2">',
        '<link rel="stylesheet" href="/static/trophies.css?v=20260815-4">',
    )

    BASE_TEMPLATE.write_text(text, encoding="utf-8")


def patch_detail_template() -> None:
    text = DETAIL_TEMPLATE.read_text(encoding="utf-8")

    text = text.replace(
        '<link rel="stylesheet" href="/static/trophies.css?v=20260815-4">\n\n',
        '',
        1,
    )

    old_button_source = '          data-model-src="{{ trophy.model_path }}"\n'
    new_button_source = (
        '          data-model-src="{{ trophy.model_path }}"\n'
        '          data-model-mobile-src="{{ trophy.mobile_model_path or trophy.model_path }}"\n'
        '          data-trophy-id="{{ trophy.id }}"\n'
    )

    text = replace_once(
        text,
        old_button_source,
        new_button_source,
        "source mobile du bouton",
    )

    text = text.replace(
        '<script src="/static/trophies.js?v=20260815-4" defer></script>\n',
        '',
        1,
    )

    DETAIL_TEMPLATE.write_text(text, encoding="utf-8")


def patch_catalog() -> None:
    payload = json.loads(TROPHIES_JSON.read_text(encoding="utf-8"))
    trophies = payload.get("trophies")

    if not isinstance(trophies, list):
        fail("La clé 'trophies' de trophies.json n'est pas une liste.")

    found = False

    for trophy in trophies:
        if not isinstance(trophy, dict):
            continue

        if str(trophy.get("id") or "").upper() != "HT-001":
            continue

        trophy["mobile_model_path"] = MOBILE_URL
        trophy["mobile_web_build"] = (
            "Mobile V2 — géométrie simplifiée à 45 %, textures 1K, Draco"
        )
        found = True
        break

    if not found:
        fail("HT-001 est introuvable dans web/data/trophies.json.")

    TROPHIES_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def patch_javascript() -> None:
    js = r'''(() => {
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
'''

    TROPHIES_JS.write_text(js, encoding="utf-8")


def main() -> None:
    required = (
        BASE_TEMPLATE,
        DETAIL_TEMPLATE,
        TROPHIES_JS,
        TROPHIES_JSON,
        SOURCE_MODEL,
    )

    for path in required:
        if not path.exists():
            fail(
                f"Fichier introuvable : {path.relative_to(ROOT)}. "
                "Place ce script à la racine du dépôt Hamtaro."
            )

    print("🐹 Correctif HT-001 mobile viewer V2")
    print("Aucun téléchargement de trophée n'est ajouté.")
    print()

    build_mobile_model()

    for path in (
        BASE_TEMPLATE,
        DETAIL_TEMPLATE,
        TROPHIES_JS,
        TROPHIES_JSON,
    ):
        backup(path)

    originals = {
        BASE_TEMPLATE: BASE_TEMPLATE.read_text(encoding="utf-8"),
        DETAIL_TEMPLATE: DETAIL_TEMPLATE.read_text(encoding="utf-8"),
        TROPHIES_JS: TROPHIES_JS.read_text(encoding="utf-8"),
        TROPHIES_JSON: TROPHIES_JSON.read_text(encoding="utf-8"),
    }

    try:
        patch_base_template()
        patch_detail_template()
        patch_catalog()
        patch_javascript()

        json.loads(TROPHIES_JSON.read_text(encoding="utf-8"))

    except Exception:
        for path, content in originals.items():
            path.write_text(content, encoding="utf-8")
        raise

    print()
    print("✅ Viewer mobile HT-001 corrigé.")
    print("✅ Un seul trophies.js est chargé.")
    print("✅ HT-001 utilise ht-001-mobile.glb sur téléphone/tablette.")
    print("✅ Le desktop garde ht-001-web-light.glb.")
    print("✅ Rotation automatique réduite sur mobile.")
    print("✅ Messages de progression/erreur visibles.")
    print()
    print("Vérifie les tailles :")
    print("  ls -lh web/static/models/trophies/ht-001*.glb")
    print()
    print("Puis pousse :")
    print(
        "  git add "
        "web/templates/base.html "
        "web/templates/trophy_detail.html "
        "web/static/trophies.js "
        "web/data/trophies.json "
        "web/static/models/trophies/ht-001-mobile.glb"
    )
    print('  git commit -m "fix: make HT-001 viewer reliable on mobile"')
    print("  git pull --rebase origin main")
    print("  git push origin main")


if __name__ == "__main__":
    main()
