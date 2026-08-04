(() => {
  "use strict";
  const panel = document.getElementById("hamtaro-rounds");
  if (!panel) return;
  const content = document.getElementById("hamtaro-rounds-content");
  const subtitle = document.getElementById("hamtaro-rounds-subtitle");
  const refresh = document.getElementById("hamtaro-rounds-refresh");
  const match = location.pathname.match(/\/tournaments\/(\d+)/);
  if (!match) { panel.hidden = true; return; }
  const id = match[1];
  let active = "";

  if (!document.querySelector('link[data-rounds-css]')) {
    const link = document.createElement("link");
    link.rel = "stylesheet"; link.href = "/static/rounds.css"; link.dataset.roundsCss = "1";
    document.head.appendChild(link);
  }

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const statusClass = m => m.is_double_loss ? "danger" : m.is_bye ? "bye" : m.is_final ? "done" : m.status === "reported" ? "reported" : m.status === "playing" ? "playing" : "pending";
  const player = p => {
    const row = el("div", `rounds-player${p.winner ? " winner" : ""}`);
    row.append(el("span", "rounds-name", p.name), el("strong", "rounds-score", p.score));
    return row;
  };
  const matchCard = m => {
    const card = el("article", "rounds-match");
    const head = el("div", "rounds-match-head");
    head.append(el("span", "rounds-ref", m.kind === "swiss" ? `Table ${m.table_number || "—"}` : `Match ${m.order || m.id || "—"}`), el("span", `rounds-status ${statusClass(m)}`, m.status_label));
    const players = el("div", "rounds-players"); players.append(player(m.player1), player(m.player2));
    card.append(head, players); return card;
  };

  const roundsBlock = (title, rounds, prefix) => {
    const wrap = el("section", "rounds-block"); wrap.append(el("h3", "", title));
    if (!rounds.length) { wrap.append(el("div", "rounds-empty", "Aucune ronde n’a encore été générée.")); return wrap; }
    const keys = rounds.map(r => `${prefix}-${r.number}`);
    if (!active || !keys.includes(active)) {
      const current = rounds.find(r => r.is_current); active = current ? `${prefix}-${current.number}` : keys[keys.length - 1];
    }
    const tabs = el("div", "rounds-tabs"), panels = el("div", "rounds-panels");
    rounds.forEach(r => {
      const key = `${prefix}-${r.number}`;
      const button = el("button", `rounds-tab${key === active ? " active" : ""}${r.is_current ? " current" : ""}`, r.label);
      button.type = "button";
      const section = el("section", "rounds-panel"); section.dataset.key = key; section.hidden = key !== active;
      section.append(el("p", "rounds-progress", `${r.completed_count}/${r.match_count} match${r.match_count > 1 ? "s" : ""} terminé${r.completed_count > 1 ? "s" : ""}`));
      const grid = el("div", "rounds-grid"); r.matches.forEach(m => grid.append(matchCard(m))); section.append(grid);
      button.addEventListener("click", () => {
        active = key;
        wrap.querySelectorAll(".rounds-tab").forEach(x => x.classList.toggle("active", x === button));
        wrap.querySelectorAll(".rounds-panel").forEach(x => x.hidden = x.dataset.key !== key);
      });
      tabs.append(button); panels.append(section);
    });
    wrap.append(tabs, panels); return wrap;
  };

  const standings = rows => {
    const section = el("section", "rounds-block"); section.append(el("h3", "", "Classement suisse"));
    if (!rows.length) { section.append(el("div", "rounds-empty", "Le classement n’est pas encore disponible.")); return section; }
    const scroll = el("div", "rounds-table-scroll"), table = el("table", "rounds-table"), thead = el("thead"), hr = el("tr");
    ["#", "Joueur", "Pts", "V", "D", "DL", "BYE"].forEach(v => hr.append(el("th", "", v))); thead.append(hr);
    const tbody = el("tbody"); rows.forEach(r => { const tr = el("tr"); [r.rank, r.name, r.points, r.wins, r.losses, r.double_losses, r.byes].forEach(v => tr.append(el("td", "", String(v)))); tbody.append(tr); });
    table.append(thead, tbody); scroll.append(table); section.append(scroll); return section;
  };

  const render = data => {
    const frag = document.createDocumentFragment(), summary = el("div", "rounds-summary");
    [["Format", data.tournament.display_type_label], ["Ronde actuelle", data.tournament.current_round || "—"], ["Rondes prévues", data.tournament.total_rounds || "—"]].forEach(([a,b]) => { const c = el("div", "rounds-summary-card"); c.append(el("span", "", a), el("strong", "", String(b))); summary.append(c); });
    frag.append(summary);
    if (data.swiss.available) { frag.append(roundsBlock("🇨🇭 Rondes suisses", data.swiss.rounds, "swiss"), standings(data.swiss.standings)); }
    if (data.bracket.available) frag.append(roundsBlock(data.swiss.available ? "🏆 Top Cut à élimination directe" : "🏆 Rondes à élimination directe", data.bracket.rounds, "bracket"));
    if (!data.swiss.available && !data.bracket.available) frag.append(el("div", "rounds-empty", "Aucune ronde n’a encore été générée pour ce tournoi."));
    content.replaceChildren(frag); subtitle.textContent = "Actualisation automatique toutes les 30 secondes.";
  };

  const load = async manual => {
    if (manual) { refresh.disabled = true; refresh.textContent = "Actualisation…"; }
    try {
      const response = await fetch(`/api/tournaments/${encodeURIComponent(id)}/rounds`, {headers:{Accept:"application/json"}, cache:"no-store"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      console.error("Hamtaro rounds", error); content.replaceChildren(el("div", "rounds-empty error", "Impossible de charger les rondes pour le moment.")); subtitle.textContent = "Une nouvelle tentative sera effectuée automatiquement.";
    } finally { if (manual) { refresh.disabled = false; refresh.textContent = "Actualiser"; } }
  };
  content.replaceChildren(el("div", "rounds-empty", "Chargement des rondes…"));
  refresh.addEventListener("click", () => load(true)); load(false); setInterval(() => load(false), 30000);
})();
