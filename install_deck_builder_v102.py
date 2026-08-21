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
    if 'self.cache_namespace = "v102"' not in text:
        text, n = re.subn(
            r'self\.cache_namespace\s*=\s*"v101"',
            'self.cache_namespace = "v102"',
            text,
            count=1,
        )
        if n != 1:
            fail("service/cache_namespace: V10.1 attendu.")

    if "HamtaroDeckBuilder/10.2" not in text:
        text, n = re.subn(
            r'HamtaroDeckBuilder/10\.1\s*\(\+public Yu-Gi-Oh TCG deck assistant\)',
            'HamtaroDeckBuilder/10.2 (+public Yu-Gi-Oh TCG deck assistant)',
            text,
            count=1,
        )
        if n != 1:
            fail("service/user_agent: V10.1 attendu.")

    format_start = "    @staticmethod\n    def _detect_sample_format"
    format_end = "    async def _deck_sample_from_url"

    format_block = r'''    @staticmethod
    def _detect_sample_format(body: str, title: str = "") -> str:
        # V10.2 : un bouton "Master Duel View" n'est jamais une preuve de ruleset.
        ctx = DeckBuilderService._deck_primer_context(body)
        category = ctx.get("category", "").casefold()
        tournament = ctx.get("tournament", "").casefold()
        structured = " ".join(part for part in (category, tournament) if part).strip()

        local = ctx.get("local", "").casefold()
        for marker in (
            "toggle master duel view",
            "master duel view",
            "export to master duel",
            "download for master duel",
        ):
            local = local.replace(marker, " ")

        if structured:
            scoped = structured
        elif ctx.get("anchor_kind") == "primer":
            scoped = f"{title} {local}".casefold()
        else:
            scoped = str(title or "").casefold()

        non_tcg_rules = (
            ("genesys ocg", "genesys_ocg"),
            ("tournament meta decks (genesys ocg)", "genesys_ocg"),
            ("tournament meta decks (genesys)", "genesys"),
            ("genesys tournament", "genesys"),
            ("genesys deck", "genesys"),
            ("asian-english ocg", "ocg_ae"),
            ("ocg-ae", "ocg_ae"),
            ("tournament meta decks (china)", "ocg_china"),
            ("china championship", "ocg_china"),
            ("tournament meta decks (ocg)", "ocg"),
            ("tournament meta decks ocg", "ocg"),
            ("ocg tournament", "ocg"),
            ("japan championship", "ocg"),
            ("asia championship", "ocg"),
            ("master duel decks", "master_duel"),
            ("master duel meta", "master_duel"),
            ("master duel tournament", "master_duel"),
            ("rush duel", "rush"),
            ("speed duel", "speed"),
            ("edison format", "legacy"),
            ("goat format", "legacy"),
        )
        for marker, value in non_tcg_rules:
            if marker in scoped:
                return value

        if category.startswith("master duel"):
            return "master_duel"
        if category.startswith("genesys"):
            return "genesys"
        if category.startswith("ocg"):
            return "ocg"

        tcg_markers = (
            "tournament meta decks (tcg)",
            "wcq regional",
            "regional qualifier",
            "national championship",
            "world championship qualifier",
            "ycs ",
            "tcg tournament",
        )
        if any(marker in scoped for marker in tcg_markers):
            return "tcg"

        if "tournament meta decks" in scoped:
            return "tcg"

        return "unknown"

'''
    if "V10.2 : un bouton" not in text:
        text = replace_between(
            text,
            format_start,
            format_end,
            format_block,
            "service/format-v102",
        )

    validation_start = "        # V10.1 : validation TCG robuste."
    validation_end = "        deduped: dict[str, DeckSample] = {}"

    validation_block = r'''        # V10.2 : validation TCG + pertinence réelle de la requête.
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

        def _relevance_norm(value: object) -> str:
            return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

        relevance_aliases_raw = [str(query or "")]
        for value in locals().get("query_variants", []) or []:
            if value:
                relevance_aliases_raw.append(str(value))

        query_norm = _relevance_norm(query)
        relevance_aliases = {
            _relevance_norm(value)
            for value in relevance_aliases_raw
            if len(_relevance_norm(value)) >= 4
        }
        if len(query_norm) >= 4:
            relevance_aliases.add(query_norm)

        # Les mots trop génériques ne doivent jamais suffire seuls.
        noise_aliases = {
            "blue", "eyes", "eye", "white", "dragon", "dark", "red",
            "the", "with", "primite",
        }
        relevance_aliases = {
            alias for alias in relevance_aliases
            if alias not in noise_aliases
        }

        def _sample_text(sample: DeckSample) -> str:
            bits: list[str] = []
            for attr in ("title", "name", "variant", "url", "source_url"):
                value = getattr(sample, attr, "")
                if value:
                    bits.append(str(value))
            return _relevance_norm(" ".join(bits))

        def _card_name(card_id: int) -> str:
            card = tcg_cards.get(card_id)
            if isinstance(card, dict):
                return str(
                    card.get("name")
                    or card.get("name_en")
                    or card.get("source_name")
                    or ""
                )
            return str(getattr(card, "name", "") or "")

        relevance_kept: list[DeckSample] = []
        irrelevant_to_query = 0
        relevance_title_matches = 0
        relevance_card_matches = 0

        for sample in tcg_compatible:
            if not relevance_aliases:
                relevance_kept.append(sample)
                continue

            sample_text = _sample_text(sample)
            title_match = any(alias in sample_text for alias in relevance_aliases)

            related_card_ids: set[int] = set()
            for card_id in set(sample.main + sample.extra + sample.side):
                card_norm = _relevance_norm(_card_name(card_id))
                if card_norm and any(alias in card_norm for alias in relevance_aliases):
                    related_card_ids.add(card_id)

            if title_match:
                relevance_kept.append(sample)
                relevance_title_matches += 1
                continue

            # Sans titre correspondant, deux cartes distinctes de la famille
            # sont exigées : un splash isolé ne suffit plus.
            if len(related_card_ids) >= 2:
                relevance_kept.append(sample)
                relevance_card_matches += 1
                continue

            irrelevant_to_query += 1

        tcg_compatible = relevance_kept

'''
    if "V10.2 : validation TCG + pertinence réelle de la requête." not in text:
        text = replace_between(
            text,
            validation_start,
            validation_end,
            validation_block,
            "service/relevance-v102",
        )

    text = text.replace(
        '"format_scope_version": "v101-local",',
        '"format_scope_version": "v102-explicit",',
        1,
    )

    compat_anchor = '''            "tcg_soft_accepted": tcg_soft_accepted,
            "missing_tcg_ids_top": ['''
    compat_new = '''            "tcg_soft_accepted": tcg_soft_accepted,
            "irrelevant_to_query_ignored": irrelevant_to_query,
            "relevance_title_matches": relevance_title_matches,
            "relevance_card_matches": relevance_card_matches,
            "relevance_filter_version": "v102-query-family",
            "missing_tcg_ids_top": ['''
    if '"relevance_filter_version": "v102-query-family"' not in text:
        text = replace_once(text, compat_anchor, compat_new, "service/debug-relevance")

    live_anchor = '''            "live_tcg_decks": len(tcg_compatible),
            "stored_tcg_decks_reused":'''
    live_new = '''            "live_tcg_decks": len(tcg_compatible),
            "relevant_tcg_decks": len(tcg_compatible),
            "stored_tcg_decks_reused":'''
    if '"relevant_tcg_decks": len(tcg_compatible)' not in text:
        text = replace_once(text, live_anchor, live_new, "service/debug-relevant-count")

    return text


def patch_routes(text: str) -> str:
    if '"version": "10.2"' not in text:
        text = replace_once(
            text,
            '                "version": "10.1",',
            '                "version": "10.2",',
            "routes/version",
        )

    if '"query-relevance-gate"' not in text:
        feature_anchor = '                    "format-local-scope-filtering",'
        feature_new = '''                    "explicit-format-marker-filtering",
                    "query-relevance-gate",
                    "generic-fallback-noise-rejection",
                    "format-local-scope-filtering",'''
        text = replace_once(text, feature_anchor, feature_new, "routes/features-v102")
    return text


def patch_template(text: str) -> str:
    if "HAMTARO DECK LAB · V10.2" not in text:
        text = replace_once(
            text,
            "HAMTARO DECK LAB · V10.1",
            "HAMTARO DECK LAB · V10.2",
            "template/hero-version",
        )
    if "<small>Deck Lab V10.2</small>" not in text:
        text = replace_once(
            text,
            "<small>Deck Lab V10.1</small>",
            "<small>Deck Lab V10.2</small>",
            "template/dock-version",
        )
    return text


def validate_texts(patched: dict[Path, str]) -> None:
    compile(patched[SERVICE], str(SERVICE), "exec")
    compile(patched[ROUTES], str(ROUTES), "exec")

    required_service = (
        'self.cache_namespace = "v102"',
        "HamtaroDeckBuilder/10.2",
        "V10.2 : un bouton",
        "irrelevant_to_query = 0",
        '"relevance_filter_version": "v102-query-family"',
        '"format_scope_version": "v102-explicit"',
    )
    for marker in required_service:
        if marker not in patched[SERVICE]:
            fail(f"validation service: marqueur absent: {marker}")

    if '("master duel", "master_duel")' in patched[SERVICE]:
        fail("validation service: marqueur Master Duel trop générique encore présent.")

    if '"version": "10.2"' not in patched[ROUTES]:
        fail("validation routes: version 10.2 absente.")

    if "HAMTARO DECK LAB · V10.2" not in patched[TEMPLATE]:
        fail("validation template: V10.2 absente.")


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
    backup = root / f".deck_builder_v102_backup_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    for relative, content in originals.items():
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return backup


def restore(root: Path, originals: dict[Path, str]) -> None:
    for relative, content in originals.items():
        (root / relative).write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Installe Hamtaro Deck Builder V10.2.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()

    try:
        originals, patched = load_and_patch(root)
    except Exception as exc:
        print(f"[V10.2] ERREUR: {exc}", file=sys.stderr)
        return 1

    changed = [relative for relative in TARGETS if originals[relative] != patched[relative]]
    if not changed:
        print("[V10.2] Déjà installé : aucun changement nécessaire.")
        return 0

    if args.dry_run:
        print("[V10.2] Dry-run OK.")
        print("[V10.2] Fichiers qui seraient modifiés:")
        for relative in changed:
            print(f"  - {relative}")
        print("[V10.2] Validation syntaxique Python: OK")
        return 0

    backup = make_backup(root, originals)
    print(f"[V10.2] Backup: {backup.relative_to(root)}")

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
        print(f"[V10.2] ERREUR pendant l'installation: {exc}", file=sys.stderr)
        print("[V10.2] Fichiers restaurés.", file=sys.stderr)
        return 1

    print("[V10.2] Installation terminée.")
    print("[V10.2] Détection de format explicite: OK")
    print("[V10.2] Filtre de pertinence requête/deck: OK")
    print("[V10.2] Cache v102: OK")
    print("")
    print("Commandes conseillées:")
    print("  git status")
    print("  git add services/deck_builder_service.py services/deck_builder_routes.py web/templates/deck_builder.html")
    print('  git commit -m "Deck Builder V10.2: selection fiable des sources"')
    print("  git push origin main")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
