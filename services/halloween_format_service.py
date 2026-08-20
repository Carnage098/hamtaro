from __future__ import annotations

from copy import deepcopy
from typing import Any


HALLOWEEN_TIERS = [
    {"id": "S", "label": "S", "decks": ["Mitsurugi", "Memento", "Darklord"]},
    {"id": "A", "label": "A", "decks": ["D/D/D", "D/D", "Archfiend", "Fiendsmith", "Unchained", "Apophis", "Yubel", "Hecahands", "Azamina"]},
    {"id": "B", "label": "B", "decks": ["K9", "Snake-Eye", "Phantom Knights", "Mimighoul", "Thunder Dragon", "Goblin Biker", "Eldlich", "Zombie", "Wight"]},
    {"id": "B-", "label": "B-", "decks": ["Gimmick Puppet", "Shaddoll", "Ogdoadic", "Nemleria", "Regenesis", "Fabled"]},
    {"id": "C+", "label": "C+", "decks": ["Generaider", "Phantom Beast", "Dark World", "Mayakashi", "Shiranui", "Call of the Haunted / Pumpking"]},
    {"id": "C", "label": "C", "decks": ["Altergeist", "Evil Eye", "Blackwing", "Eyes Restrict / Relinquished", "Evil HERO", "Vampire", "Scareclaw", "Myutant", "Fluffal / Frightfur"]},
    {"id": "D", "label": "D", "decks": ["Arcana Force", "Spirit Message", "Ghostrick"]},
]

HALLOWEEN_STAPLES = [
    "Yo-kai Girl", "Knightmare", "Danger!", "Paleozoic",
    "Predaplant", "Entity", "Evilswarm", "True King",
]

HALLOWEEN_BANLIST_OVERRIDES = {
    "Archfiend": [
        {"card": "Hot Red Dragon Archfiend King Calamity", "limit": 1},
    ],
    "Yubel": [
        {"card": "Phantom of Yubel", "limit": 2},
    ],
    "K9": [
        {"card": "K9-04 Noroi", "limit": 1},
        {"card": "K9-66a Jokul", "limit": 2},
        {"card": "A Case for K9", "limit": 1},
    ],
    "Snake-Eye": [
        {"card": "Original Sinful Spoils - Snake-Eye", "limit": 1},
        {"card": "Bonfire", "limit": 2},
    ],
    "Thunder Dragon": [
        {"card": "Gold Sarcophagus", "limit": 2},
        {"card": "Chaos Space", "limit": 2},
    ],
    "Eldlich": [
        {"card": "Skill Drain", "limit": 2},
        {"card": "Rivalry of Warlords", "limit": 2},
        {"card": "Gozen Match", "limit": 2},
        {"card": "There Can Be Only One", "limit": 1},
    ],
    "Zombie": [
        {"card": "Chaos Ruler, the Chaotic Magical Dragon", "limit": 1},
        {"card": "That Grass Looks Greener", "limit": 2},
    ],
    "Wight": [
        {"card": "One for One", "limit": 2},
        {"card": "That Grass Looks Greener", "limit": 2},
    ],
    "Gimmick Puppet": [
        {"card": "CXyz Gimmick Puppet Fanatix Machinix", "limit": 1},
        {"card": "Gimmick Puppet Nightmare", "limit": 1},
        {"card": "Number 40: Gimmick Puppet of Strings", "limit": 2},
        {"card": "Number C40: Gimmick Puppet of Dark Strings", "limit": 2},
    ],
    "Shaddoll": [
        {"card": "Instant Fusion", "limit": 2},
        {"card": "That Grass Looks Greener", "limit": 2},
    ],
    "Ogdoadic": [
        {"card": "King of the Feral Imps", "limit": 1},
        {"card": "Foolish Burial", "limit": 2},
    ],
    "Fabled": [
        {"card": "Card Destruction", "limit": 2},
        {"card": "T.G. Hyper Librarian", "limit": 2},
        {"card": "Borreload Savage Dragon", "limit": 1},
    ],
    "Phantom Beast": [
        {"card": "Mecha Phantom Beast Auroradon", "limit": 1},
    ],
    "Dark World": [
        {"card": "Card Destruction", "limit": 2},
    ],
    "Altergeist": [
        {"card": "Vanity's Emptiness", "limit": 1},
        {"card": "Imperial Order", "limit": 1},
        {"card": "Summon Limit", "limit": 1},
    ],
    "Evil Eye": [
        {"card": "Kaiser Colosseum", "limit": 1},
    ],
    "Blackwing": [
        {"card": "Blackwing - Gofu the Vague Shadow", "limit": 1},
    ],
    "Evil HERO": [
        {"card": "Predaplant Verte Anaconda", "limit": 1},
    ],
    "Vampire": [
        {"card": "Card of Safe Return", "limit": 1},
    ],
    "Scareclaw": [
        {"card": "Knightmare Gryphon", "limit": 1},
    ],
    "Myutant": [
        {"card": "Dimension Shifter", "limit": 2},
        {"card": "Return from the Different Dimension", "limit": 1},
    ],
    "Fluffal / Frightfur": [
        {"card": "Predaplant Verte Anaconda", "limit": 1},
    ],
    "Arcana Force": [
        {"card": "Sixth Sense", "limit": 1},
    ],
    "Spirit Message": [
        {"card": "Mystic Mine", "limit": 1},
        {"card": "One Day of Peace", "limit": 2},
        {"card": "Card of Demise", "limit": 2},
    ],
    "Ghostrick": [
        {"card": "Royal Oppression", "limit": 1},
        {"card": "One Day of Peace", "limit": 2},
        {"card": "Card of Demise", "limit": 2},
    ],
    "Call of the Haunted / Pumpking": [
        {"card": "Card of Safe Return", "limit": 1},
    ],
    "True King": [
        {"card": "True King of All Calamities", "limit": 1},
    ],
}

HALLOWEEN_CANDIES = [
    "Pot of Duality", "One Day of Peace", "Book of Moon", "Allure of Darkness",
    "Monster Reborn", "Upstart Goblin", "Creature Swap", "Forbidden Chalice",
]
HALLOWEEN_SPELLS = [
    "Card Destruction", "Mind Control", "Enemy Controller", "Eradicator Epidemic Virus",
    "Offerings to the Doomed", "Dark Hole", "Terraforming", "Mystical Space Typhoon",
]


def _slug(value: str) -> str:
    import re
    import unicodedata
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", "and").replace("/", "-").replace("!", "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


class HalloweenFormatService:
    def public_data(self) -> dict[str, Any]:
        tiers = deepcopy(HALLOWEEN_TIERS)
        for tier in tiers:
            tier["entries"] = []
            for name in tier["decks"]:
                tier["entries"].append({
                    "name": name,
                    "slug": _slug(name),
                    "image_url": f"/static/halloween/decks/{_slug(name)}.jpg",
                    "tier": tier["id"],
                    "overrides": deepcopy(HALLOWEEN_BANLIST_OVERRIDES.get(name, [])),
                })

        staples = [{
            "name": name,
            "slug": _slug(name),
            "image_url": f"/static/halloween/decks/{_slug(name)}.jpg",
            "overrides": deepcopy(HALLOWEEN_BANLIST_OVERRIDES.get(name, [])),
        } for name in HALLOWEEN_STAPLES]

        return {
            "id": "halloween",
            "name": "Halloween",
            "emoji": "🎃",
            "format_version": "1.0",
            "description": "Format horrifique Hamtaro avec whitelist, staples dédiées et banlist Halloween spéciale.",
            "meta_left": "Whitelist Halloween",
            "meta_right": f"{sum(len(t['decks']) for t in HALLOWEEN_TIERS)} decks + {len(HALLOWEEN_STAPLES)} staples",
            "tierlist_image_url": "/static/halloween/tierlist_halloween.png",
            "tiers": tiers,
            "staples": staples,
            "banlist_overrides": deepcopy(HALLOWEEN_BANLIST_OVERRIDES),
            "candies": list(HALLOWEEN_CANDIES),
            "spells": list(HALLOWEEN_SPELLS),
        }

    def whitelist_text(self) -> str:
        lines = []
        for tier in HALLOWEEN_TIERS:
            lines.append(f"[{tier['label']}]")
            lines.extend(f"- {name}" for name in tier["decks"])
            lines.append("")
        lines.append("[STAPLES]")
        lines.extend(f"- {name}" for name in HALLOWEEN_STAPLES)
        return "\n".join(lines).rstrip() + "\n"

    def banlist_text(self) -> str:
        lines = [
            "FORMAT HALLOWEEN - EXCEPTIONS DE BANLIST",
            "Toute carte absente suit la banlist TCG normale.",
            "",
        ]
        for deck, entries in HALLOWEEN_BANLIST_OVERRIDES.items():
            lines.append(f"[{deck}]")
            for entry in entries:
                lines.append(f"- {entry['card']} : x{entry['limit']}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
