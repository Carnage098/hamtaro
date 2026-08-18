#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import subprocess
import sys
from pathlib import Path

MARK = "HAMTARO DECK LAB V10"

ROUTES = Path("services/deck_builder_routes.py")
HTML = Path("web/templates/deck_builder.html")
CSS = Path("web/static/deck_builder.css")
JS = Path("web/static/deck_builder.js")
TARGETS = (ROUTES, HTML, CSS, JS)


def die(msg: str) -> None:
    raise SystemExit(f"[V10] ERREUR: {msg}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        die(f"ancre introuvable pour {label}. Le fichier a probablement changé; aucun fichier ne sera modifié.")
    return text.replace(old, new, 1)


def insert_before_once(text: str, anchor: str, insertion: str, label: str) -> str:
    if anchor not in text:
        die(f"ancre introuvable pour {label}. Le fichier a probablement changé; aucun fichier ne sera modifié.")
    return text.replace(anchor, insertion + anchor, 1)


def patch_routes(text: str) -> str:
    if MARK in text:
        return text

    analysis_anchor = "    async def analyze(self, request: web.Request) -> web.Response:\n"
    resilient = '''    # --- HAMTARO DECK LAB V10: resilient analysis ---\n    @staticmethod\n    def _analysis_strength(payload: Any) -> tuple[int, int, int, int]:\n        \"\"\"Compare two analyses without pretending that an empty fallback is reliable.\"\"\"\n        if not isinstance(payload, dict):\n            return (-1, 0, 0, 0)\n\n        zones = payload.get(\"zones\") or {}\n        zone_cards = 0\n        if isinstance(zones, dict):\n            for zone_name in (\"main\", \"extra\", \"side\"):\n                zone = zones.get(zone_name) or []\n                if isinstance(zone, list):\n                    zone_cards += len(zone)\n\n        try:\n            samples = int(payload.get(\"samples_analyzed\") or 0)\n        except (TypeError, ValueError):\n            samples = 0\n\n        confidence = payload.get(\"confidence\") or {}\n        try:\n            confidence_score = int(confidence.get(\"score\") or 0) if isinstance(confidence, dict) else 0\n        except (TypeError, ValueError):\n            confidence_score = 0\n\n        healthy = 0 if payload.get(\"degraded\") else 1\n        return (healthy, samples, zone_cards, confidence_score)\n\n    async def _analyze_resilient(self, query: str, options: dict[str, Any]) -> dict[str, Any]:\n        \"\"\"Retry weak analyses with a larger sample while preserving explicit user filters.\"\"\"\n        primary = await self.service.analyze(query, **options)\n        if not isinstance(primary, dict):\n            return primary\n\n        primary_strength = self._analysis_strength(primary)\n        requested_max = int(options.get(\"max_decks\") or 48)\n        weak = bool(primary.get(\"degraded\")) or primary_strength[1] < 8 or primary_strength[2] < 18\n\n        if not weak or requested_max >= 96:\n            return primary\n\n        retry_options = dict(options)\n        retry_options[\"max_decks\"] = 96\n\n        try:\n            expanded = await self.service.analyze(query, **retry_options)\n        except Exception:\n            primary[\"recovery\"] = {\n                \"attempted\": True,\n                \"chosen\": \"initial\",\n                \"strategy\": \"expanded-sample\",\n                \"initial_samples\": primary_strength[1],\n                \"final_samples\": primary_strength[1],\n                \"retry_failed\": True,\n            }\n            return primary\n\n        expanded_strength = self._analysis_strength(expanded)\n        chosen = expanded if expanded_strength > primary_strength else primary\n        final_strength = self._analysis_strength(chosen)\n        chosen[\"recovery\"] = {\n            \"attempted\": True,\n            \"chosen\": \"expanded\" if chosen is expanded else \"initial\",\n            \"strategy\": \"expanded-sample\",\n            \"initial_samples\": primary_strength[1],\n            \"final_samples\": final_strength[1],\n            \"initial_cards\": primary_strength[2],\n            \"final_cards\": final_strength[2],\n        }\n\n        if chosen is expanded:\n            warnings = list(chosen.get(\"warnings\") or [])\n            warnings.insert(0, \"Hamtaro a automatiquement élargi l'échantillon car l'analyse initiale était trop faible.\")\n            chosen[\"warnings\"] = warnings\n\n        return chosen\n\n'''
    text = insert_before_once(text, analysis_anchor, resilient, "analyse résiliente")

    old_call = "            payload = await self.service.analyze(query, **self._common_options(request))\n"
    new_call = "            options = self._common_options(request)\n            payload = await self._analyze_resilient(query, options)\n"
    text = replace_once(text, old_call, new_call, "appel analyze")

    # Keep the public health endpoint aligned with the UI version if the old value is still present.
    text = text.replace('"version": "8.3"', '"version": "10.0"', 1)

    feature_anchor = '"persistent-learned-decklists",'
    if feature_anchor in text and '"adaptive-analysis-retry"' not in text:
        text = text.replace(
            feature_anchor,
            feature_anchor + '\n                    "adaptive-analysis-retry",\n                    "analysis-quality-cockpit",',
            1,
        )
    return text


def patch_html(text: str) -> str:
    if MARK in text:
        return text

    text = text.replace("HAMTARO DECK LAB · V9.0", "HAMTARO DECK LAB · V10.0", 1)

    anchor = '        <div class="db-warning-list" data-db-warnings hidden></div>\n'
    cockpit = '''        <!-- HAMTARO DECK LAB V10: quality cockpit -->\n        <section class="db-quality-cockpit" data-db-quality-cockpit hidden>\n            <div class="db-quality-head">\n                <div>\n                    <span class="db-kicker">Qualité de l'analyse</span>\n                    <h3>Cette base est-elle vraiment exploitable ?</h3>\n                    <p data-db-quality-note>Hamtaro vérifie l'échantillon avant de présenter les ratios comme fiables.</p>\n                </div>\n                <span class="db-quality-badge" data-db-quality-badge>Analyse</span>\n            </div>\n\n            <div class="db-quality-grid">\n                <article>\n                    <span>Échantillon</span>\n                    <strong data-db-quality-samples>—</strong>\n                    <small>decklists réellement analysées</small>\n                </article>\n                <article>\n                    <span>Couverture</span>\n                    <strong data-db-quality-cards>—</strong>\n                    <small>cartes observées dans les zones</small>\n                </article>\n                <article>\n                    <span>Structure Main</span>\n                    <strong data-db-quality-main>—</strong>\n                    <small>Core · fréquentes · flex</small>\n                </article>\n                <article>\n                    <span>Récupération auto</span>\n                    <strong data-db-quality-recovery>—</strong>\n                    <small>élargissement si les données sont faibles</small>\n                </article>\n            </div>\n\n            <div class="db-quality-actions">\n                <button class="db-secondary-button" type="button" data-db-max-coverage>\n                    Relancer en couverture maximale\n                </button>\n                <button class="db-link-button" type="button" data-db-quality-cards-jump>\n                    Voir les cartes observées\n                </button>\n            </div>\n        </section>\n'''
    return replace_once(text, anchor, anchor + cockpit, "cockpit qualité HTML")


def patch_js(text: str) -> str:
    if MARK in text:
        return text

    marker_and_renderer = r'''    // --- HAMTARO DECK LAB V10: quality cockpit ---
    const renderQualityCockpit = () => {
      const cockpit = $('[data-db-quality-cockpit]');
      if (!cockpit) return;

      const a = state.analysis;
      if (!a) {
        cockpit.hidden = true;
        return;
      }

      cockpit.hidden = false;

      const samples = Number(a.samples_analyzed || 0);
      const confidence = Number(a.confidence?.score || 0);
      const zoneCards = ['main', 'extra', 'side'].reduce((total, zone) => {
        const cards = a.zones?.[zone];
        return total + (Array.isArray(cards) ? cards.length : 0);
      }, 0);
      const fallbackCards = Array.isArray(a.fallback_archetype_cards) ? a.fallback_archetype_cards.length : 0;
      const coverage = Math.max(zoneCards, fallbackCards);

      const mainProfile = a.deck_profile?.main || {};
      const coreSlots = Number(mainProfile.core_slots || 0);
      const frequentSlots = Number(mainProfile.frequent_slots || 0);
      const flexSlots = Number(mainProfile.flex_slots_estimate || 0);
      const structureKnown = !a.degraded && samples > 0 && (
        coreSlots > 0 || frequentSlots > 0 || flexSlots > 0 || Number(mainProfile.observed_unique_cards || 0) > 0
      );

      let tier = 'solid';
      let badge = 'Solide';
      let note = `${samples} decklist${samples > 1 ? 's' : ''} exploitable${samples > 1 ? 's' : ''} · confiance ${confidence} %.`;

      if (a.degraded || samples === 0) {
        tier = 'danger';
        badge = 'Secours';
        note = "Pas assez de decklists fiables : Hamtaro affiche une base de secours sans inventer de ratios.";
      } else if (samples < 5 || confidence < 45) {
        tier = 'fragile';
        badge = 'Fragile';
        note = `Seulement ${samples} decklist${samples > 1 ? 's' : ''} exploitable${samples > 1 ? 's' : ''}. Utilise cette base comme piste, pas comme liste de référence.`;
      } else if (samples < 12 || confidence < 70) {
        tier = 'usable';
        badge = 'Utilisable';
        note = `${samples} decklists analysées · confiance ${confidence} %. La structure est utile mais certains slots peuvent encore bouger.`;
      }

      cockpit.dataset.tier = tier;

      const badgeEl = $('[data-db-quality-badge]');
      const noteEl = $('[data-db-quality-note]');
      const samplesEl = $('[data-db-quality-samples]');
      const cardsEl = $('[data-db-quality-cards]');
      const mainEl = $('[data-db-quality-main]');
      const recoveryEl = $('[data-db-quality-recovery]');

      if (badgeEl) badgeEl.textContent = badge;
      if (noteEl) noteEl.textContent = note;
      if (samplesEl) samplesEl.textContent = samples ? String(samples) : '0';
      if (cardsEl) cardsEl.textContent = coverage ? String(coverage) : '—';
      if (mainEl) mainEl.textContent = structureKnown ? `${coreSlots} · ${frequentSlots} · ${flexSlots}` : '—';

      const recovery = a.recovery || {};
      if (recoveryEl) {
        if (recovery.attempted && recovery.chosen === 'expanded') {
          recoveryEl.textContent = `${Number(recovery.initial_samples || 0)} → ${Number(recovery.final_samples || 0)}`;
        } else if (recovery.attempted && recovery.retry_failed) {
          recoveryEl.textContent = 'Échec du retry';
        } else if (recovery.attempted) {
          recoveryEl.textContent = 'Aucun gain';
        } else {
          recoveryEl.textContent = 'Non nécessaire';
        }
      }
    };

    root.addEventListener('click', (event) => {
      const maxCoverage = event.target.closest('[data-db-max-coverage]');
      if (maxCoverage) {
        if (els.days) els.days.value = '';
        if (els.limit) els.limit.value = '96';
        if (els.tournamentOnly) els.tournamentOnly.checked = false;
        state.variant = '';
        if (els.clearVariant) els.clearVariant.hidden = true;
        analyze({ preserveVariant: false });
        return;
      }

      const cardsJump = event.target.closest('[data-db-quality-cards-jump]');
      if (cardsJump) {
        jumpTo('db-library');
      }
    });

'''
    text = insert_before_once(text, "    const renderAnalysis = () => {\n", marker_and_renderer, "renderer qualité JS")

    render_warning = "        renderWarnings(a.warnings);\n"
    text = replace_once(
        text,
        render_warning,
        render_warning + "      renderQualityCockpit();\n",
        "appel cockpit qualité",
    )

    sample_anchor = "        const sampleCount = Number(a.samples_analyzed || 0);\n"
    structure = "        const hasStructure = !a.degraded && sampleCount > 0 && (coreSlots > 0 || frequentSlots > 0 || flexSlots > 0 || Number(mainProfile.observed_unique_cards || 0) > 0);\n"
    text = replace_once(text, sample_anchor, sample_anchor + structure, "détection structure overview")

    old_note = '''        if (els.overviewNote) {\n            els.overviewNote.textContent = a.degraded\n                ? 'Reconstruction TCG partielle : les cartes résolues sont visibles, mais Hamtaro n’invente pas de statistiques.'\n                : `${sampleCount} listes TCG uniques · ${coreSlots + frequentSlots} slots Main plutôt stables · ${flexSlots} slots flex estimés.`;\n        }\n'''
    new_note = '''        if (els.overviewNote) {\n            els.overviewNote.textContent = !hasStructure\n                ? 'Structure Main non déterminée : Hamtaro masque les slots plutôt que d’afficher un faux 0.'\n                : `${sampleCount} listes TCG uniques · ${coreSlots + frequentSlots} slots Main plutôt stables · ${flexSlots} slots flex estimés.`;\n        }\n'''
    text = replace_once(text, old_note, new_note, "note overview sans faux zéro")

    text = text.replace("<span><b>${coreSlots}</b> slots Core</span>", "<span><b>${hasStructure ? coreSlots : '—'}</b> slots Core</span>", 1)
    text = text.replace("<span><b>${flexSlots}</b> slots Flex</span>", "<span><b>${hasStructure ? flexSlots : '—'}</b> slots Flex</span>", 1)

    old_degraded_step = '''            if (a.degraded) {\n                title = 'Données encore partielles';\n                note = 'Explore le pool TCG retrouvé et relance plus tard : la base Hamtaro s’enrichit au fil des recherches.';\n                action = '<button type="button" data-db-next-cards>Voir les cartes retrouvées</button>';\n            }'''
    new_degraded_step = '''            if (a.degraded) {\n                title = 'Données encore partielles';\n                note = 'Hamtaro peut tenter une recherche plus large avant de te laisser sur une base de secours.';\n                action = '<button type="button" data-db-max-coverage>Relancer en couverture maximale</button>';\n            }'''
    text = replace_once(text, old_degraded_step, new_degraded_step, "prochaine étape données partielles")

    return text


def patch_css(text: str) -> str:
    if MARK in text:
        return text

    block = r'''

/* --- HAMTARO DECK LAB V10: quality cockpit --- */
.db-quality-cockpit {
    position: relative;
    overflow: hidden;
    margin: 18px 0 22px;
    padding: 20px;
    border: 1px solid rgba(148, 163, 184, .2);
    border-radius: 24px;
    background:
        radial-gradient(circle at 12% 0%, rgba(99, 102, 241, .16), transparent 34%),
        linear-gradient(145deg, rgba(15, 23, 42, .96), rgba(17, 24, 39, .88));
    box-shadow: 0 18px 50px rgba(2, 6, 23, .18);
}

.db-quality-cockpit::after {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: linear-gradient(110deg, rgba(255,255,255,.025), transparent 30%, transparent 70%, rgba(255,255,255,.018));
}

.db-quality-head,
.db-quality-actions {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
}

.db-quality-head h3 {
    margin: 4px 0 6px;
    font-size: clamp(1.08rem, 2vw, 1.35rem);
}

.db-quality-head p {
    margin: 0;
    max-width: 760px;
    color: rgba(226, 232, 240, .78);
}

.db-quality-badge {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    min-height: 34px;
    padding: 7px 12px;
    border-radius: 999px;
    font-size: .82rem;
    font-weight: 800;
    letter-spacing: .02em;
    border: 1px solid rgba(148, 163, 184, .24);
    background: rgba(15, 23, 42, .72);
}

.db-quality-grid {
    position: relative;
    z-index: 1;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    margin: 18px 0;
}

.db-quality-grid article {
    min-width: 0;
    padding: 14px;
    border-radius: 17px;
    border: 1px solid rgba(148, 163, 184, .14);
    background: rgba(15, 23, 42, .48);
}

.db-quality-grid span,
.db-quality-grid small {
    display: block;
    color: rgba(203, 213, 225, .68);
}

.db-quality-grid span {
    font-size: .74rem;
    font-weight: 800;
    letter-spacing: .06em;
    text-transform: uppercase;
}

.db-quality-grid strong {
    display: block;
    margin: 6px 0 3px;
    font-size: 1.22rem;
    line-height: 1.2;
}

.db-quality-grid small {
    font-size: .72rem;
    line-height: 1.35;
}

.db-quality-cockpit[data-tier="solid"] .db-quality-badge {
    border-color: rgba(34, 197, 94, .38);
    background: rgba(22, 101, 52, .2);
}

.db-quality-cockpit[data-tier="usable"] .db-quality-badge {
    border-color: rgba(59, 130, 246, .38);
    background: rgba(30, 64, 175, .2);
}

.db-quality-cockpit[data-tier="fragile"] .db-quality-badge {
    border-color: rgba(245, 158, 11, .4);
    background: rgba(146, 64, 14, .22);
}

.db-quality-cockpit[data-tier="danger"] .db-quality-badge {
    border-color: rgba(244, 63, 94, .4);
    background: rgba(136, 19, 55, .22);
}

@media (max-width: 900px) {
    .db-quality-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 620px) {
    .db-quality-cockpit {
        padding: 16px;
        border-radius: 20px;
    }

    .db-quality-head,
    .db-quality-actions {
        align-items: stretch;
        flex-direction: column;
    }

    .db-quality-badge {
        align-self: flex-start;
    }

    .db-quality-grid {
        grid-template-columns: 1fr;
    }

    .db-quality-actions .db-secondary-button,
    .db-quality-actions .db-link-button {
        width: 100%;
    }
}
'''
    return text.rstrip() + block + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Installe Hamtaro Deck Lab V10 dans un checkout du dépôt Hamtaro.")
    parser.add_argument("--root", default=".", help="racine du dépôt Hamtaro (défaut: dossier courant)")
    parser.add_argument("--dry-run", action="store_true", help="vérifie et prépare les patchs sans écrire")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    missing = [str(p) for p in TARGETS if not (root / p).is_file()]
    if missing:
        die("fichiers manquants: " + ", ".join(missing))

    original = {p: (root / p).read_text(encoding="utf-8") for p in TARGETS}

    # Build every patched file in memory first so a failed anchor never leaves a half-install.
    patched = {
        ROUTES: patch_routes(original[ROUTES]),
        HTML: patch_html(original[HTML]),
        CSS: patch_css(original[CSS]),
        JS: patch_js(original[JS]),
    }

    if args.dry_run:
        changed = [str(p) for p in TARGETS if patched[p] != original[p]]
        print("[V10] Dry-run OK.")
        print("[V10] Fichiers qui seraient modifiés:")
        for p in changed:
            print("  -", p)
        return 0

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = root / f".deck_builder_v10_backup_{stamp}"
    for p in TARGETS:
        dest = backup_dir / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / p, dest)

    for p in TARGETS:
        (root / p).write_text(patched[p], encoding="utf-8")

    print(f"[V10] Backup: {backup_dir.name}")

    checks: list[tuple[str, list[str]]] = [
        ("Python routes", [sys.executable, "-m", "py_compile", str(ROUTES)]),
    ]
    if shutil.which("node"):
        checks.append(("JavaScript", ["node", "--check", str(JS)]))

    for label, cmd in checks:
        proc = subprocess.run(cmd, cwd=root, text=True, capture_output=True)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            print(f"[V10] {label}: ECHEC. Restauration du backup...", file=sys.stderr)
            for p in TARGETS:
                shutil.copy2(backup_dir / p, root / p)
            die("validation échouée; les fichiers d'origine ont été restaurés.")
        print(f"[V10] {label}: OK")

    print("\n[V10] Installation terminée.")
    print("[V10] Changements: retry auto jusqu'à 96 decklists, cockpit de qualité, faux 0 slots supprimés, UI V10.")
    print("\nCommandes conseillées:")
    print("  git status")
    print("  git add services/deck_builder_routes.py web/templates/deck_builder.html web/static/deck_builder.css web/static/deck_builder.js")
    print('  git commit -m "Deck Builder V10: fiabilite et cockpit qualite"')
    print("  git push origin main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
