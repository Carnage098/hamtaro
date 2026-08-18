#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import re
import sys
from datetime import datetime
from pathlib import Path

SERVICE = Path("services/deck_builder_service.py")
ROUTES = Path("services/deck_builder_routes.py")
TEMPLATE = Path("web/templates/deck_builder.html")
TARGETS = (SERVICE, ROUTES, TEMPLATE)


def fail(message: str) -> None:
    raise RuntimeError(message)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: ancre attendue {count} fois au lieu de 1.")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        fail(f"{label}: début d'ancre introuvable.")
    end_pos = text.find(end, start_pos + len(start))
    if end_pos < 0:
        fail(f"{label}: fin d'ancre introuvable.")
    return text[:start_pos] + replacement + text[end_pos:]


def patch_service(text: str) -> str:
    # Nouvelle namespace = pages réseau V9/V10 refetchées après déploiement.
    if 'self.cache_namespace = "v101"' not in text:
        text, n = re.subn(
            r'self\.cache_namespace\s*=\s*"v(?:90|100|10|9)"',
            'self.cache_namespace = "v101"',
            text,
            count=1,
        )
        if n != 1:
            fail("service/cache_namespace: version actuelle non reconnue.")

    if "HamtaroDeckBuilder/10.1" not in text:
        text, n = re.subn(
            r'HamtaroDeckBuilder/(?:9\.0|10\.0)\s*\(\+public Yu-Gi-Oh TCG deck assistant\)',
            'HamtaroDeckBuilder/10.1 (+public Yu-Gi-Oh TCG deck assistant)',
            text,
            count=1,
        )
        if n != 1:
            fail("service/user_agent: version actuelle non reconnue.")

    alias_old = '            "blueeyes": ["Blue-Eyes", "Blue Eyes"],'
    alias_new = '''            "blueeyes": [
                "Blue-Eyes",
                "Blue Eyes",
                "Blue-Eyes White Dragon",
                "Primite Blue-Eyes",
                "Blue-Eyes Primite",
            ],
            "primiteblueeyes": [
                "Primite Blue-Eyes",
                "Blue-Eyes Primite",
                "Blue-Eyes",
                "Blue Eyes",
            ],'''
    if '"primiteblueeyes": [' not in text:
        text = replace_once(text, alias_old, alias_new, "service/aliases-blue-eyes")

    format_start = "    @staticmethod\n    def _deck_primer_context"
    format_end = "    async def _deck_sample_from_url"
    format_block = r'''    @staticmethod
    def _deck_primer_context(body: str) -> dict[str, str]:
        # Contexte local au deck : jamais la navigation globale entière.
        text = html_lib.unescape(body)
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        lower = text.casefold()

        anchor_kind = "none"
        local = ""
        primer_pos = lower.find("deck primer")
        if primer_pos >= 0:
            anchor_kind = "primer"
            local = text[max(0, primer_pos - 300):primer_pos + 2600]
        else:
            # Sans Deck Primer, on n'accepte un bloc Main Deck que s'il est
            # précédé de champs propres au deck (Category/Tournament).
            for match in re.finditer(r"\bmain deck\b", lower):
                start = max(0, match.start() - 1800)
                candidate = text[start:match.start() + 300]
                candidate_lower = candidate.casefold()
                if "category:" in candidate_lower or "tournament:" in candidate_lower:
                    anchor_kind = "main"
                    local = candidate
                    break

        def field(label: str, stops: tuple[str, ...]) -> str:
            if not local:
                return ""
            escaped = "|".join(re.escape(stop) for stop in stops)
            match = re.search(
                rf"\b{re.escape(label)}:\s*(.+?)(?=\s+(?:{escaped})(?:\s|$)|$)",
                local,
                flags=re.I,
            )
            return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

        category = field(
            "Category",
            ("Creator:", "Tournament:", "Placement:", "Read More", "Toggle Master Duel View", "Main Deck"),
        )
        tournament = field(
            "Tournament",
            ("Placement:", "Read More", "Toggle Master Duel View", "Main Deck"),
        )
        placement = field(
            "Placement",
            ("Read More", "Toggle Master Duel View", "Main Deck"),
        )
        return {
            "local": local,
            "category": category,
            "tournament": tournament,
            "placement": placement,
            "anchor_kind": anchor_kind,
        }

    @staticmethod
    def _detect_sample_format(body: str, title: str = "") -> str:
        # Les champs structurés font foi. Sans eux, on ne regarde jamais
        # arbitrairement les premiers caractères de la page.
        ctx = DeckBuilderService._deck_primer_context(body)
        category = ctx.get("category", "").casefold()
        tournament = ctx.get("tournament", "").casefold()
        structured = " ".join(part for part in (category, tournament) if part).strip()

        if structured:
            scoped = structured
        elif ctx.get("anchor_kind") == "primer":
            scoped = f"{title} {ctx.get('local', '')}".casefold()
        else:
            scoped = str(title or "").casefold()

        non_tcg_rules = (
            ("genesys ocg", "genesys_ocg"),
            ("tournament meta decks (genesys ocg)", "genesys_ocg"),
            ("tournament meta decks (genesys)", "genesys"),
            ("genesys", "genesys"),
            ("asian-english ocg", "ocg_ae"),
            ("ocg-ae", "ocg_ae"),
            ("tournament meta decks (china)", "ocg_china"),
            ("china championship", "ocg_china"),
            ("tournament meta decks (ocg)", "ocg"),
            ("tournament meta decks ocg", "ocg"),
            ("ocg tournament", "ocg"),
            ("japan championship", "ocg"),
            ("asia championship", "ocg"),
            ("master duel", "master_duel"),
            ("rush duel", "rush"),
            ("speed duel", "speed"),
            ("edison format", "legacy"),
            ("goat format", "legacy"),
        )
        for marker, value in non_tcg_rules:
            if marker in scoped:
                return value

        tcg_markers = (
            "tournament meta decks (tcg)",
            "tournament meta decks",
            "wcq regional",
            "regional qualifier",
            "national championship",
            "world championship qualifier",
            "ycs ",
        )
        if any(marker in scoped for marker in tcg_markers):
            return "tcg"
        return "unknown"

'''
    if '"anchor_kind": anchor_kind' not in text:
        text = replace_between(text, format_start, format_end, format_block, "service/format-local")

    primary_old = '''        primary_parsed = sum(1 for sample in loaded if sample is not None)
        signature_names: list[str] = []'''
    primary_new = '''        primary_parsed = sum(1 for sample in loaded if sample is not None)
        # V10.1 : le fallback dépend des listes TCG/unknown potentiellement
        # utilisables, pas du nombre brut de pages parsées.
        primary_potential_tcg = sum(
            1
            for sample in loaded
            if sample is not None and sample.format_name in {"tcg", "unknown"}
        )
        signature_names: list[str] = []'''
    text = replace_once(text, primary_old, primary_new, "service/primary-potential-tcg")

    text = replace_once(
        text,
        "        if primary_parsed < min(4, limit):",
        "        if primary_potential_tcg < min(4, limit):",
        "service/signature-trigger",
    )

    after_old = '''        parsed_after_signature = sum(1 for sample in loaded if sample is not None)
        if parsed_after_signature < min(4, limit):'''
    after_new = '''        parsed_after_signature = sum(1 for sample in loaded if sample is not None)
        post_signature_potential_tcg = sum(
            1
            for sample in loaded
            if sample is not None and sample.format_name in {"tcg", "unknown"}
        )
        if post_signature_potential_tcg < min(4, limit):'''
    text = replace_once(text, after_old, after_new, "service/universal-trigger")

    validation_start = "        # Validation carte-par-carte TCG :"
    validation_end = "        deduped: dict[str, DeckSample] = {}"
    validation_block = r'''        # V10.1 : validation TCG robuste.
        # Format inconnu = validation stricte.
        # Page explicitement TCG = tolérance d'un seul passcode non résolu.
        live_ids = [cid for sample in live for cid in [*sample.main, *sample.extra, *sample.side]]
        tcg_cards = await self.card_data_by_ids(live_ids) if live_ids else {}
        known_tcg_ids = set(tcg_cards)
        tcg_compatible: list[DeckSample] = []
        card_incompatible = 0
        tcg_soft_accepted = 0
        missing_tcg_ids: Counter[int] = Counter()

        for sample in live:
            sample_ids = set(sample.main + sample.extra + sample.side)
            if not sample_ids:
                card_incompatible += 1
                continue

            missing_ids = sample_ids - known_tcg_ids
            if not missing_ids:
                tcg_compatible.append(sample)
                continue

            missing_tcg_ids.update(missing_ids)
            if sample.format_name == "tcg" and len(missing_ids) <= 1:
                tcg_compatible.append(sample)
                tcg_soft_accepted += 1
                continue

            card_incompatible += 1

'''
    if "tcg_soft_accepted = 0" not in text:
        text = replace_between(
            text,
            validation_start,
            validation_end,
            validation_block,
            "service/tcg-validation",
        )

    debug_anchor = '''            "deck_pages_parsed": sum(1 for sample in loaded if sample is not None),
            "signature_fallback_used": bool(signature_urls),'''
    debug_new = '''            "deck_pages_parsed": sum(1 for sample in loaded if sample is not None),
            "primary_parsed": primary_parsed,
            "primary_potential_tcg": primary_potential_tcg,
            "post_signature_potential_tcg": post_signature_potential_tcg,
            "format_scope_version": "v101-local",
            "signature_fallback_used": bool(signature_urls),'''
    text = replace_once(text, debug_anchor, debug_new, "service/debug-fallback")

    compat_anchor = '''            "tcg_incompatible_ignored": card_incompatible,
            "live_tcg_decks": len(tcg_compatible),'''
    compat_new = '''            "tcg_incompatible_ignored": card_incompatible,
            "tcg_soft_accepted": tcg_soft_accepted,
            "missing_tcg_ids_top": [
                {"card_id": card_id, "occurrences": count}
                for card_id, count in missing_tcg_ids.most_common(12)
            ],
            "live_tcg_decks": len(tcg_compatible),'''
    text = replace_once(text, compat_anchor, compat_new, "service/debug-card-validation")

    return text


def patch_routes(text: str) -> str:
    if '"version": "10.1"' not in text:
        text = replace_once(
            text,
            '                "version": "10.0",',
            '                "version": "10.1",',
            "routes/version",
        )

    feature_anchor = '''                    "analysis-quality-cockpit",
                    "punctuation-tolerant-archetype-aliases",'''
    feature_new = '''                    "analysis-quality-cockpit",
                    "format-local-scope-filtering",
                    "usable-tcg-sample-fallback-trigger",
                    "explicit-tcg-single-card-tolerance",
                    "blue-eyes-family-query-aliases",
                    "punctuation-tolerant-archetype-aliases",'''
    if '"format-local-scope-filtering"' not in text:
        text = replace_once(text, feature_anchor, feature_new, "routes/features-v101")
    return text


def patch_template(text: str) -> str:
    text, hero_count = re.subn(
        r"HAMTARO DECK LAB · V(?:9\.0|10\.0)",
        "HAMTARO DECK LAB · V10.1",
        text,
        count=1,
    )
    if hero_count == 0 and "HAMTARO DECK LAB · V10.1" not in text:
        fail("template/version-hero: version V9/V10 introuvable.")

    text, dock_count = re.subn(
        r"<small>Deck Lab V(?:9(?:\.0)?|10(?:\.0)?)</small>",
        "<small>Deck Lab V10.1</small>",
        text,
        count=1,
    )
    if dock_count == 0 and "<small>Deck Lab V10.1</small>" not in text:
        fail("template/version-dock: version du dock introuvable.")
    return text


def validate_texts(patched: dict[Path, str]) -> None:
    compile(patched[SERVICE], str(SERVICE), "exec")
    compile(patched[ROUTES], str(ROUTES), "exec")

    required_service = (
        'self.cache_namespace = "v101"',
        "primary_potential_tcg",
        "post_signature_potential_tcg",
        "tcg_soft_accepted",
        '"format_scope_version": "v101-local"',
        '"primiteblueeyes": [',
    )
    for marker in required_service:
        if marker not in patched[SERVICE]:
            fail(f"validation service: marqueur manquant: {marker}")

    if '"version": "10.1"' not in patched[ROUTES]:
        fail("validation routes: version 10.1 absente.")
    if "HAMTARO DECK LAB · V10.1" not in patched[TEMPLATE]:
        fail("validation template: hero V10.1 absent.")
    if "<small>Deck Lab V10.1</small>" not in patched[TEMPLATE]:
        fail("validation template: dock V10.1 absent.")


def load_and_patch(root: Path) -> tuple[dict[Path, str], dict[Path, str]]:
    originals: dict[Path, str] = {}
    for relative in TARGETS:
        path = root / relative
        if not path.is_file():
            fail(f"Fichier introuvable: {relative}")
        originals[relative] = path.read_text(encoding="utf-8")

    patched = {
        SERVICE: patch_service(originals[SERVICE]),
        ROUTES: patch_routes(originals[ROUTES]),
        TEMPLATE: patch_template(originals[TEMPLATE]),
    }
    validate_texts(patched)
    return originals, patched


def make_backup(root: Path, originals: dict[Path, str]) -> Path:
    backup = root / f".deck_builder_v101_backup_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    for relative, content in originals.items():
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return backup


def restore(root: Path, originals: dict[Path, str]) -> None:
    for relative, content in originals.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Installe Hamtaro Deck Builder V10.1.")
    parser.add_argument("--dry-run", action="store_true", help="Valide le patch sans modifier les fichiers.")
    parser.add_argument("--root", default=".", help="Racine du dépôt Hamtaro.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()

    try:
        originals, patched = load_and_patch(root)
    except Exception as exc:
        print(f"[V10.1] ERREUR: {exc}", file=sys.stderr)
        return 1

    changed = [relative for relative in TARGETS if originals[relative] != patched[relative]]
    if not changed:
        print("[V10.1] Déjà installé : aucun changement nécessaire.")
        return 0

    if args.dry_run:
        print("[V10.1] Dry-run OK.")
        print("[V10.1] Fichiers qui seraient modifiés:")
        for relative in changed:
            print(f"  - {relative}")
        print("[V10.1] Validation syntaxique Python: OK")
        return 0

    backup = make_backup(root, originals)
    print(f"[V10.1] Backup: {backup.relative_to(root)}")

    try:
        for relative in changed:
            (root / relative).write_text(patched[relative], encoding="utf-8")

        py_compile.compile(str(root / SERVICE), doraise=True)
        py_compile.compile(str(root / ROUTES), doraise=True)

        validate_texts({
            SERVICE: (root / SERVICE).read_text(encoding="utf-8"),
            ROUTES: (root / ROUTES).read_text(encoding="utf-8"),
            TEMPLATE: (root / TEMPLATE).read_text(encoding="utf-8"),
        })
    except Exception as exc:
        restore(root, originals)
        print(f"[V10.1] ERREUR pendant l'installation: {exc}", file=sys.stderr)
        print("[V10.1] Les fichiers d'origine ont été restaurés.", file=sys.stderr)
        return 1

    print("[V10.1] Python service/routes: OK")
    print("[V10.1] Installation terminée.")
    print(
        "[V10.1] Changements: filtre format local, fallback basé sur les listes TCG "
        "utilisables, alias Blue-Eyes/Primite, tolérance d'un passcode sur page TCG, cache renouvelé."
    )
    print("\nCommandes conseillées:")
    print("  git status")
    print(
        "  git add services/deck_builder_service.py "
        "services/deck_builder_routes.py web/templates/deck_builder.html"
    )
    print('  git commit -m "Deck Builder V10.1: moteur de recuperation TCG"')
    print("  git push origin main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
