
(() => {
  const normalize = v => String(v || "").toLocaleLowerCase("fr").normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim().replace(/\s+/g, " ");
  const search = document.getElementById("halloween-search");
  const filters = [...document.querySelectorAll("[data-tier-filter]")];
  const cards = [...document.querySelectorAll("#halloween-whitelist .halloween-deck-card")];
  const sections = [...document.querySelectorAll("[data-tier-section]")];
  let activeTier = "all";
  const apply = () => {
    const q = normalize(search?.value || "");
    cards.forEach(card => {
      const okTier = activeTier === "all" || card.dataset.deckTier === activeTier;
      const okName = !q || normalize(card.dataset.deckName).includes(q);
      card.hidden = !(okTier && okName);
    });
    sections.forEach(section => {
      section.hidden = ![...section.querySelectorAll(".halloween-deck-card")].some(c => !c.hidden);
    });
  };
  filters.forEach(button => button.addEventListener("click", () => {
    activeTier = button.dataset.tierFilter || "all";
    filters.forEach(x => x.classList.toggle("is-active", x === button));
    apply();
  }));
  search?.addEventListener("input", apply);

  const state = {
    candy: localStorage.getItem("hamtaroHalloweenCandy") || "",
    spell: localStorage.getItem("hamtaroHalloweenSpell") || ""
  };
  const render = () => {
    document.querySelectorAll("[data-choice-group]").forEach(group => {
      const key = group.dataset.choiceGroup;
      group.querySelectorAll(".halloween-choice").forEach(btn => btn.classList.toggle("is-selected", btn.dataset.choice === state[key]));
    });
    const c = document.getElementById("halloween-candy-choice");
    const s = document.getElementById("halloween-spell-choice");
    if(c) c.textContent = state.candy || "Aucun";
    if(s) s.textContent = state.spell || "Aucun";
  };
  document.querySelectorAll("[data-choice-group]").forEach(group => {
    group.addEventListener("click", e => {
      const btn = e.target.closest(".halloween-choice");
      if(!btn) return;
      const key = group.dataset.choiceGroup;
      state[key] = btn.dataset.choice || "";
      localStorage.setItem(key === "candy" ? "hamtaroHalloweenCandy" : "hamtaroHalloweenSpell", state[key]);
      render();
    });
  });
  document.getElementById("halloween-copy-choice")?.addEventListener("click", async e => {
    const text = `Format Halloween — Bonbon : ${state.candy || "non choisi"} | Sort : ${state.spell || "non choisi"}`;
    try {
      await navigator.clipboard.writeText(text);
      e.currentTarget.textContent = "✅ Choix copiés";
      setTimeout(() => e.currentTarget.textContent = "Copier mes choix", 1500);
    } catch (_) {
      window.prompt("Copie tes choix :", text);
    }
  });
  render();
  apply();
})();

/* HAMTARO_HALLOWEEN_INTERACTIVE_V13:START */
(() => {
  if (window.__hamtaroHalloweenInteractiveV13) return;
  window.__hamtaroHalloweenInteractiveV13 = true;

  const normalize = (value) => String(value || "")
    .toLocaleLowerCase("fr")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[’‘]/g, "'")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");

  // ------------------------------------------------------------
  // 1) TIER LIST INTERACTIVE — 100 % locale à la page.
  //    Aucun localStorage, aucune API, aucune sauvegarde serveur.
  // ------------------------------------------------------------
  const officialTierOrder = ["S", "A", "B", "B-", "C+", "STAPLE", "C", "D"];
  const tierListSection = document.getElementById("tierlist");
  const tierImageWrap = tierListSection?.querySelector(".halloween-tierlist-image-wrap");

  const deckSourceCards = [...document.querySelectorAll("#halloween-whitelist .halloween-deck-card")];
  const stapleSourceCards = [...document.querySelectorAll("#staples .halloween-deck-card")];

  const defaultEntries = [];
  deckSourceCards.forEach((card) => {
    defaultEntries.push({
      name: card.dataset.deckName || card.querySelector(".halloween-deck-name")?.textContent?.trim() || "",
      tier: card.dataset.deckTier || card.querySelector(".halloween-tier-corner")?.textContent?.trim() || "C",
      image: card.querySelector("img")?.getAttribute("src") || "",
    });
  });
  stapleSourceCards.forEach((card) => {
    defaultEntries.push({
      name: card.querySelector(".halloween-deck-name")?.textContent?.trim() || "",
      tier: "STAPLE",
      image: card.querySelector("img")?.getAttribute("src") || "",
    });
  });

  // If an old build has not exposed Pumpking in the source DOM yet,
  // guarantee that it is still present in the interactive official board.
  if (!defaultEntries.some((entry) => normalize(entry.name).includes("pumpking"))) {
    defaultEntries.push({
      name: "Call of the Haunted / Pumpking",
      tier: "C+",
      image: "/static/halloween/decks/call-of-the-haunted-pumpking.jpg",
    });
  }

  let selectedTierTile = null;

  const tierClass = (tier) => ({
    "S": "is-s",
    "A": "is-a",
    "B": "is-b",
    "B-": "is-bminus",
    "C+": "is-cplus",
    "STAPLE": "is-staple",
    "C": "is-c",
    "D": "is-d",
  }[tier] || "is-c");

  const buildTierTile = (entry) => {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "halloween-live-tier-tile";
    tile.draggable = true;
    tile.dataset.deckName = entry.name;
    tile.dataset.originalTier = entry.tier;
    tile.title = `${entry.name} — glisser pour déplacer`;
    tile.innerHTML = `
      <span class="halloween-live-tier-art">
        <img src="${entry.image}" alt="Artwork ${entry.name}" loading="lazy" decoding="async">
      </span>
      <strong>${entry.name}</strong>
    `;

    tile.addEventListener("dragstart", (event) => {
      tile.classList.add("is-dragging");
      event.dataTransfer?.setData("text/plain", entry.name);
      event.dataTransfer.effectAllowed = "move";
    });
    tile.addEventListener("dragend", () => tile.classList.remove("is-dragging"));

    tile.addEventListener("click", () => {
      document.querySelectorAll(".halloween-live-tier-tile.is-selected")
        .forEach((item) => item.classList.remove("is-selected"));
      if (selectedTierTile === tile) {
        selectedTierTile = null;
        return;
      }
      selectedTierTile = tile;
      tile.classList.add("is-selected");
    });

    return tile;
  };

  const renderOfficialTierBoard = () => {
    if (!tierImageWrap || !defaultEntries.length) return;

    tierImageWrap.innerHTML = `
      <div class="halloween-live-tier-toolbar">
        <div>
          <strong>🎃 Ta tier list personnelle</strong>
          <small>Glisse les decks où tu veux. Rien n'est sauvegardé : quitter/recharger remet la version officielle.</small>
        </div>
        <div class="halloween-live-tier-actions">
          <select id="halloween-tier-target" aria-label="Déplacer le deck sélectionné">
            ${officialTierOrder.map(tier => `<option value="${tier}">${tier === "STAPLE" ? "Staple" : tier}</option>`).join("")}
          </select>
          <button type="button" id="halloween-tier-move">Déplacer</button>
          <button type="button" id="halloween-tier-reset">Réinitialiser</button>
        </div>
      </div>
      <div class="halloween-live-tier-board" id="halloween-live-tier-board"></div>
    `;

    const board = document.getElementById("halloween-live-tier-board");
    officialTierOrder.forEach((tier) => {
      const row = document.createElement("section");
      row.className = `halloween-live-tier-row ${tierClass(tier)}`;
      row.dataset.tier = tier;
      row.innerHTML = `
        <div class="halloween-live-tier-label">${tier === "STAPLE" ? "Staple" : tier}</div>
        <div class="halloween-live-tier-dropzone" data-tier-dropzone="${tier}"></div>
      `;
      board.appendChild(row);
    });

    defaultEntries.forEach((entry) => {
      const zone = board.querySelector(`[data-tier-dropzone="${CSS.escape(entry.tier)}"]`);
      zone?.appendChild(buildTierTile(entry));
    });

    board.querySelectorAll("[data-tier-dropzone]").forEach((zone) => {
      zone.addEventListener("dragover", (event) => {
        event.preventDefault();
        zone.classList.add("is-over");
      });
      zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
      zone.addEventListener("drop", (event) => {
        event.preventDefault();
        zone.classList.remove("is-over");
        const name = event.dataTransfer?.getData("text/plain");
        const tile = [...board.querySelectorAll(".halloween-live-tier-tile")]
          .find((item) => item.dataset.deckName === name);
        if (tile) zone.appendChild(tile);
      });

      // Mobile/touch fallback: select a tile, then tap/click a row.
      zone.parentElement?.querySelector(".halloween-live-tier-label")?.addEventListener("click", () => {
        if (selectedTierTile) {
          zone.appendChild(selectedTierTile);
          selectedTierTile.classList.remove("is-selected");
          selectedTierTile = null;
        }
      });
    });

    document.getElementById("halloween-tier-move")?.addEventListener("click", () => {
      if (!selectedTierTile) return;
      const target = document.getElementById("halloween-tier-target")?.value;
      const zone = board.querySelector(`[data-tier-dropzone="${CSS.escape(target)}"]`);
      if (zone) {
        zone.appendChild(selectedTierTile);
        selectedTierTile.classList.remove("is-selected");
        selectedTierTile = null;
      }
    });

    document.getElementById("halloween-tier-reset")?.addEventListener("click", renderOfficialTierBoard);
  };

  renderOfficialTierBoard();

  // bfcache can otherwise restore the user's temporary DOM when pressing Back.
  // Requirement: once the page is left, the official order must return.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });

  // ------------------------------------------------------------
  // 2) GALERIE DES CARTES AUTORISÉES AVEC IMAGES
  // ------------------------------------------------------------
  const CARD_API = "https://db.ygoprodeck.com/api/v7/cardinfo.php";

  const deckQueries = {
    "Mitsurugi": [{type:"archetype", value:"Mitsurugi"}],
    "Memento": [{type:"archetype", value:"Memento"}],
    "Darklord": [{type:"archetype", value:"Darklord"}],
    "D/D/D": [{type:"archetype", value:"D/D"}, {type:"archetype", value:"D/D/D"}],
    "D/D": [{type:"archetype", value:"D/D"}, {type:"archetype", value:"D/D/D"}],
    "Archfiend": [{type:"archetype", value:"Archfiend"}],
    "Fiendsmith": [{type:"archetype", value:"Fiendsmith"}],
    "Unchained": [{type:"archetype", value:"Unchained"}],
    "Apophis": [{type:"archetype", value:"Apophis"}],
    "Yubel": [{type:"archetype", value:"Yubel"}],
    "Hecahands": [{type:"archetype", value:"Hecahands"}],
    "Azamina": [{type:"archetype", value:"Azamina"}],
    "K9": [{type:"archetype", value:"K9"}],
    "Snake-Eye": [{type:"archetype", value:"Snake-Eye"}],
    "Phantom Knights": [{type:"archetype", value:"The Phantom Knights"}],
    "Mimighoul": [{type:"archetype", value:"Mimighoul"}],
    "Thunder Dragon": [{type:"archetype", value:"Thunder Dragon"}],
    "Goblin Biker": [{type:"archetype", value:"Goblin Biker"}],
    "Eldlich": [{type:"archetype", value:"Eldlich"}, {type:"archetype", value:"Eldlixir"}, {type:"archetype", value:"Golden Land"}],
    "Zombie": [{type:"race", value:"Zombie"}],
    "Wight": [{type:"archetype", value:"Skull Servant"}],
    "Gimmick Puppet": [{type:"archetype", value:"Gimmick Puppet"}],
    "Shaddoll": [{type:"archetype", value:"Shaddoll"}],
    "Ogdoadic": [{type:"archetype", value:"Ogdoadic"}],
    "Nemleria": [{type:"archetype", value:"Nemleria"}],
    "Regenesis": [{type:"archetype", value:"Regenesis"}],
    "Fabled": [{type:"archetype", value:"Fabled"}],
    "Generaider": [{type:"archetype", value:"Generaider"}],
    "Phantom Beast": [{type:"archetype", value:"Phantom Beast"}, {type:"archetype", value:"Mecha Phantom Beast"}],
    "Dark World": [{type:"archetype", value:"Dark World"}],
    "Mayakashi": [{type:"archetype", value:"Mayakashi"}],
    "Shiranui": [{type:"archetype", value:"Shiranui"}],
    "Call of the Haunted / Pumpking": [
      {type:"names", value:[
        "Call of the Haunted", "Pumpking the King of Ghosts", "Pumpking the Great Ghost King",
        "Armored Zombie", "Clown Zombie", "Dragon Zombie", "The Snake Hair",
        "Great Mammoth of Goldfine"
      ]}
    ],
    "Altergeist": [{type:"archetype", value:"Altergeist"}],
    "Evil Eye": [{type:"archetype", value:"Evil Eye"}],
    "Blackwing": [{type:"archetype", value:"Blackwing"}],
    "Eyes Restrict / Relinquished": [{type:"archetype", value:"Relinquished"}, {type:"archetype", value:"Eyes Restrict"}],
    "Evil HERO": [{type:"archetype", value:"Evil HERO"}],
    "Vampire": [{type:"archetype", value:"Vampire"}],
    "Scareclaw": [{type:"archetype", value:"Scareclaw"}],
    "Myutant": [{type:"archetype", value:"Myutant"}],
    "Fluffal / Frightfur": [{type:"archetype", value:"Fluffal"}, {type:"archetype", value:"Frightfur"}, {type:"archetype", value:"Edge Imp"}],
    "Arcana Force": [{type:"archetype", value:"Arcana Force"}],
    "Spirit Message": [{type:"archetype", value:"Destiny Board"}],
    "Ghostrick": [{type:"archetype", value:"Ghostrick"}],
    "Yo-kai Girl": [{type:"names", value:[
      "Ash Blossom & Joyous Spring", "Ghost Ogre & Snow Rabbit", "Ghost Belle & Haunted Mansion",
      "Ghost Reaper & Winter Cherries", "Ghost Sister & Spooky Dogwood", "Ghost Mourner & Moonlit Chill"
    ]}],
    "Knightmare": [{type:"archetype", value:"Knightmare"}],
    "Danger!": [{type:"archetype", value:"Danger!"}],
    "Paleozoic": [{type:"archetype", value:"Paleozoic"}],
    "Predaplant": [{type:"archetype", value:"Predaplant"}],
    "Entity": [{type:"fname", value:"Entity"}],
    "Evilswarm": [{type:"archetype", value:"Evilswarm"}],
    "True King": [{type:"archetype", value:"True King"}],
  };

  const cache = new Map();

  const fetchJson = async (url) => {
    const response = await fetch(url, {headers: {"Accept":"application/json"}});
    if (!response.ok) return [];
    const payload = await response.json();
    return Array.isArray(payload?.data) ? payload.data : [];
  };

  const fetchQuery = async (query) => {
    if (query.type === "names") {
      const chunks = await Promise.all(query.value.map((name) =>
        fetchJson(`${CARD_API}?name=${encodeURIComponent(name)}`)
      ));
      return chunks.flat();
    }
    const key = query.type === "race" ? "race" : query.type === "fname" ? "fname" : "archetype";
    let data = await fetchJson(`${CARD_API}?${key}=${encodeURIComponent(query.value)}`);
    // Fallback for newly-added archetypes if their archetype tag isn't normalized yet.
    if (!data.length && query.type === "archetype") {
      data = await fetchJson(`${CARD_API}?fname=${encodeURIComponent(query.value)}`);
    }
    return data;
  };

  const parseOverrideMap = () => {
    const map = new Map();
    document.querySelectorAll(".halloween-ban-card").forEach((details) => {
      const deck = details.querySelector("summary strong")?.textContent?.trim();
      if (!deck) return;
      const cards = new Map();
      details.querySelectorAll("li").forEach((li) => {
        const card = li.querySelector("span")?.textContent?.trim();
        const limitText = li.querySelector(".halloween-limit")?.textContent || "";
        const limit = Number((limitText.match(/\d+/) || [3])[0]);
        if (card) cards.set(normalize(card), limit);
      });
      map.set(normalize(deck), cards);
    });
    return map;
  };

  const overrideMap = parseOverrideMap();

  const tcgFormats = (card) => {
    const misc = Array.isArray(card.misc_info) ? card.misc_info[0] : null;
    return Array.isArray(misc?.formats) ? misc.formats : [];
  };

  const allowedLimitFor = (deckName, card) => {
    const special = overrideMap.get(normalize(deckName))?.get(normalize(card.name));
    if (special) return {limit: special, special: true};

    const status = card?.banlist_info?.ban_tcg || "";
    if (status === "Banned") return {limit: 0, special: false};
    if (status === "Limited") return {limit: 1, special: false};
    if (status === "Semi-Limited") return {limit: 2, special: false};
    return {limit: 3, special: false};
  };

  const uniqueCards = (cards) => {
    const seen = new Map();
    cards.forEach((card) => {
      const key = card?.id || normalize(card?.name);
      if (key && !seen.has(key)) seen.set(key, card);
    });
    return [...seen.values()];
  };

  const loadDeckCards = async (deckName) => {
    if (cache.has(deckName)) return cache.get(deckName);

    const queries = deckQueries[deckName] || [{type:"archetype", value:deckName}];
    let cards = uniqueCards((await Promise.all(queries.map(fetchQuery))).flat());

    // Include Halloween-special cards even when they are generic/outside the archetype.
    const specials = overrideMap.get(normalize(deckName));
    if (specials?.size) {
      const extra = await Promise.all([...specials.keys()].map(async (normalizedName) => {
        const original = [...document.querySelectorAll(".halloween-ban-card")].flatMap((details) => {
          const d = details.querySelector("summary strong")?.textContent?.trim();
          if (normalize(d) !== normalize(deckName)) return [];
          return [...details.querySelectorAll("li span")].map(x => x.textContent.trim());
        }).find(name => normalize(name) === normalizedName);
        return original ? fetchJson(`${CARD_API}?name=${encodeURIComponent(original)}`) : [];
      }));
      cards = uniqueCards(cards.concat(extra.flat()));
    }

    // When format metadata exists, avoid OCG-only cards.
    cards = cards.filter((card) => {
      const formats = tcgFormats(card);
      return !formats.length || formats.includes("TCG");
    });

    cards = cards
      .map(card => ({card, permission: allowedLimitFor(deckName, card)}))
      .filter(({permission}) => permission.limit > 0)
      .sort((a, b) => a.card.name.localeCompare(b.card.name, "fr"));

    cache.set(deckName, cards);
    return cards;
  };

  const createAllowedCardsSection = () => {
    if (document.getElementById("halloween-cards")) return;
    const whitelist = document.getElementById("whitelist");
    if (!whitelist) return;

    const section = document.createElement("section");
    section.id = "halloween-cards";
    section.className = "format-panel halloween-panel halloween-card-catalog";
    section.innerHTML = `
      <div class="format-section-heading">
        <div>
          <p class="format-kicker">GALERIE OFFICIELLE</p>
          <h2>🃏 Cartes autorisées</h2>
          <p class="format-muted">Choisis un deck pour voir les cartes de sa famille avec leur artwork et leur limite Halloween.</p>
        </div>
        <div class="halloween-card-catalog-tools">
          <select id="halloween-card-deck-select" aria-label="Choisir un deck"></select>
          <input id="halloween-card-search" class="format-search" type="search" placeholder="Rechercher une carte..." autocomplete="off">
        </div>
      </div>
      <div class="halloween-card-catalog-status" id="halloween-card-status">Choisis un deck pour charger ses cartes.</div>
      <div class="halloween-card-gallery" id="halloween-card-gallery"></div>
    `;

    whitelist.insertAdjacentElement("afterend", section);

    const nav = document.querySelector(".halloween-nav");
    if (nav && !nav.querySelector('a[href="#halloween-cards"]')) {
      const link = document.createElement("a");
      link.href = "#halloween-cards";
      link.textContent = "Cartes autorisées";
      const stapleLink = nav.querySelector('a[href="#staples"]');
      if (stapleLink) nav.insertBefore(link, stapleLink);
      else nav.appendChild(link);
    }

    const select = document.getElementById("halloween-card-deck-select");
    const allNames = [...new Set(defaultEntries.map(entry => entry.name))];
    select.innerHTML = `<option value="">— Choisir un deck —</option>` +
      allNames.map(name => `<option value="${name.replaceAll('"', '&quot;')}">${name}</option>`).join("");

    const search = document.getElementById("halloween-card-search");
    const gallery = document.getElementById("halloween-card-gallery");
    const status = document.getElementById("halloween-card-status");
    let currentEntries = [];

    const renderCards = () => {
      const q = normalize(search.value || "");
      const filtered = currentEntries.filter(({card}) => !q || normalize(card.name).includes(q));
      status.textContent = currentEntries.length
        ? `${filtered.length}/${currentEntries.length} carte(s) affichée(s)`
        : status.textContent;

      gallery.innerHTML = filtered.map(({card, permission}) => {
        const image = card.card_images?.[0]?.image_url_small || card.card_images?.[0]?.image_url || "";
        const badge = permission.special ? `Halloween x${permission.limit}` : `x${permission.limit}`;
        return `
          <article class="halloween-allowed-card">
            <div class="halloween-allowed-card-image">
              ${image ? `<img src="${image}" alt="${card.name}" loading="lazy" decoding="async">` : `<span>Image indisponible</span>`}
              <span class="halloween-card-limit ${permission.special ? "is-special" : ""}">${badge}</span>
            </div>
            <strong>${card.name}</strong>
            <small>${card.type || ""}</small>
          </article>
        `;
      }).join("");
    };

    select.addEventListener("change", async () => {
      const deckName = select.value;
      gallery.innerHTML = "";
      currentEntries = [];
      if (!deckName) {
        status.textContent = "Choisis un deck pour charger ses cartes.";
        return;
      }

      status.textContent = `Chargement des cartes ${deckName}…`;
      try {
        currentEntries = await loadDeckCards(deckName);
        if (!currentEntries.length) {
          status.textContent = `Aucune carte résolue automatiquement pour ${deckName}.`;
          return;
        }
        renderCards();
      } catch (error) {
        status.textContent = `Impossible de charger les images pour le moment : ${error?.message || error}`;
      }
    });

    search.addEventListener("input", renderCards);

    // Clicking a whitelist or tier-list deck jumps directly to its cards.
    document.addEventListener("click", (event) => {
      const source = event.target.closest(".halloween-deck-card, .halloween-live-tier-tile");
      if (!source) return;
      const name = source.dataset.deckName || source.querySelector(".halloween-deck-name")?.textContent?.trim();
      if (!name || !allNames.includes(name)) return;
      // Don't hijack drag interactions in the live tier board.
      if (source.classList.contains("halloween-live-tier-tile") && source.classList.contains("is-dragging")) return;
      if (event.detail === 2 || event.altKey) {
        select.value = name;
        select.dispatchEvent(new Event("change"));
        section.scrollIntoView({behavior:"smooth", block:"start"});
      }
    });
  };

  createAllowedCardsSection();
})();
/* HAMTARO_HALLOWEEN_INTERACTIVE_V13:END */
