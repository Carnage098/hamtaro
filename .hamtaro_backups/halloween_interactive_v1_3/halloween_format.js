
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
