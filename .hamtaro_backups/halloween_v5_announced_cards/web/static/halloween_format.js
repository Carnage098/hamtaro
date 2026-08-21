(() => {
  const normalize = (value) => String(value || "")
    .toLocaleLowerCase("fr")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[’‘]/g, "'")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");

  const CARD_API = "https://db.ygoprodeck.com/api/v7/cardinfo.php";
  const catalogNode = document.getElementById("halloween-card-data");
  let config = {catalog: {}, overrides: {}, global_bans: [], representative_cards: {}, tiers: [], staples: []};
  try {
    config = JSON.parse(catalogNode?.textContent || "{}");
  } catch (error) {
    console.error("Halloween catalog JSON invalide", error);
  }

  // ------------------------------------------------------------
  // Whitelist search / filters
  // ------------------------------------------------------------
  const whitelistSearch = document.getElementById("halloween-search");
  const filters = [...document.querySelectorAll("[data-tier-filter]")];
  const whitelistCards = [...document.querySelectorAll("#halloween-whitelist .halloween-deck-card")];
  const tierSections = [...document.querySelectorAll("[data-tier-section]")];
  let activeTier = "all";

  const applyWhitelistFilter = () => {
    const q = normalize(whitelistSearch?.value || "");
    whitelistCards.forEach((card) => {
      const okTier = activeTier === "all" || card.dataset.deckTier === activeTier;
      const okName = !q || normalize(card.dataset.deckName).includes(q);
      card.hidden = !(okTier && okName);
    });
    tierSections.forEach((section) => {
      section.hidden = ![...section.querySelectorAll(".halloween-deck-card")].some((card) => !card.hidden);
    });
  };

  filters.forEach((button) => button.addEventListener("click", () => {
    activeTier = button.dataset.tierFilter || "all";
    filters.forEach((item) => item.classList.toggle("is-active", item === button));
    applyWhitelistFilter();
  }));
  whitelistSearch?.addEventListener("input", applyWhitelistFilter);
  applyWhitelistFilter();

  // ------------------------------------------------------------
  // Tier list locale / temporaire
  // ------------------------------------------------------------
  const tierBoard = document.getElementById("halloween-live-tier-board");
  const resetTierButton = document.getElementById("halloween-tier-reset");
  const moveTierButton = document.getElementById("halloween-tier-move");
  const targetTierSelect = document.getElementById("halloween-tier-target");
  const selectedDeckText = document.getElementById("halloween-selected-deck");
  let selectedTierTile = null;

  const officialTierSnapshot = tierBoard?.innerHTML || "";

  const selectTierTile = (tile) => {
    tierBoard?.querySelectorAll(".halloween-live-tier-tile.is-selected").forEach((item) => item.classList.remove("is-selected"));
    selectedTierTile = tile || null;
    if (selectedTierTile) selectedTierTile.classList.add("is-selected");
    if (selectedDeckText) selectedDeckText.textContent = selectedTierTile ? selectedTierTile.dataset.deckName : "Aucun deck sélectionné";
  };

  const wireTierBoard = () => {
    if (!tierBoard) return;

    tierBoard.querySelectorAll(".halloween-live-tier-tile").forEach((tile) => {
      tile.addEventListener("dragstart", (event) => {
        tile.classList.add("is-dragging");
        event.dataTransfer?.setData("text/plain", tile.dataset.deckName || "");
        if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
      });
      tile.addEventListener("dragend", () => tile.classList.remove("is-dragging"));
      tile.addEventListener("click", () => selectTierTile(selectedTierTile === tile ? null : tile));
      tile.addEventListener("dblclick", () => openDeckCatalog(tile.dataset.deckName || ""));
    });

    tierBoard.querySelectorAll("[data-tier-dropzone]").forEach((zone) => {
      zone.addEventListener("dragover", (event) => {
        event.preventDefault();
        zone.classList.add("is-over");
      });
      zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
      zone.addEventListener("drop", (event) => {
        event.preventDefault();
        zone.classList.remove("is-over");
        const deckName = event.dataTransfer?.getData("text/plain") || "";
        const tile = [...tierBoard.querySelectorAll(".halloween-live-tier-tile")]
          .find((item) => item.dataset.deckName === deckName);
        if (tile) zone.appendChild(tile);
      });
    });

    tierBoard.querySelectorAll(".halloween-live-tier-label").forEach((label) => {
      label.addEventListener("click", () => {
        if (!selectedTierTile) return;
        const zone = label.parentElement?.querySelector("[data-tier-dropzone]");
        zone?.appendChild(selectedTierTile);
        selectTierTile(null);
      });
    });
  };

  wireTierBoard();

  resetTierButton?.addEventListener("click", () => {
    if (!tierBoard) return;
    tierBoard.innerHTML = officialTierSnapshot;
    selectTierTile(null);
    wireTierBoard();
    upgradeTierArtworks();
  });

  moveTierButton?.addEventListener("click", () => {
    if (!selectedTierTile || !tierBoard) return;
    const tier = targetTierSelect?.value || "";
    const zone = tierBoard.querySelector(`[data-tier-dropzone="${CSS.escape(tier)}"]`);
    zone?.appendChild(selectedTierTile);
    selectTierTile(null);
  });

  // Safari/Chrome can restore a modified DOM from bfcache. Force official order back.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });

  // ------------------------------------------------------------
  // Card catalog resolution
  // ------------------------------------------------------------
  const cardCache = new Map();
  const queryCache = new Map();

  const fetchData = async (url) => {
    if (queryCache.has(url)) return queryCache.get(url);
    const promise = fetch(url, {headers: {Accept: "application/json"}})
      .then(async (response) => response.ok ? (await response.json())?.data || [] : [])
      .catch(() => []);
    queryCache.set(url, promise);
    return promise;
  };

  const fetchByName = async (name) => {
    const key = `name:${normalize(name)}`;
    if (cardCache.has(key)) return cardCache.get(key);
    const cards = await fetchData(`${CARD_API}?name=${encodeURIComponent(name)}`);
    const card = cards[0] || null;
    cardCache.set(key, card);
    return card;
  };

  const fetchByArchetype = async (archetype) => {
    const url = `${CARD_API}?archetype=${encodeURIComponent(archetype)}`;
    return fetchData(url);
  };

  const upgradeDeckArtwork = async (deckName, representativeName) => {
    let card = representativeName ? await fetchByName(representativeName) : null;
    if (!card) {
      const archetype = config.catalog?.[deckName]?.archetypes?.[0];
      if (archetype) {
        const cards = await fetchByArchetype(archetype);
        card = cards.find(isTCGCard) || cards[0] || null;
      }
    }
    if (!card) return;
    const image = card.card_images?.[0]?.image_url_cropped || card.card_images?.[0]?.image_url || card.card_images?.[0]?.image_url_small || "";
    if (!image) return;
    document.querySelectorAll(`.halloween-live-tier-tile[data-deck-name="${CSS.escape(deckName)}"] img, .halloween-deck-card[data-deck-name="${CSS.escape(deckName)}"] img`).forEach((img) => {
      img.src = image; img.decoding = "async";
    });
  };

  const upgradeTierArtworks = () => {
    Object.entries(config.representative_cards || {}).forEach(([deckName, representativeName]) => {
      if (deckName === "Call of the Haunted / Pumpking") return;
      upgradeDeckArtwork(deckName, representativeName);
    });
  };

  upgradeTierArtworks();

  const uniqueCards = (cards) => {
    const seen = new Map();
    cards.filter(Boolean).forEach((card) => {
      const key = card.id || normalize(card.name);
      if (key && !seen.has(key)) seen.set(key, card);
    });
    return [...seen.values()];
  };

  const isTCGCard = (card) => {
    const formats = card?.misc_info?.[0]?.formats;
    if (Array.isArray(formats) && formats.length) return formats.includes("TCG");

    const sets = Array.isArray(card?.card_sets) ? card.card_sets : [];
    if (sets.length) {
      return sets.some((set) => /-(?:EN|FR|DE|IT|PT|SP)\d/i.test(String(set?.set_code || "")));
    }

    // Some older records omit format metadata. The explicit per-deck exclusion list remains authoritative.
    return true;
  };

  const overrideForDeck = (deckName, cardName) => {
    const entries = config.overrides?.[deckName] || [];
    return entries.find((entry) => normalize(entry.card) === normalize(cardName)) || null;
  };

  const overrideUsers = (cardName) => Object.entries(config.overrides || {})
    .filter(([, entries]) => entries.some((entry) => normalize(entry.card) === normalize(cardName)))
    .map(([deck]) => deck);

  const tcgLimit = (card) => {
    const status = card?.banlist_info?.ban_tcg || "";
    if (status === "Banned") return 0;
    if (status === "Limited") return 1;
    if (status === "Semi-Limited") return 2;
    return 3;
  };

  const permissionFor = (deckName, card) => {
    const globallyBanned = new Set((config.global_bans || []).map(normalize));
    if (globallyBanned.has(normalize(card.name))) {
      return {limit: 0, special: true, globalBan: true, label: "INTERDITE"};
    }

    const special = overrideForDeck(deckName, card.name);
    if (special) return {limit: Number(special.limit), special: true, label: `Halloween x${special.limit}`};

    if (deckName === "Halloween Staples") {
      const users = overrideUsers(card.name);
      return {
        limit: tcgLimit(card),
        special: users.length > 0,
        contextOnly: users.length > 0,
        label: users.length > 0 ? "Selon deck" : `x${tcgLimit(card)}`,
        users,
      };
    }

    const limit = tcgLimit(card);
    return {limit, special: false, label: `x${limit}`};
  };

  const fetchExactList = async (names) => {
    const results = await Promise.all((names || []).map(fetchByName));
    return uniqueCards(results).filter(isTCGCard);
  };

  const fetchArchetypeList = async (archetypes, nameContains) => {
    const chunks = await Promise.all((archetypes || []).map(fetchByArchetype));
    let cards = uniqueCards(chunks.flat()).filter(isTCGCard);
    if (nameContains?.length) {
      cards = cards.filter((card) => nameContains.some((needle) => normalize(card.name).includes(normalize(needle))));
    }
    return cards;
  };

  const applyRuleExclusions = (rule, cards) => {
    const excluded = new Set((rule.exclude_exact || []).map(normalize));
    return uniqueCards(cards).filter((card) => !excluded.has(normalize(card.name)));
  };

  const loadCatalog = async (deckName) => {
    const rule = config.catalog?.[deckName];
    if (!rule) return {rule: {}, groups: []};

    const archetypeCards = await fetchArchetypeList(rule.archetypes || [], rule.name_contains || []);
    const exactCore = await fetchExactList(rule.core_exact || []);
    const core = applyRuleExclusions(rule, [...archetypeCards, ...exactCore]);
    const extra = applyRuleExclusions(rule, await fetchExactList(rule.extra_exact || []));
    const support = applyRuleExclusions(rule, await fetchExactList(rule.support_exact || []));
    const related = applyRuleExclusions(rule, await fetchExactList(rule.related_exact || []));
    const stapleArchetypeChunks = await Promise.all((rule.staple_archetypes || []).map(fetchByArchetype));
    const stapleArchetypeCards = uniqueCards(stapleArchetypeChunks.flat()).filter(isTCGCard);
    const staples = applyRuleExclusions(rule, [...stapleArchetypeCards, ...(await fetchExactList(rule.staples || []))]);

    const makeGroup = (key, title, cards) => {
      const decorated = cards
        .map((card) => ({card, permission: permissionFor(deckName, card)}))
        .filter(({permission}) => permission.limit > 0 || permission.contextOnly)
        .sort((a, b) => a.card.name.localeCompare(b.card.name, "fr"));
      return decorated.length ? {key, title, cards: decorated} : null;
    };

    return {
      rule,
      groups: [
        makeGroup("core", rule.core_title || (rule.staple_overview ? "Cartes de la catégorie" : "Cartes du deck"), core),
        makeGroup("extra", rule.extra_title || "Extra Deck", extra),
        makeGroup("support", rule.support_title || "Support", support),
        makeGroup("related", rule.related_title || "Related / Support lié", related),
        makeGroup("staples", "Staples compatibles", staples),
      ].filter(Boolean),
    };
  };

  const cardSelect = document.getElementById("halloween-card-deck-select");
  const cardSearch = document.getElementById("halloween-card-search");
  const cardStatus = document.getElementById("halloween-card-status");
  const cardSections = document.getElementById("halloween-card-sections");
  const cardNote = document.getElementById("halloween-card-note");
  let currentDeckName = "";
  let currentCatalog = {rule: {}, groups: []};

  const renderCardCatalog = () => {
    if (!cardSections || !cardStatus) return;
    const q = normalize(cardSearch?.value || "");
    let total = 0;
    let visible = 0;

    cardSections.innerHTML = currentCatalog.groups.map((group) => {
      total += group.cards.length;
      const cards = group.cards.filter(({card}) => !q || normalize(card.name).includes(q));
      visible += cards.length;
      if (!cards.length) return "";

      return `
        <section class="halloween-card-group" data-card-group="${group.key}">
          <h3>${group.title} <span>${cards.length} carte(s)</span></h3>
          <div class="halloween-card-gallery">
            ${cards.map(({card, permission}) => {
              const image = card.card_images?.[0]?.image_url_small || card.card_images?.[0]?.image_url || "";
              const specialClass = permission.contextOnly ? "is-context" : permission.special ? "is-special" : "";
              const users = permission.users?.length ? ` · ${permission.users.join(", ")}` : "";
              return `
                <button type="button" class="halloween-card-tile" data-card-id="${card.id || ""}" data-card-name="${card.name.replaceAll('"', '&quot;')}" data-group-kind="${group.key}">
                  <span class="halloween-card-image">
                    ${image ? `<img src="${image}" alt="${card.name}" loading="lazy" decoding="async">` : `<span class="no-image">Image indisponible</span>`}
                    <span class="halloween-card-limit ${specialClass}" title="${users}">${permission.label}</span>
                  </span>
                  <strong>${card.name}</strong>
                  <small>${card.type || ""}</small>
                </button>`;
            }).join("")}
          </div>
        </section>`;
    }).join("");

    cardStatus.textContent = total ? `${visible}/${total} carte(s) affichée(s) pour ${currentDeckName}.` : `Aucune carte résolue pour ${currentDeckName}.`;
  };

  const openDeckCatalog = async (deckName) => {
    if (!deckName || !cardSelect) return;
    if (![...cardSelect.options].some((option) => option.value === deckName)) return;
    cardSelect.value = deckName;
    currentDeckName = deckName;
    if (cardSections) cardSections.innerHTML = "";
    if (cardStatus) cardStatus.textContent = `Chargement de ${deckName}…`;
    if (cardNote) cardNote.hidden = true;

    currentCatalog = await loadCatalog(deckName);
    if (cardNote) {
      const note = currentCatalog.rule?.note || "";
      cardNote.textContent = note;
      cardNote.hidden = !note;
    }
    renderCardCatalog();
    document.getElementById("cards")?.scrollIntoView({behavior: "smooth", block: "start"});
  };

  cardSelect?.addEventListener("change", () => openDeckCatalog(cardSelect.value));
  cardSearch?.addEventListener("input", renderCardCatalog);
  document.querySelectorAll("[data-open-deck]").forEach((button) => button.addEventListener("click", () => openDeckCatalog(button.dataset.openDeck || "")));

  // ------------------------------------------------------------
  // Card modal — enlarged artwork + effect + official Neuron link
  // ------------------------------------------------------------
  const modal = document.getElementById("halloween-card-modal");
  const modalImage = document.getElementById("halloween-card-modal-image");
  const modalName = document.getElementById("halloween-card-modal-name");
  const modalKind = document.getElementById("halloween-card-modal-kind");
  const modalType = document.getElementById("halloween-card-modal-type");
  const modalDesc = document.getElementById("halloween-card-modal-desc");
  const modalLimit = document.getElementById("halloween-card-modal-limit");
  const modalLink = document.getElementById("halloween-card-modal-link");

  const closeModal = () => {
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("halloween-modal-open");
  };

  const showCardModal = (card, permission, groupKind) => {
    if (!modal) return;
    const image = card.card_images?.[0]?.image_url || card.card_images?.[0]?.image_url_small || "";
    if (modalImage) {
      modalImage.src = image;
      modalImage.alt = card.name;
    }
    if (modalName) modalName.textContent = card.name;
    if (modalKind) {
      modalKind.textContent =
        groupKind === "staples" ? "Staple compatible" :
        groupKind === "related" ? "Related / Support lié" :
        groupKind === "support" ? "Support" :
        groupKind === "extra" ? "Extra Deck" :
        "Carte du deck";
    }
    if (modalType) modalType.textContent = card.type || "";
    if (modalDesc) modalDesc.textContent = card.desc || "Texte de carte indisponible.";
    if (modalLimit) {
      modalLimit.textContent = permission.label;
      modalLimit.className = `halloween-card-limit ${permission.contextOnly ? "is-context" : permission.special ? "is-special" : ""}`;
    }
    if (modalLink) {
      modalLink.href = `https://www.db.yugioh-card.com/yugiohdb/card_search.action?ope=1&keyword=${encodeURIComponent(card.name)}&request_locale=fr`;
    }
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("halloween-modal-open");
  };

  cardSections?.addEventListener("click", (event) => {
    const tile = event.target.closest(".halloween-card-tile");
    if (!tile) return;
    const cardName = tile.dataset.cardName || "";
    const groupKind = tile.dataset.groupKind || "core";
    const group = currentCatalog.groups.find((item) => item.key === groupKind);
    const entry = group?.cards.find(({card}) => card.name === cardName);
    if (entry) showCardModal(entry.card, entry.permission, groupKind);
  });

  modal?.querySelectorAll("[data-close-card-modal]").forEach((button) => button.addEventListener("click", closeModal));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal && !modal.hidden) closeModal();
  });

  // ------------------------------------------------------------
  // Bonbons & Sorts (kept as before)
  // ------------------------------------------------------------
  const choiceState = {
    candy: localStorage.getItem("hamtaroHalloweenCandy") || "",
    spell: localStorage.getItem("hamtaroHalloweenSpell") || "",
  };

  const renderChoices = () => {
    document.querySelectorAll("[data-choice-group]").forEach((group) => {
      const key = group.dataset.choiceGroup;
      group.querySelectorAll(".halloween-choice").forEach((button) => button.classList.toggle("is-selected", button.dataset.choice === choiceState[key]));
    });
    const candy = document.getElementById("halloween-candy-choice");
    const spell = document.getElementById("halloween-spell-choice");
    if (candy) candy.textContent = choiceState.candy || "Aucun";
    if (spell) spell.textContent = choiceState.spell || "Aucun";
  };

  document.querySelectorAll("[data-choice-group]").forEach((group) => {
    group.addEventListener("click", (event) => {
      const button = event.target.closest(".halloween-choice");
      if (!button) return;
      const key = group.dataset.choiceGroup;
      choiceState[key] = button.dataset.choice || "";
      localStorage.setItem(key === "candy" ? "hamtaroHalloweenCandy" : "hamtaroHalloweenSpell", choiceState[key]);
      renderChoices();
    });
  });

  document.getElementById("halloween-copy-choice")?.addEventListener("click", async (event) => {
    const text = `Format Halloween — Bonbon : ${choiceState.candy || "non choisi"} | Sort : ${choiceState.spell || "non choisi"}`;
    try {
      await navigator.clipboard.writeText(text);
      const button = event.currentTarget;
      const original = button.textContent;
      button.textContent = "✅ Choix copiés";
      setTimeout(() => { button.textContent = original; }, 1500);
    } catch (_) {
      window.prompt("Copie tes choix :", text);
    }
  });

  renderChoices();
})();
