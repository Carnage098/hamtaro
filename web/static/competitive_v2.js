(() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[char]));

  async function loadMeta(period = "30d") {
    if (!location.pathname.startsWith("/archetypes")) return;
    const params = new URLSearchParams(location.search);
    params.set("period", period);
    const format = new URLSearchParams(location.search).get("format");
    const url = "/api/v2/meta?" + new URLSearchParams({
      period,
      ...(format ? { format } : {})
    }).toString();

    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();

    const summary = document.querySelector("[data-meta-summary]");
    if (summary) {
      const cards = summary.querySelectorAll("article strong");
      if (cards[0]) cards[0].textContent = String(data.decks ?? 0);
      if (cards[1]) cards[1].textContent = String(data.matches ?? 0);
    }

    const podium = document.querySelector("[data-meta-podium]");
    if (podium) {
      podium.innerHTML = (data.podium || []).map((row, index) => `
        <div class="v2-list-row">
          <strong>${["🥇","🥈","🥉"][index] || "#" + (index + 1)}</strong>
          <div><b>${esc(row.deck)}</b><small>${row.players} joueur(s) · ${row.matches} match(s)</small></div>
          <span>${Number(row.win_rate || 0).toFixed(1)}%</span>
        </div>
      `).join("") || "<p>Aucune donnée pour cette période.</p>";
    }

    const emerging = document.querySelector("[data-meta-emerging]");
    if (emerging) {
      emerging.innerHTML = (data.emerging || []).map((row, index) => {
        const delta = Number(row.popularity_delta || 0);
        return `
          <div class="v2-list-row">
            <strong>🚀</strong>
            <div><b>${esc(row.deck)}</b><small>${Number(row.popularity || 0).toFixed(1)}% de présence</small></div>
            <span class="v2-delta ${delta >= 0 ? "up" : "down"}">${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pt</span>
          </div>
        `;
      }).join("") || "<p>Aucun deck émergent détecté.</p>";
    }

    const map = new Map((data.items || []).map((row) => [String(row.deck).toLowerCase(), row]));
    document.querySelectorAll("[data-meta-deck]").forEach((node) => {
      const row = map.get(String(node.dataset.metaDeck || "").toLowerCase());
      if (!row) return;
      const delta = Number(row.popularity_delta || 0);
      const sample = row.sample_label
        ? `<span class="v2-chip warn">⚠ ${esc(row.sample_label)}</span>`
        : "";
      node.innerHTML = `
        <span class="v2-chip">${Number(row.popularity || 0).toFixed(1)}% méta</span>
        <span class="v2-chip ${delta >= 0 ? "" : "warn"}">${delta >= 0 ? "↗" : "↘"} ${Math.abs(delta).toFixed(1)} pt</span>
        ${sample}
      `;
    });
  }

  document.querySelectorAll("[data-meta-periods] button").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-meta-periods] button").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      loadMeta(button.dataset.period || "30d");
    });
  });

  async function enrichPlayer() {
    const match = location.pathname.match(/^\/players\/(\d+)$/);
    if (!match) return;
    const response = await fetch(`/api/v2/players/${match[1]}/identity`, { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    const main = document.querySelector("main");
    if (!main) return;

    const panel = document.createElement("section");
    panel.className = "identity-v2";
    panel.innerHTML = `
      <span class="v2-kicker">IDENTITÉ HAMTARO</span>
      <h2>${esc(data.title || "Duelliste Hamtaro")}</h2>
      <div class="identity-badges">
        ${(data.badges || []).map((badge) => `<span class="identity-badge">${esc(badge.icon)} ${esc(badge.label)}</span>`).join("")}
      </div>
      <div class="v2-metrics">
        <article><span>Deck signature</span><strong>${esc(data.signature_deck || "—")}</strong></article>
        <article><span>Meilleure série</span><strong>${Number(data.best_streak || 0)}</strong></article>
        <article><span>Meilleur ELO</span><strong>${esc(data.elo?.peak_rating ?? "—")}</strong></article>
      </div>
    `;
    main.insertBefore(panel, main.children[1] || null);
  }

  function injectTournamentLiveLink() {
    const match = location.pathname.match(/^\/tournaments\/(\d+)$/);
    if (!match) return;
    const main = document.querySelector("main");
    if (!main) return;
    const link = document.createElement("a");
    link.href = `/live/tournament/${match[1]}`;
    link.className = "live-primary";
    link.textContent = "🔴 Ouvrir le centre LIVE";
    main.insertBefore(link, main.firstChild);
  }

  loadMeta();
  enrichPlayer();
  injectTournamentLiveLink();
})();
