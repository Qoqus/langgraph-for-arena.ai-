/* Museum catalog — a read-only window onto an accumulated material history.
 *
 * Two data modes:
 *   api     — talks to the FastAPI layer (`museum serve`), polls for new accessions.
 *   static  — reads the exported JSON/SVG snapshot (Netlify and any static host),
 *             with no polling because the snapshot cannot change underneath us.
 * The mode comes from `window.MUSEUM_CONFIG`, injected by `museum export`.
 */

(() => {
  "use strict";

  const CONFIG = Object.assign(
    {
      mode: "api",
      catalogUrl: "/api/catalog",
      artifactUrl: (id) => `/api/artifacts/${encodeURIComponent(id)}`,
      svgUrl: (id) => `/api/artifacts/${encodeURIComponent(id)}/svg`,
      pollMs: 6000,
    },
    window.MUSEUM_CONFIG || {}
  );
  const STATIC = CONFIG.mode === "static";

  const state = {
    payload: null,
    lineage: new Set(),
    material: new Set(),
    currentId: null,
    signature: null,
    timer: null,
    pushedHash: false,
    opener: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[ch]);

  const REL_CLASS = {
    turunan: "t", pemulihan: "p", resonansi: "r", kutipan: "k", patahan: "x",
  };

  const STATUS_ID = {
    "belum-dimulai": "menunggu seed",
    complete: "selesai",
    seeded: "seed",
    curating: "mengkurasi",
    rebuilt: "proyeksi dibangun ulang",
    paused: "menunggu review",
  };

  async function fetchJSON(url) {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  /* ---------------------------------------------------------------- rail */

  function renderStats(data) {
    const counts = data.counts || {};
    $("#stat-iteration").textContent = data.iteration ?? "—";
    $("#stat-artifacts").textContent = counts.artifacts ?? 0;
    const span = data.span || {};
    $("#stat-span").textContent =
      span.first_year != null ? `${span.first_year} – ${span.last_year}` : "—";
    $("#stat-rejections").textContent = counts.rejections ?? 0;
    $("#stat-llm").textContent = data.llm || "—";

    const dot = $("#status-dot");
    const hasArt = (counts.artifacts || 0) > 0;
    dot.className = "dot" + (data.status === "complete" ? " done" : hasArt ? " live" : "");
    $("#status-text").textContent = STATUS_ID[data.status] || data.status || "tidak diketahui";
    $("#iteration-badge").textContent = `iter ${data.iteration ?? 0}`;
  }

  function chip(label, count, pressed, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.setAttribute("aria-pressed", pressed ? "true" : "false");
    button.innerHTML = `${esc(label)}<span class="count">${count}</span>`;
    button.addEventListener("click", onClick);
    return button;
  }

  function renderFilters() {
    const data = state.payload || {};
    const lineageBox = $("#lineage-filters");
    const materialBox = $("#material-filters");
    lineageBox.innerHTML = "";
    materialBox.innerHTML = "";

    const lineages = data.lineage_counts || {};
    const materials = data.material_counts || {};

    lineageBox.appendChild(
      chip("semua", data.counts?.artifacts ?? 0, state.lineage.size === 0, () => {
        state.lineage.clear();
        applyFilters();
      })
    );

    Object.entries(lineages).forEach(([lineage, count]) => {
      lineageBox.appendChild(chip(lineage, count, state.lineage.has(lineage), () => {
        if (state.lineage.has(lineage)) state.lineage.delete(lineage);
        else state.lineage.add(lineage);
        applyFilters();
      }));
    });

    Object.entries(materials).forEach(([material, count]) => {
      materialBox.appendChild(chip(material, count, state.material.has(material), () => {
        if (state.material.has(material)) state.material.delete(material);
        else state.material.add(material);
        applyFilters();
      }));
    });

    updateFilterCount();
  }

  function updateFilterCount() {
    const active = state.lineage.size + state.material.size;
    const badge = $("#filter-count");
    badge.textContent = active;
    badge.hidden = active === 0;
    $("#clear-filters").hidden = active === 0;
    $("#filter-toggle").classList.toggle("is-active", active > 0);
  }

  function setFiltersOpen(open) {
    document.body.classList.toggle("filters-open", open);
    $("#filter-toggle").setAttribute("aria-expanded", open ? "true" : "false");
    $("#filter-scrim").hidden = !open;
  }

  /* ----------------------------------------------------------------- map */

  function renderMap() {
    const data = state.payload || {};
    const svg = $("#map");
    const artifacts = data.artifacts || [];
    if (!artifacts.length) {
      svg.innerHTML = `<text x="20" y="130" class="axis-label">BELUM ADA AKSESI</text>`;
      return;
    }
    const lineages = Object.keys(data.lineage_counts || {});
    const W = 900, H = 260, padL = 66, padR = 26, padT = 26, padB = 34;
    const years = artifacts.map((a) => a.year_fictional);
    const minY = Math.min(...years);
    const maxY = Math.max(...years);
    const x = (year) =>
      padL + ((year - minY) / Math.max(1, maxY - minY)) * (W - padL - padR);
    const laneY = (lineage) => {
      const index = Math.max(0, lineages.indexOf(lineage));
      const usable = H - padT - padB;
      const step = usable / Math.max(1, lineages.length);
      return padT + step * (index + 0.5);
    };

    const parts = [];

    lineages.forEach((lineage) => {
      const y = laneY(lineage);
      parts.push(`<line class="lane" x1="${padL - 8}" y1="${y}" x2="${W - padR}" y2="${y}" />`);
      parts.push(`<text class="lane-label" x="0" y="${y + 3}">${esc(lineage)}</text>`);
    });

    const ticks = 4;
    for (let i = 0; i <= ticks; i += 1) {
      const t = i / ticks;
      const year = Math.round(minY + t * (maxY - minY));
      const px = x(year);
      parts.push(`<line x1="${px}" y1="${H - padB + 6}" x2="${px}" y2="${H - padB + 11}" stroke="rgba(236,231,219,0.25)" />`);
      parts.push(`<text class="axis-label" x="${px}" y="${H - 10}" text-anchor="middle">${year}</text>`);
    }

    const byId = Object.fromEntries(artifacts.map((a) => [a.id, a]));

    (data.graph?.edges || []).forEach((edge) => {
      const source = byId[edge.source];
      const target = byId[edge.target];
      if (!source || !target) return;
      const x1 = x(source.year_fictional);
      const x2 = x(target.year_fictional);
      const y1 = laneY(source.lineage);
      const y2 = laneY(target.lineage);
      const cx = (x1 + x2) / 2;
      const lift = y1 === y2 ? 16 : 0;
      const path = `M ${x1} ${y1} C ${cx} ${y1 - lift}, ${cx} ${y2 - lift}, ${x2} ${y2}`;
      parts.push(`<path class="edge ${REL_CLASS[edge.relation] || "k"}" d="${path}" />`);
    });

    artifacts.forEach((art) => {
      const px = x(art.year_fictional);
      const py = laneY(art.lineage);
      const cited = (data.most_cited || []).some((item) => item.id === art.id);
      const r = cited ? 5 : 3.4;
      // The visible dot stays small for legibility; the hit target is finger-sized.
      parts.push(
        `<g class="node" data-id="${esc(art.id)}" tabindex="0" role="button"
            aria-label="Buka ${esc(art.title)}, ${art.year_fictional}">
           <circle class="node-hit" cx="${px}" cy="${py}" r="12" />
           <circle class="node-dot" cx="${px}" cy="${py}" r="${r}" />
           <text x="${px + 7}" y="${py - 7}">${esc(art.id)}</text>
         </g>`
      );
    });

    svg.innerHTML = parts.join("");
    svg.querySelectorAll(".node").forEach((node) => {
      const open = () => openDetail(node.dataset.id, { opener: node });
      node.addEventListener("click", open);
      node.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
  }

  /* ------------------------------------------------------------ timeline */

  function visibleArtifacts() {
    const artifacts = state.payload?.artifacts || [];
    return artifacts.filter((art) => {
      const lineageOk = state.lineage.size === 0 || state.lineage.has(art.lineage);
      const materialOk =
        state.material.size === 0 || art.materials.some((m) => state.material.has(m));
      return lineageOk && materialOk;
    });
  }

  function entryTemplate(art) {
    const refs = art.refs || [];
    const refLabel = refs.length
      ? `${refs.length} rujukan · ${refs.map((r) => r.relation).join(", ")}`
      : "tanpa rujukan (fondasi)";
    const accession = String(art.id).toUpperCase();
    return `
      <article class="entry" data-id="${esc(art.id)}" tabindex="0" role="button"
               aria-label="Buka detail ${esc(art.title)}, tahun ${art.year_fictional}">
        <div class="entry-year">
          <span class="year">${art.year_fictional}</span>
          <span class="iter">ITER ${String(art.iteration).padStart(2, "0")}</span>
        </div>
        <figure class="plaque">
          <img loading="lazy" src="${esc(CONFIG.svgUrl(art.id))}" alt="Plakat ${esc(art.title)}" />
          <figcaption><span>${esc(accession)}</span><span>${esc(art.visual.palette)}</span></figcaption>
        </figure>
        <div class="entry-body">
          <h3>${esc(art.title)}</h3>
          <p class="inscription">${esc(art.inscription)}</p>
          <div class="entry-meta">
            <span class="tag lineage">${esc(art.lineage)}</span>
            <span class="tag">${esc(art.form)}</span>
            <span class="tag">${esc(art.function)}</span>
            <span class="tag refs">${esc(refLabel)}</span>
          </div>
          <p class="entry-extra">${esc(art.materials.join(" · "))} &nbsp;/&nbsp; motif ${esc(art.motifs.join(" · "))}</p>
        </div>
      </article>`;
  }

  function renderTimeline() {
    const box = $("#timeline");
    const all = state.payload?.artifacts || [];
    const visible = visibleArtifacts();

    if (!all.length) {
      box.innerHTML = `
        <div class="empty">
          <p>Katalog masih kosong.</p>
          <p>Jalankan <code>museum seed</code> lalu <code>museum run --iterations 12</code>,
          atau tunggu scheduler menulis aksesi pertama.</p>
        </div>`;
      $("#timeline-meta").textContent = "";
      return;
    }

    box.innerHTML = visible.map(entryTemplate).join("") ||
      `<div class="empty"><p>Tidak ada artefak yang cocok dengan filter ini.</p></div>`;

    $("#timeline-meta").textContent =
      `${visible.length} / ${all.length} aksesi · urut tahun fiktif`;

    box.querySelectorAll(".entry").forEach((entry) => {
      const open = () => openDetail(entry.dataset.id, { opener: entry });
      entry.addEventListener("click", open);
      entry.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
  }

  function applyFilters() {
    renderFilters();
    renderTimeline();
  }

  /* -------------------------------------------------------------- detail */

  function staticDetail(id) {
    const artifacts = state.payload?.artifacts || [];
    const byId = new Map(artifacts.map((a) => [a.id, a]));
    const art = byId.get(id);
    if (!art) throw new Error(`artefak ${id} tidak ada di katalog ini`);

    const refs = (art.refs || []).map((ref) => {
      const target = byId.get(ref.id);
      return {
        ...ref,
        target: target
          ? {
              id: target.id,
              title: target.title,
              year_fictional: target.year_fictional,
              lineage: target.lineage,
            }
          : null,
      };
    });

    const citedBy = [];
    artifacts.forEach((other) => {
      (other.refs || []).forEach((ref) => {
        if (ref.id !== id) return;
        citedBy.push({
          id: other.id,
          title: other.title,
          year: other.year_fictional,
          relation: ref.relation,
          note: ref.note,
        });
      });
    });

    return { artifact: art, refs, cited_by: citedBy };
  }

  async function loadDetail(id) {
    if (STATIC) return staticDetail(id);
    return fetchJSON(CONFIG.artifactUrl(id));
  }

  async function openDetail(id, options = {}) {
    if (!id) return;
    const { push = true } = options;
    const first = !state.currentId;
    if (document.body.classList.contains("filters-open")) setFiltersOpen(false);

    if (first) state.opener = options.opener || document.activeElement;
    state.currentId = id;

    const drawer = $("#detail");
    const body = $("#detail-body");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    $("#scrim").hidden = false;
    document.body.classList.add("sheet-open");
    body.innerHTML = `<p class="loading">MEMUAT ${esc(id)}…</p>`;

    const hash = `#/artefak/${encodeURIComponent(id)}`;
    if (push && location.hash !== hash) {
      history.pushState({ museumDetail: id }, "", hash);
      state.pushedHash = true;
    }

    drawer.querySelector(".close").focus({ preventScroll: true });

    try {
      const data = await loadDetail(id);
      if (state.currentId !== id) return;
      body.innerHTML = detailTemplate(data);
      body.scrollTop = 0;
      drawer.scrollTop = 0;
      body.querySelectorAll("[data-goto]").forEach((el) => {
        el.addEventListener("click", () => openDetail(el.dataset.goto));
      });
    } catch (error) {
      body.innerHTML = `<p class="loading">GAGAL MEMUAT: ${esc(error.message)}</p>`;
    }
  }

  function hideDetail() {
    state.currentId = null;
    const drawer = $("#detail");
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    $("#scrim").hidden = true;
    document.body.classList.remove("sheet-open");
    $("#detail-body").innerHTML = "";
    if (state.opener && typeof state.opener.focus === "function") {
      state.opener.focus({ preventScroll: true });
    }
    state.opener = null;
  }

  function closeDetail(options = {}) {
    const { fromHistory = false } = options;
    const hadHash = /^#\/artefak\//.test(location.hash);
    hideDetail();
    if (hadHash && state.pushedHash && !fromHistory) {
      // Undo our own pushState so the phone's back button stays predictable.
      state.pushedHash = false;
      history.back();
      return;
    }
    state.pushedHash = false;
    if (hadHash) history.replaceState(null, "", location.pathname + location.search);
  }

  function refBlock(ref) {
    const relation = ref.relation || "kutipan";
    const target = ref.target;
    const title = target ? target.title : ref.id;
    const year = target ? target.year_fictional : "?";
    return `
      <button class="ref" data-goto="${esc(ref.id)}" type="button">
        <span class="ref-top">
          <span class="ref-title">${esc(title)} · ${esc(year)}</span>
          <span class="ref-rel">${esc(relation)}</span>
        </span>
        <span class="ref-note">${esc(ref.note || "")}</span>
        <span class="ref-id">${esc(ref.id)}</span>
      </button>`;
  }

  function citedByBlock(citation) {
    return `
      <button class="ref" data-goto="${esc(citation.id)}" type="button">
        <span class="ref-top">
          <span class="ref-title">${esc(citation.title)} · ${esc(citation.year)}</span>
          <span class="ref-rel">${esc(citation.relation)}</span>
        </span>
        <span class="ref-note">${esc(citation.note || "")}</span>
        <span class="ref-id">${esc(citation.id)}</span>
      </button>`;
  }

  function detailTemplate(data) {
    const art = data.artifact;
    const refs = data.refs || [];
    const citedBy = data.cited_by || [];
    const visual = art.visual || {};
    return `
      <p class="eyebrow">Aksesi ${esc(art.id)} · iterasi ${art.iteration}</p>
      <div class="detail-figure">
        <img src="${esc(CONFIG.svgUrl(art.id))}" alt="Plakat ${esc(art.title)}" />
      </div>
      <h2>${esc(art.title)}</h2>
      <div class="kicker">
        <span class="tag lineage">${esc(art.lineage)}</span>
        <span class="tag">${esc(art.form)}</span>
        <span class="tag">${esc(art.function)}</span>
        <span class="tag">${esc(art.year_fictional)}</span>
      </div>

      <div class="inscription-box">“${esc(art.inscription)}”</div>

      <dl class="meta">
        <dt>Bahan</dt><dd>${esc(art.materials.join(", "))}</dd>
        <dt>Motif</dt><dd>${esc(art.motifs.join(", "))}</dd>
        <dt>Dibuat</dt><dd class="mono">${esc(art.created_at)}</dd>
        <dt>Kurator</dt><dd class="mono">${esc(art.llm)}</dd>
        <dt>Digest</dt><dd class="mono">${esc(String(art.draft_digest).slice(0, 24))}…</dd>
      </dl>

      <p class="eyebrow section-label">Asal-usul</p>
      <p class="provenance">${esc(art.provenance_note)}</p>

      <p class="eyebrow section-label">Rujukan keluar (${refs.length})</p>
      ${refs.length ? refs.map(refBlock).join("") : `<p class="provenance">Tidak merujuk apa pun: ini salah satu batu fondasi museum.</p>`}

      <p class="eyebrow section-label">Dikutip oleh (${citedBy.length})</p>
      ${citedBy.length ? citedBy.map(citedByBlock).join("") : `<p class="provenance">Belum ada karya lain yang merujuknya.</p>`}

      <p class="eyebrow section-label">Parameter visual</p>
      <dl class="visual-grid">
        <div><dt>Form</dt><dd>${esc(visual.form)}</dd></div>
        <div><dt>Palet</dt><dd>${esc(visual.palette)}</dd></div>
        <div><dt>Motif</dt><dd>${esc(visual.motif)}</dd></div>
        <div><dt>Simetri</dt><dd>${esc(visual.symmetry)}</dd></div>
        <div><dt>Densitas</dt><dd>${esc(visual.density)}</dd></div>
        <div><dt>Strata</dt><dd>${esc(visual.strata)}</dd></div>
      </dl>
    `;
  }

  /* ---------------------------------------------------------------- boot */

  function renderAll() {
    renderStats(state.payload || {});
    renderFilters();
    renderMap();
    renderTimeline();
  }

  async function refresh() {
    try {
      const data = await fetchJSON(CONFIG.catalogUrl);
      state.payload = data;
      const signature = `${data.generated_at}|${data.iteration}|${(data.artifacts || []).length}`;
      if (signature !== state.signature) {
        state.signature = signature;
        const validLineage = new Set(Object.keys(data.lineage_counts || {}));
        const validMaterial = new Set(Object.keys(data.material_counts || {}));
        state.lineage = new Set([...state.lineage].filter((l) => validLineage.has(l)));
        state.material = new Set([...state.material].filter((m) => validMaterial.has(m)));
        renderAll();
      }
    } catch (error) {
      $("#status-text").textContent = STATIC
        ? "gagal membaca data/catalog.json"
        : "server tidak terjangkau";
      $("#status-dot").className = "dot";
    }
  }

  function trapFocus(event) {
    const focusable = [...document.querySelectorAll("#detail button, #detail a[href]")];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function boot() {
    $("#detail-close").addEventListener("click", () => closeDetail());
    $("#scrim").addEventListener("click", () => closeDetail());
    $("#clear-filters").addEventListener("click", () => {
      state.lineage.clear();
      state.material.clear();
      applyFilters();
    });
    $("#filter-toggle").addEventListener("click", () => {
      setFiltersOpen(!document.body.classList.contains("filters-open"));
    });
    $("#filters-close").addEventListener("click", () => setFiltersOpen(false));
    $("#filter-scrim").addEventListener("click", () => setFiltersOpen(false));
    $("#to-top").addEventListener("click", () => {
      const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
      window.scrollTo({ top: 0, behavior: query?.matches ? "auto" : "smooth" });
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Tab" && state.currentId) {
        trapFocus(event);
        return;
      }
      if (event.key !== "Escape") return;
      if (document.body.classList.contains("filters-open")) setFiltersOpen(false);
      else if (state.currentId) closeDetail();
    });

    window.addEventListener("popstate", () => {
      const match = location.hash.match(/^#\/artefak\/(.+)$/);
      if (match) openDetail(decodeURIComponent(match[1]), { push: false });
      else if (state.currentId) closeDetail({ fromHistory: true });
    });

    const initial = location.hash.match(/^#\/artefak\/(.+)$/);
    refresh().then(() => {
      if (initial) openDetail(decodeURIComponent(initial[1]), { push: false });
    });

    if (!STATIC && CONFIG.pollMs > 0) {
      state.timer = setInterval(() => {
        if (document.hidden) return;
        refresh();
      }, CONFIG.pollMs);
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
