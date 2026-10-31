// Interactive bar charts for docs/benchmarks.md, drawn from the benchmark results JSON.
// No library: plain SVG, colored by CSS variables so they follow the light/dark theme.
(function () {
  "use strict";

  const LABELS = {
    nuboard: "nuboard",
    tensorboardX: "tensorboardX",
    torch: "torch.utils.tensorboard",
  };
  const CASES = {
    scalars_us: { unit: "µs per step", fmt: (v) => fmt(v, 1) + " µs" },
    slowdown_pct: { unit: "% throughput lost", fmt: (v) => fmt(v, 1) + "%" },
    image_ms: { unit: "ms per image", fmt: (v) => fmt(v, 2) + " ms" },
    write_1m_s: { unit: "seconds", fmt: (v) => fmt(v, 2) + " s" },
    read_1m_s: { unit: "seconds", fmt: (v) => fmt(v, 2) + " s" },
    disk_1m_mb: { unit: "MB", fmt: (v) => fmt(v, 1) + " MB" },
  };
  const NS = "http://www.w3.org/2000/svg";
  const SHORT = { torch: "torch TB" };  // on narrow screens
  const ROW = 34, TOP = 6, AXIS = 40;
  let data = null;

  function fmt(v, digits) {
    return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function el(name, attrs, parent, text) {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceTicks(max) {
    const step = Math.pow(10, Math.floor(Math.log10(max)));
    const unit = [1, 2, 5, 10].map((m) => m * step).find((s) => max / s <= 6);
    const ticks = [];
    for (let t = 0; t < max + unit; t += unit) ticks.push(t);  // the last tick is past max
    return ticks;
  }

  function ratio(v, ours) {
    if (!ours || v <= ours) return "";
    const r = v / ours;
    return r >= 10 ? `${Math.round(r).toLocaleString("en-US")}× nuboard` : `${r.toFixed(1)}× nuboard`;
  }

  function draw(box) {
    const key = box.dataset.case;
    const spec = CASES[key];
    const writers = Object.keys(LABELS).filter((w) => data[w] && data[w][key] !== undefined);
    const values = writers.map((w) => data[w][key]);
    const ours = data.nuboard ? data.nuboard[key] : null;
    const max = Math.max(...values);
    const W = Math.max(280, Math.round(box.clientWidth || 720));
    const narrow = W < 520;
    const LEFT = narrow ? 100 : 190, RIGHT = narrow ? 70 : 96;
    const name = (w) => (narrow && SHORT[w]) || LABELS[w];
    const plotW = W - LEFT - RIGHT;
    const H = TOP + ROW * writers.length + AXIS;
    const ticks = niceTicks(max);
    const top = ticks[ticks.length - 1];
    const x = (v) => (v / top) * plotW;

    box.replaceChildren();
    if (box.dataset.title) {
      const head = document.createElement("div");
      head.className = "nb-bench-title";
      head.textContent = box.dataset.title;
      box.appendChild(head);
    }
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": box.dataset.title || key }, box);
    const g = el("g", { transform: `translate(${LEFT},${TOP})` }, svg);

    for (const t of ticks) {
      el("line", { class: "nb-bench-grid", x1: x(t), x2: x(t), y1: 0, y2: ROW * writers.length }, g);
      el("text", { class: "nb-bench-tick", x: x(t), y: ROW * writers.length + 16, "text-anchor": "middle" }, g,
        t >= 1000 ? t.toLocaleString("en-US") : String(+t.toPrecision(3)));
    }

    el("text", { class: "nb-bench-unit", x: plotW / 2, y: ROW * writers.length + 34, "text-anchor": "middle" }, g,
      `${spec.unit}, lower is better`);

    writers.forEach((w, i) => {
      const v = values[i];
      const y = i * ROW;
      const row = el("g", { class: "nb-bench-row" + (w === "nuboard" ? " nb-bench-us" : "") }, g);
      const tip = [`${LABELS[w]}: ${spec.fmt(v)}`, ratio(v, ours)].filter(Boolean).join(" · ");
      el("title", {}, row, tip);
      el("rect", { class: "nb-bench-hit", x: -LEFT, y, width: W, height: ROW }, row);
      el("text", { class: "nb-bench-label", x: -10, y: y + ROW / 2, "text-anchor": "end", "dominant-baseline": "central" }, row, name(w));
      el("rect", { class: "nb-bench-bar", x: 0, y: y + 6, width: Math.max(x(v), 2), height: ROW - 12, rx: 3 }, row);
      el("text", { class: "nb-bench-value", x: Math.max(x(v), 2) + 8, y: y + ROW / 2, "dominant-baseline": "central" }, row, spec.fmt(v));
      row.addEventListener("mouseenter", () => show(box, tip));
      row.addEventListener("mouseleave", () => show(box, ""));
    });

    const note = document.createElement("div");
    note.className = "nb-bench-note";
    note.textContent = " ";
    box.appendChild(note);
  }

  function show(box, text) {
    const note = box.querySelector(".nb-bench-note");
    if (note) note.textContent = text || " ";
  }

  function drawAll() {
    document.querySelectorAll(".nb-bench[data-case]").forEach(draw);
  }

  async function init() {
    const boxes = document.querySelectorAll(".nb-bench[data-case]");
    if (!boxes.length) return;
    try {
      const res = await fetch(boxes[0].dataset.src);
      data = (await res.json()).results;
    } catch (err) {
      boxes.forEach((b) => (b.textContent = "Could not load the benchmark results."));
      return;
    }
    drawAll();
  }

  let resizing = 0;
  window.addEventListener("resize", () => {
    if (!data) return;
    clearTimeout(resizing);
    resizing = setTimeout(drawAll, 150);  // charts are drawn at their real width
  });

  // Material's instant navigation swaps pages without a reload; document$ fires on each
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(init);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
