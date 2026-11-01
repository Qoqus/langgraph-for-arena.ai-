/* Museum catalog — a read-only window onto an accumulated material history. */

(() => {
  "use strict";

  const state = {
    payload: null,
    lineage: new Set(),
    material: new Set(),
    currentId: null,
    signature: null,
    timer: null,
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

    const allLineage = chip("semua", data.counts?.artifacts ?? 0, state.lineage.size === 0, () => {
      state.lineage.clear();
      applyFilters();
    });
    lineageBox.appendChild(allLineage);

    Object.entries(lineages).forEach(([lineage, count]) => {
      const active = state.lineage.has(lineage);
      lineageBox.appendChild(chip(lineage, count, active, () => {
        if (state.lineage.has(lineage)) state.lineage.delete(lineage);
        else state.lineage.add(lineage);
        applyFilters();
      }));
    });

    Object.entries(materials).forEach(([material, count]) => {
      const active = state.material.has(material);
      materialBox.appendChild(chip(material, count, active, () => {
        if (state.material.has(material)) state.material.delete(material);
        else state.material.add(material);
        applyFilters();
      }));
    });
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
    const NS = "http://www.w3.org/2000/svg";
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

    // lanes
    lineages.forEach((lineage) => {
      const y = laneY(lineage);
      parts.push(`<line class="lane" x1="${padL - 8}" y1="${y}" x2="${W - padR}" y2="${y}" />`);
      parts.push(`<text class="lane-label" x="0" y="${y + 3}">${esc(lineage)}</text>`);
    });

    // year axis
    const ticks = 4;
    for (let i = 0; i <= ticks; i += 1) {
      const t = i / ticks;
      const year = Math.round(minY + t * (maxY - minY));
      const px = x(year);
      parts.push(`<line x1="${px}" y1="${H - padB + 6}" x2="${px}" y2="${H - padB + 11}" stroke="rgba(236,231,219,0.25)" />`);
      parts.push(`<text class="axis-label" x="${px}" y="${H - 10}" text-anchor="middle">${year}</text>`);
    }

    const byId = Object.fromEntries(artifacts.map((a) => [a.id, a]));

    // edges (source = older, target = newer)
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

    // nodes
    artifacts.forEach((art) => {
      const px = x(art.year_fictional);
      const py = laneY(art.lineage);
      const cited = (data.most_cited || []).some((item) => item.id === art.id);
      const r = cited ? 5 : 3.4;
      parts.push(
        `<g class="node" data-id="${esc(art.id)}" tabindex="0">
           <circle cx="${px}" cy="${py}" r="${r}" />
           <text x="${px + 7}" y="${py - 7}">${esc(art.id)}</text>
         </g>`
      );
    });

    svg.innerHTML = parts.join("");
    svg.querySelectorAll(".node").forEach((node) => {
      const open = () => openDetail(node.dataset.id);
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
      <article class="entry" data-id="${esc(art.id)}" tabindex="0">
        <div class="entry-year">
          <span class="year">${art.year_fictional}</span>
          <span class="iter">ITER ${String(art.iteration).padStart(2, "0")}</span>
        </div>
        <figure class="plaque">
          <img loading="lazy" src="/api/artifacts/${encodeURIComponent(art.id)}/svg" alt="Plakat ${esc(art.title)}" />
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
      const open = () => openDetail(entry.dataset.id);
      entry.addEventListener("click", open);
      entry.addEventListener("keydown", (event) => {
        if (event.key === "Enter") open();
      });
    });
  }

  function applyFilters() {
    renderFilters();
    renderTimeline();
  }

  /* -------------------------------------------------------------- detail */

  async function openDetail(id) {
    if (!id) return;
    state.currentId = id;
    const drawer = $("#detail");
    const body = $("#detail-body");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    $("#scrim").hidden = false;
    body.innerHTML = `<p class="loading">MEMUAT ${esc(id)}…</p>`;
    if (location.hash !== `#/artefak/${id}`) history.replaceState(null, "", `#/artefak/${id}`);

    try {
      const data = await fetchJSON(`/api/artifacts/${encodeURIComponent(id)}`);
      if (state.currentId !== id) return;
      body.innerHTML = detailTemplate(data);
      body.querySelectorAll("[data-goto]").forEach((el) => {
        el.addEventListener("click", () => openDetail(el.dataset.goto));
      });
    } catch (error) {
      body.innerHTML = `<p class="loading">GAGAL MEMUAT: ${esc(error.message)}</p>`;
    }
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
        <img src="/api/artifacts/${encodeURIComponent(art.id)}/svg?refresh=true" alt="Plakat ${esc(art.title)}" />
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

  function closeDetail() {
    state.currentId = null;
    $("#detail").classList.remove("open");
    $("#detail").setAttribute("aria-hidden", "true");
    $("#scrim").hidden = true;
    $("#detail-body").innerHTML = "";
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
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
      const data = await fetchJSON("/api/catalog");
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
      $("#status-text").textContent = "server tidak terjangkau";
      $("#status-dot").className = "dot";
    }
  }

  function boot() {
    $("#detail-close").addEventListener("click", closeDetail);
    $("#scrim").addEventListener("click", closeDetail);
    $("#clear-filters").addEventListener("click", () => {
      state.lineage.clear();
      state.material.clear();
      applyFilters();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && state.currentId) closeDetail();
    });
    window.addEventListener("hashchange", () => {
      const match = location.hash.match(/^#\/artefak\/(.+)$/);
      if (match) openDetail(decodeURIComponent(match[1]));
      else if (state.currentId) closeDetail();
    });

    const initial = location.hash.match(/^#\/artefak\/(.+)$/);
    refresh().then(() => {
      if (initial) openDetail(decodeURIComponent(initial[1]));
    });
    state.timer = setInterval(refresh, 6000);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
