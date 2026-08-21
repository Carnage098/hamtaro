from __future__ import annotations

import json
import re
import unicodedata
from copy import deepcopy
from typing import Any


HALLOWEEN_TIERS: list[dict[str, Any]] = [
    {"id": "light-and-darkness-ritual", "label": "Rituel de la Lumière et des Ténèbres", "decks": ["light-and-darkness-ritual", "Memento", "Darklord"]},
    {"id": "S", "label": "S", "decks": ["Mitsurugi", "Memento", "Darklord"]},
    {"id": "A", "label": "A", "decks": ["D/D/D", "D/D", "Archfiend", "Fiendsmith", "Unchained", "Apophis", "Yubel", "Hecahands", "Azamina"]},
    {"id": "B", "label": "B", "decks": ["K9", "Snake-Eye", "Phantom Knights", "Mimighoul", "Thunder Dragon", "Goblin Biker", "Eldlich", "Zombie", "Wight"]},
    {"id": "B-", "label": "B-", "decks": ["Gimmick Puppet", "Shaddoll", "Ogdoadic", "Nemleria", "Regenesis", "Fabled"]},
    {"id": "C+", "label": "C+", "decks": ["Generaider", "Dark World", "Mayakashi", "Shiranui", "Call of the Haunted / Pumpking"]},
    {"id": "C", "label": "C", "decks": ["Altergeist", "Evil Eye", "Blackwing", "Eyes Restrict / Relinquished", "Evil HERO", "Vampire", "Scareclaw", "Myutant", "Fluffal / Frightfur"]},
    {"id": "D", "label": "D", "decks": ["Arcana Force", "Spirit Message", "Ghostrick"]},
]

HALLOWEEN_STAPLES: list[str] = [
    "Yo-kai Girl",
    "Knightmare",
    "Danger!",
    "Paleozoic",
    "Predaplant",
    "Entity",
    "Evilswarm",
    "True King",
    "Halloween Staples",
    "Zombie Staples",
]

# Une carte absente de cette table suit la banlist TCG normale.
# Les cartes génériques de cette table apparaissent visuellement sous
# « Staples compatibles » plutôt que dans le cœur de l'archétype.
HALLOWEEN_BANLIST_OVERRIDES: dict[str, list[dict[str, Any]]] = {
    "Darklord": [
        {"card": "Forbidden Crown", "limit": 3},
    ],
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

# Cartes génériques / staples : elles ne sont plus mélangées au cœur d'un deck.
GENERIC_HALLOWEEN_STAPLES: list[str] = [
    "Forbidden Crown",
    "Bonfire",
    "Gold Sarcophagus",
    "Chaos Space",
    "Skill Drain",
    "Rivalry of Warlords",
    "Gozen Match",
    "There Can Be Only One",
    "Chaos Ruler, the Chaotic Magical Dragon",
    "That Grass Looks Greener",
    "One for One",
    "Instant Fusion",
    "Foolish Burial",
    "King of the Feral Imps",
    "Card Destruction",
    "T.G. Hyper Librarian",
    "Borreload Savage Dragon",
    "Vanity's Emptiness",
    "Imperial Order",
    "Summon Limit",
    "Kaiser Colosseum",
    "Predaplant Verte Anaconda",
    "Card of Safe Return",
    "Knightmare Gryphon",
    "Dimension Shifter",
    "Return from the Different Dimension",
    "Sixth Sense",
    "Mystic Mine",
    "One Day of Peace",
    "Card of Demise",
    "Royal Oppression",
]

ZOMBIE_STAPLES: list[str] = [
    "Doomking Balerdroch",
    "Uni-Zombie",
    "Mezuki",
    "Gozuki",
    "Necroworld Banshee",
    "Glow-Up Bloom",
    "Jack-o-Bolan",
    "Changshi the Spiridao",
    "Alghoul Mazera",
    "Mad Mauler",
    "Zombie World",
    "Book of Life",
    "Vampire Sucker",
    "The Zombie Vampire",
    "Immortal Dragon",
    "Red-Eyes Zombie Dragon Lord",
    "Avendread Savior",
]

# Définition stricte du catalogue. Pour les archétypes simples, YGOPRODeck est
# interrogé uniquement via son tag d'archétype. Les cas sensibles sont listés
# explicitement afin d'éviter les faux positifs.
HALLOWEEN_CARD_CATALOG: dict[str, dict[str, Any]] = {
    "Mitsurugi": {"archetypes": ["Mitsurugi"]},
    "Memento": {"archetypes": ["Memento"]},
    "Darklord": {"archetypes": ["Darklord"], "staples": ["Forbidden Crown"]},
    "D/D/D": {"archetypes": ["D/D", "D/D/D"]},
    "D/D": {"archetypes": ["D/D", "D/D/D"]},
    "Archfiend": {
        "archetypes": ["Archfiend"],
        "name_contains": ["Archfiend"],
        "note": "Filtre strict : seules les cartes portant réellement « Archfiend » dans leur nom sont retenues dans le cœur du deck.",
    },
    "Fiendsmith": {"archetypes": ["Fiendsmith"]},
    "Unchained": {"archetypes": ["Unchained"]},
    "Apophis": {
        "core_exact": [
            "Apophis the Serpent",
            "Apophis the Swamp Deity",
            "Divine Serpent Apophis",
            "Embodiment of Apophis",
        ],
        "related_exact": [
            "The Man with the Mark",
            "Temple of the Kings",
            "Treasures of the Kings",
            "Defense of the Temple",
            "Dangers of the Divine",
            "Anubis the Last Judge",
            "Merciless Scorpion of Serket",
            "Mystical Beast of Serket",
        ],
        "note": "Le support Odion / Temple of the Kings est affiché comme support lié à Apophis.",
    },
    "Yubel": {"archetypes": ["Yubel"]},
    "Hecahands": {"archetypes": ["Hecahands"]},
    "Azamina": {"archetypes": ["Azamina"]},
    "K9": {"archetypes": ["K9"]},
    "Snake-Eye": {"archetypes": ["Snake-Eye"], "related_exact": ["Original Sinful Spoils - Snake-Eye"], "staples": ["Bonfire"]},
    "Phantom Knights": {"archetypes": ["The Phantom Knights"]},
    "Mimighoul": {"archetypes": ["Mimighoul"]},
    "Thunder Dragon": {"archetypes": ["Thunder Dragon"], "staples": ["Gold Sarcophagus", "Chaos Space"]},
    "Goblin Biker": {"archetypes": ["Goblin Biker"]},
    "Eldlich": {
        "archetypes": ["Eldlich", "Eldlixir", "Golden Land"],
        "staples": ["Skill Drain", "Rivalry of Warlords", "Gozen Match", "There Can Be Only One"],
    },
    "Zombie": {
        "core_exact": ["Zombie World", "Doomking Balerdroch", "Necroworld Banshee", "Glow-Up Bloom"],
        "staples": ZOMBIE_STAPLES + ["Chaos Ruler, the Chaotic Magical Dragon", "That Grass Looks Greener"],
        "note": "Le noyau Zombie World est séparé des staples Zombie génériques.",
    },
    "Wight": {
        "core_exact": [
            "Skull Servant",
            "King of the Skull Servants",
            "The Lady in Wight",
            "Wightprince",
            "Wightprincess",
            "Wightmare",
            "Wightbaking",
            "Wightlord",
            "Moissa Wight",
            "Wight Reanimator",
        ],
        "related_exact": ["Flame Ghost"],
        "staples": ["One for One", "That Grass Looks Greener"] + ZOMBIE_STAPLES,
    },
    "Gimmick Puppet": {
        "archetypes": ["Gimmick Puppet"],
        "related_exact": ["Number 40: Gimmick Puppet of Strings", "Number C40: Gimmick Puppet of Dark Strings"],
    },
    "Shaddoll": {"archetypes": ["Shaddoll"], "staples": ["Instant Fusion", "That Grass Looks Greener"]},
    "Ogdoadic": {"archetypes": ["Ogdoadic"], "staples": ["King of the Feral Imps", "Foolish Burial"]},
    "Nemleria": {
        "core_exact": [
            "Dreaming Nemleria",
            "Dream Tower of Princess Nemleria",
            "Sweet Dreams, Nemleria",
            "Nemleria Dream Defender - Oreiller",
            "Nemleria Dream Defender - Couette",
            "Nemleria Dream Devourer - Reveil",
            "Dreaming Reality of Nemleria, Realized",
            "Nemleria Louve",
            "Nemleria Repeter",
        ],
    },
    "Regenesis": {"archetypes": ["Regenesis"]},
    "Fabled": {"archetypes": ["Fabled"], "staples": ["Card Destruction", "T.G. Hyper Librarian", "Borreload Savage Dragon"]},
    "Generaider": {"archetypes": ["Generaider"]},
    "Dark World": {"archetypes": ["Dark World"], "staples": ["Card Destruction"]},
    "Mayakashi": {"archetypes": ["Mayakashi"], "staples": ZOMBIE_STAPLES},
    "Shiranui": {"archetypes": ["Shiranui"], "staples": ZOMBIE_STAPLES},
    "Call of the Haunted / Pumpking": {
        "core_exact": [
            "Call of the Haunted",
            "Pumpking the King of Grave Ghosts",
            "Pumpking the Great Ghost King",
            "Pumpking the King of Ghosts",
        ],
        "related_exact": [
            "Army of the Haunted",
            "Stare of the Snake Hair",
            "Great Mammoth of the Netherworld",
            "The Undying Legion",
            "Call of the Forgotten",
            "Ectoplasmic Fortification",
            "Vortex of Time",
            "Deadly Zombie Breath",
            "The Snake Hair",
            "Great Mammoth of Goldfine",
        ],
        "staples": ["Card of Safe Return"] + ZOMBIE_STAPLES,
        "note": "Le noyau MAZE OF MUERTOS est regroupé avec Call of the Haunted / Pumpking.",
    },
    "Altergeist": {"archetypes": ["Altergeist"], "staples": ["Vanity's Emptiness", "Imperial Order", "Summon Limit"]},
    "Evil Eye": {"archetypes": ["Evil Eye"], "staples": ["Kaiser Colosseum"]},
    "Blackwing": {"archetypes": ["Blackwing"]},
    "Eyes Restrict / Relinquished": {"archetypes": ["Relinquished", "Eyes Restrict"]},
    "Evil HERO": {"archetypes": ["Evil HERO"], "staples": ["Predaplant Verte Anaconda"]},
    "Vampire": {"archetypes": ["Vampire"], "staples": ["Card of Safe Return"] + ZOMBIE_STAPLES},
    "Scareclaw": {"archetypes": ["Scareclaw"], "staples": ["Knightmare Gryphon"]},
    "Myutant": {"archetypes": ["Myutant"], "staples": ["Dimension Shifter", "Return from the Different Dimension"]},
    "Fluffal / Frightfur": {"archetypes": ["Fluffal", "Frightfur", "Edge Imp"], "staples": ["Predaplant Verte Anaconda"]},
    "Arcana Force": {"archetypes": ["Arcana Force"], "staples": ["Sixth Sense"]},
    "Spirit Message": {
        "core_exact": [
            "Destiny Board",
            'Spirit Message "I"',
            'Spirit Message "N"',
            'Spirit Message "A"',
            'Spirit Message "L"',
        ],
        "related_exact": [
            "Dark Sanctuary",
            "Dark Spirit's Mastery",
            "Sentence of Doom",
            "Spirit Shield",
            "Spirit Illusion",
            "Dark Necrofear",
            "Curse Necrofear",
            "Dark Spirit of Banishment",
            "Dark Spirit of Malice",
            "The Duke of Demise",
            "Zoma the Spirit",
            "Zoma the Earthbound Spirit",
        ],
        "staples": ["Mystic Mine", "One Day of Peace", "Card of Demise"],
    },
    "Ghostrick": {"archetypes": ["Ghostrick"], "staples": ["Royal Oppression", "One Day of Peace", "Card of Demise"]},
    "Yo-kai Girl": {
        "core_exact": [
            "Ash Blossom & Joyous Spring",
            "Ghost Ogre & Snow Rabbit",
            "Ghost Belle & Haunted Mansion",
            "Ghost Reaper & Winter Cherries",
            "Ghost Sister & Spooky Dogwood",
            "Ghost Mourner & Moonlit Chill",
        ],
    },
    "Knightmare": {"archetypes": ["Knightmare"]},
    "Danger!": {"archetypes": ["Danger!"]},
    "Paleozoic": {"archetypes": ["Paleozoic"]},
    "Predaplant": {"archetypes": ["Predaplant"]},
    "Entity": {"archetypes": ["Entity"]},
    "Evilswarm": {"archetypes": ["Evilswarm"]},
    "True King": {"archetypes": ["True King"]},
    "Halloween Staples": {
        "core_exact": GENERIC_HALLOWEEN_STAPLES,
        "note": "Vue d'ensemble des cartes génériques. Leur limite peut dépendre du deck autorisé qui les utilise.",
        "staple_overview": True,
    },
    "Zombie Staples": {
        "core_exact": ZOMBIE_STAPLES,
        "note": "Staples Zombie fortes prévues pour accompagner les stratégies Zombie du format.",
        "staple_overview": True,
    },
}

HALLOWEEN_CANDIES: list[str] = [
    "Pot of Duality",
    "One Day of Peace",
    "Book of Moon",
    "Allure of Darkness",
    "Monster Reborn",
    "Upstart Goblin",
    "Creature Swap",
    "Forbidden Chalice",
]

HALLOWEEN_SPELLS: list[str] = [
    "Card Destruction",
    "Mind Control",
    "Enemy Controller",
    "Eradicator Epidemic Virus",
    "Offerings to the Doomed",
    "Dark Hole",
    "Terraforming",
    "Mystical Space Typhoon",
]


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", "and").replace("/", "-").replace("!", "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _image_slug(name: str) -> str:
    if name == "Call of the Haunted / Pumpking":
        return "call-of-the-haunted-pumpking"
    if name == "Zombie Staples":
        return "zombie-staples"
    if name == "Halloween Staples":
        return "halloween-staples"
    return _slug(name)


def _entry(name: str, tier: str) -> dict[str, Any]:
    return {
        "name": name,
        "slug": _slug(name),
        "image_url": f"/static/halloween/decks/{_image_slug(name)}.jpg",
        "tier": tier,
        "overrides": deepcopy(HALLOWEEN_BANLIST_OVERRIDES.get(name, [])),
    }


class HalloweenFormatService:
    def public_data(self) -> dict[str, Any]:
        tiers = deepcopy(HALLOWEEN_TIERS)
        for tier in tiers:
            tier["entries"] = [_entry(name, tier["id"]) for name in tier["decks"]]

        staples = [_entry(name, "STAPLE") for name in HALLOWEEN_STAPLES]

        catalog_payload = {
            "catalog": HALLOWEEN_CARD_CATALOG,
            "overrides": HALLOWEEN_BANLIST_OVERRIDES,
            "tiers": HALLOWEEN_TIERS,
            "staples": HALLOWEEN_STAPLES,
        }

        return {
            "id": "halloween",
            "name": "Halloween",
            "emoji": "🎃",
            "format_version": "2.0",
            "description": (
                "Format horrifique Hamtaro avec whitelist vérifiée, staples séparées, "
                "tier list locale modulable et banlist Halloween spéciale."
            ),
            "meta_left": "Whitelist Halloween V2",
            "meta_right": f"{sum(len(t['decks']) for t in HALLOWEEN_TIERS)} decks + {len(HALLOWEEN_STAPLES)} groupes de staples",
            "tiers": tiers,
            "staples": staples,
            "banlist_overrides": deepcopy(HALLOWEEN_BANLIST_OVERRIDES),
            "candies": list(HALLOWEEN_CANDIES),
            "spells": list(HALLOWEEN_SPELLS),
            "card_catalog_json": json.dumps(catalog_payload, ensure_ascii=False),
        }

    def whitelist_text(self) -> str:
        lines: list[str] = []
        for tier in HALLOWEEN_TIERS:
            lines.append(f"[{tier['label']}]")
            lines.extend(f"- {name}" for name in tier["decks"])
            lines.append("")
        lines.append("[STAPLES]")
        lines.extend(f"- {name}" for name in HALLOWEEN_STAPLES)
        return "\n".join(lines).rstrip() + "\n"

    def banlist_text(self) -> str:
        lines = [
            "FORMAT HALLOWEEN V2 - EXCEPTIONS DE BANLIST",
            "Toute carte absente suit la banlist TCG normale.",
            "Les cartes génériques sont classées visuellement dans les Staples.",
            "",
        ]
        for deck, entries in HALLOWEEN_BANLIST_OVERRIDES.items():
            lines.append(f"[{deck}]")
            for entry in entries:
                lines.append(f"- {entry['card']} : x{entry['limit']}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
