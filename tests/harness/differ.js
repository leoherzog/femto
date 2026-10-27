/*
 * femto parity harness: in-page collector and differ. Runs in the top-level host page
 * (/tests/harness/host.html) and drives a same-origin iframe of exact width.
 *
 * Python calls window.H.* through WebDriver. Snapshots stay in this page's memory; only
 * differences (already matched against the divergence registry) go back to Python.
 */
(function () {
  "use strict";
  const H = (window.H = {});

  // ---------------------------------------------------------------------------------------
  // Configuration and state
  // ---------------------------------------------------------------------------------------
  const PROBE_PROPS = [
    "color", "background-color", "border-top-color", "outline-color", "box-shadow",
    "background-image", "filter", "backdrop-filter", "opacity", "font-size", "font-family",
    "font-weight", "line-height", "letter-spacing", "width", "padding-top", "margin-top",
    "border-top-width", "border-top-left-radius", "outline-width", "outline-offset",
    "text-decoration-line", "text-underline-offset", "transition", "content",
  ];
  const SKIP_TAGS = new Set(["head", "meta", "title", "script", "link", "style", "template", "base", "noscript"]);
  const PROBE_TAGS = new Set(["femto-probe", "femto-mq", "femto-cover"]);
  const STATE_PSEUDO = { hover: ":hover", active: ":active", focus: ":focus", "focus-visible": ":focus-visible" };

  let cfg = {
    entries: [],          // registry entries already filtered by Python for this cell
    maxRecords: 300,      // unregistered records returned in detail per call
    pseudos: ["::before", "::after", "::marker", "::placeholder", "::file-selector-button", "::backdrop"],
    tokenPrefix: "--femto-",
    probeProps: PROBE_PROPS,
  };
  let compiled = [];
  let frame = null, win = null, doc = null;
  let els = [], index = new Map(), PROPS = null;
  const store = { ref: null, test: null };
  const stateRef = new Map();
  let harnessErrors = [];

  H.PROBE_PROPS = PROBE_PROPS;

  H.configure = function (c) {
    cfg = Object.assign({}, cfg, c || {});
    compiled = [];
    const errors = [];
    for (const e of cfg.entries || []) {
      try { compiled.push(compileEntry(e)); }
      catch (err) { errors.push("registry entry " + e.id + ": " + err.message); }
    }
    stateRef.clear();
    store.ref = store.test = null;
    return { ok: true, errors, entries: compiled.length };
  };

  H.hostStatus = function () {
    return {
      visibility: document.visibilityState,
      hasFocus: document.hasFocus(),
      dark: matchMedia("(prefers-color-scheme: dark)").matches,
      inner: [innerWidth, innerHeight],
      dpr: devicePixelRatio,
      ua: navigator.userAgent,
    };
  };

  // ---------------------------------------------------------------------------------------
  // Value comparison: exact, except colors (numeric, 1/255 per channel, 0.004 alpha)
  // ---------------------------------------------------------------------------------------
  const ctx = document.createElement("canvas").getContext("2d");
  const namedCache = new Map();
  const NOT_NAMED = new Set(["currentcolor", "inherit", "initial", "unset", "revert", "none", "auto"]);
  function namedColor(word) {
    const w = word.toLowerCase();
    if (namedCache.has(w)) return namedCache.get(w);
    let rgba = null;
    if (!NOT_NAMED.has(w)) {
      ctx.fillStyle = "#010203";
      ctx.fillStyle = w;
      const v = ctx.fillStyle;
      if (v !== "#010203" || w === "#010203") rgba = parseColor(v, true);
    }
    namedCache.set(w, rgba);
    return rgba;
  }
  function num(s, scale) {
    s = s.trim();
    if (s === "none") return 0;
    if (s.endsWith("%")) return (parseFloat(s) / 100) * scale;
    const v = parseFloat(s);
    return Number.isFinite(v) ? v : NaN;
  }
  function parseColor(s, noNamed) {
    s = s.trim();
    let m;
    if ((m = /^#([0-9a-f]{3,8})$/i.exec(s))) {
      let h = m[1];
      if (h.length === 3 || h.length === 4) h = h.split("").map((c) => c + c).join("");
      if (h.length !== 6 && h.length !== 8) return null;
      const n = (i) => parseInt(h.slice(i, i + 2), 16);
      return [n(0), n(2), n(4), h.length === 8 ? n(6) / 255 : 1];
    }
    if ((m = /^rgba?\((.*)\)$/i.exec(s))) {
      const parts = m[1].replace(/\//, ",").split(/[\s,]+/).filter(Boolean);
      if (parts.length < 3) return null;
      const c = [num(parts[0], 255), num(parts[1], 255), num(parts[2], 255), parts.length > 3 ? num(parts[3], 1) : 1];
      return c.some((x) => Number.isNaN(x)) ? null : c;
    }
    if ((m = /^color\(\s*srgb\s+(.*)\)$/i.exec(s))) {
      const [chan, alpha] = m[1].split("/");
      const parts = chan.trim().split(/\s+/);
      if (parts.length !== 3) return null;
      const c = [num(parts[0], 1) * 255, num(parts[1], 1) * 255, num(parts[2], 1) * 255, alpha ? num(alpha, 1) : 1];
      return c.some((x) => Number.isNaN(x)) ? null : c;
    }
    if (!noNamed && /^[a-z]+$/i.test(s)) return namedColor(s);
    return null;
  }
  // Split a value into color tokens and the remainder; quoted strings and url() stay in the remainder.
  const TOKEN_RE = /"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|url\([^)]*\)|rgba?\([^()]*\)|color\(\s*srgb[^()]*\)|#[0-9a-fA-F]{3,8}\b|\b[a-zA-Z]+\b/g;
  function tokenize(v) {
    const colors = [];
    const rest = v.replace(TOKEN_RE, (t) => {
      const c0 = t.charAt(0);
      if (c0 === '"' || c0 === "'" || /^url\(/i.test(t)) return t;
      const c = parseColor(t);
      if (!c) return t;
      colors.push(c);
      return "\u0000";
    });
    return { rest, colors };
  }
  function same(a, b) {
    if (a === b) return true;
    if (typeof a !== "string" || typeof b !== "string") return false;
    const ta = tokenize(a), tb = tokenize(b);
    if (!ta.colors.length || ta.rest !== tb.rest || ta.colors.length !== tb.colors.length) return false;
    for (let i = 0; i < ta.colors.length; i++) {
      const x = ta.colors[i], y = tb.colors[i];
      for (let k = 0; k < 3; k++) if (Math.abs(x[k] - y[k]) > 1 + 1e-6) return false;
      if (Math.abs(x[3] - y[3]) > 0.004 + 1e-9) return false;
    }
    return true;
  }
  H.same = same;

  // ---------------------------------------------------------------------------------------
  // Registry matching
  // ---------------------------------------------------------------------------------------
  function strPat(p) {
    if (p === undefined || p === null || p === "*") return () => true;
    if (typeof p === "string" && p.length > 2 && p.charAt(0) === "/" && p.lastIndexOf("/") > 0) {
      const k = p.lastIndexOf("/");
      const re = new RegExp(p.slice(1, k), p.slice(k + 1));
      return (v) => re.test(v == null ? "" : String(v));
    }
    return (v) => v === p;
  }
  function valPat(p) {
    if (p === undefined || p === null || p === "*") return () => true;
    if (typeof p === "string" && p.length > 2 && p.charAt(0) === "/" && p.lastIndexOf("/") > 0) return strPat(p);
    return (v) => same(p, v == null ? "" : String(v));
  }
  function compileEntry(e) {
    const sel = e.selector && e.selector !== "*" ? e.selector : null;
    if (sel) document.createDocumentFragment().querySelector(sel); // throws on invalid selectors
    return {
      id: e.id, kind: e.kind, sel,
      states: e.states || null,
      pseudo: e.pseudo === undefined ? () => true : strPat(e.pseudo),
      prop: strPat(e.property),
      token: strPat(e.token),
      check: strPat(e.check),
      ref: valPat(e.reference),
      test: valPat(e.femto),
    };
  }
  function matchRecord(rec, el) {
    const hits = [];
    for (const e of compiled) {
      if (e.kind !== rec.kind) continue;
      if (e.states && !e.states.includes(rec.state || "base")) continue;
      if (rec.kind === "style" && (!e.pseudo(rec.pseudo) || !e.prop(rec.prop))) continue;
      if ((rec.kind === "token" || rec.kind === "token-raw" || rec.kind === "surface-added" || rec.kind === "surface-missing") && !e.token(rec.token)) continue;
      if (rec.kind === "token" && !e.prop(rec.prop)) continue;
      if (rec.kind === "style" || rec.kind === "token" || rec.kind === "token-raw") {
        if (!e.ref(rec.ref) || !e.test(rec.test)) continue;
      }
      if (e.sel) {
        if (!el) continue;
        let ok = false;
        try { ok = el.matches(e.sel); } catch (err) { harnessErrors.push("registry " + e.id + ": " + err.message); }
        if (!ok) continue;
      }
      hits.push(e.id);
    }
    return hits;
  }
  function newResult() {
    return { total: 0, unregisteredTotal: 0, unregistered: [], registered: {}, samples: {}, counts: {} };
  }
  function addRecord(res, rec, el) {
    res.total++;
    res.counts[rec.kind] = (res.counts[rec.kind] || 0) + 1;
    const hits = matchRecord(rec, el);
    if (!hits.length) {
      res.unregisteredTotal++;
      if (res.unregistered.length < cfg.maxRecords) res.unregistered.push(rec);
      return;
    }
    for (const id of hits) {
      res.registered[id] = (res.registered[id] || 0) + 1;
      const s = (res.samples[id] = res.samples[id] || []);
      if (s.length < 2) s.push(rec);
    }
  }

  // ---------------------------------------------------------------------------------------
  // Document walking, labels, paths
  // ---------------------------------------------------------------------------------------
  function walk(d) {
    const out = [d.documentElement];
    const visit = (node) => {
      for (let c = node.firstElementChild; c; c = c.nextElementSibling) {
        const t = c.localName;
        if (SKIP_TAGS.has(t) || PROBE_TAGS.has(t)) continue;
        out.push(c);
        if (c.shadowRoot) visit(c.shadowRoot);
        visit(c);
      }
    };
    visit(d.documentElement);
    return out;
  }
  function composedParent(el) {
    if (el.parentElement) return el.parentElement;
    const r = el.parentNode;
    return r && r.host ? r.host : null;
  }
  function composedContains(a, b) {
    for (let x = b; x; x = composedParent(x)) if (x === a) return true;
    return false;
  }
  function label(el) {
    let s = el.localName;
    if (el.id) s += "#" + el.id;
    if (el.classList && el.classList.length) s += "." + [...el.classList].join(".");
    const attrs = [];
    for (const a of ["type", "role", "data-theme", "dir", "aria-invalid", "aria-busy", "aria-current", "data-tooltip", "data-placement", "open", "disabled", "checked", "readonly", "multiple", "data-module"]) {
      if (el.hasAttribute && el.hasAttribute(a)) {
        const v = el.getAttribute(a);
        attrs.push(v === "" ? a : a + "=" + (v.length > 20 ? v.slice(0, 20) + "~" : v));
      }
    }
    if (attrs.length) s += "[" + attrs.join(" ") + "]";
    let text = "";
    for (const n of el.childNodes) if (n.nodeType === 3) text += n.textContent;
    text = text.trim().replace(/\s+/g, " ");
    if (text) s += ' "' + (text.length > 24 ? text.slice(0, 24) + "~" : text) + '"';
    if (el.getRootNode() !== el.ownerDocument) s += " (shadow)";
    return s;
  }
  function step(el) {
    if (el.hasAttribute("data-module")) return '[data-module="' + el.getAttribute("data-module") + '"]';
    let s = el.localName;
    if (el.id) return s + "#" + el.id;
    const p = el.parentNode;
    if (p && p.children) {
      const same = [...p.children].filter((c) => c.localName === el.localName);
      if (same.length > 1) s += ":nth-of-type(" + (same.indexOf(el) + 1) + ")";
    }
    return s;
  }
  function path(el) {
    const parts = [];
    for (let x = el; x; ) {
      parts.unshift(step(x));
      if (x.hasAttribute("data-module") || x.localName === "html") break;
      if (x.parentElement) { x = x.parentElement; continue; }
      const r = x.parentNode;
      if (r && r.host) { parts.unshift(">>>"); x = r.host; continue; }
      break;
    }
    return parts.join(" > ").replace(/ > >>> > /g, " >>> ");
  }

  // ---------------------------------------------------------------------------------------
  // Loading a fixture into a fresh iframe
  // ---------------------------------------------------------------------------------------
  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
  function withTimeout(p, ms, what) {
    return Promise.race([p, sleep(ms).then(() => { throw new Error("timeout: " + what); })]);
  }

  H.load = async function (url, width, height, expect) {
    const t0 = performance.now();
    harnessErrors = [];
    const box = document.getElementById("box");
    box.textContent = "";
    window.scrollTo(0, 0);
    frame = document.createElement("iframe");
    frame.id = "frame";
    frame.style.width = width + "px";
    frame.style.height = height + "px";
    const loaded = new Promise((resolve) => frame.addEventListener("load", resolve, { once: true }));
    frame.src = url;
    box.appendChild(frame);
    const errors = [];
    try {
      await withTimeout(loaded, 30000, "iframe load " + url);
      win = frame.contentWindow;
      doc = frame.contentDocument;
      if (!win.__femto) throw new Error("page.js did not run (window.__femto missing) in " + url);
      const errs = await withTimeout(win.__femto.ready, 30000, "page.js ready");
      for (const e of errs) errors.push(e);
    } catch (e) {
      errors.push(String(e && e.message ? e.message : e));
      return { errors, ms: performance.now() - t0 };
    }
    // Cancel activation behavior (navigation, toggles, submits) of synthetic clicks.
    const cancel = (e) => e.preventDefault();
    doc.addEventListener("click", cancel, true);
    doc.addEventListener("submit", cancel, true);
    doc.addEventListener("auxclick", cancel, true);
    // A pointer-down on <select> opens the native picker, which then swallows later input and
    // differs run to run. Cancelling mousedown on select keeps :active but skips focus and the picker.
    doc.addEventListener("mousedown", (e) => {
      if (e.target && e.target.closest && e.target.closest("select")) e.preventDefault();
    }, true);
    els = walk(doc);
    index = new Map(els.map((el, i) => [el, i]));
    PROPS = null;
    const info = checkEnv(width, expect);
    for (const e of info.errors) errors.push(e);
    return { errors, info, elements: els.length, ms: performance.now() - t0 };
  };

  function checkEnv(width, expect) {
    const errors = [];
    const head = doc.head || doc.documentElement;
    const style = doc.createElement("style");
    style.textContent =
      "femto-mq{order:1;z-index:1}" +
      "@media (prefers-color-scheme: dark){femto-mq{order:2}}" +
      "@media (width: " + width + "px){femto-mq{z-index:7}}";
    const probe = doc.createElement("femto-mq");
    head.appendChild(style);
    head.appendChild(probe);
    const cs = win.getComputedStyle(probe);
    const info = {
      innerWidth: win.innerWidth,
      mqWidth: win.matchMedia("(width: " + width + "px)").matches,
      cssWidth: cs.getPropertyValue("z-index") === "7",
      dark: win.matchMedia("(prefers-color-scheme: dark)").matches,
      cssDark: cs.getPropertyValue("order") === "2",
      theme: doc.documentElement.getAttribute("data-theme"),
      dir: doc.documentElement.getAttribute("dir"),
      classes: doc.documentElement.className,
      visibility: doc.visibilityState,
      errors,
    };
    probe.remove();
    style.remove();
    if (info.innerWidth !== width) errors.push("viewport: innerWidth " + info.innerWidth + " != " + width);
    if (!info.mqWidth || !info.cssWidth) errors.push("viewport: (width: " + width + "px) media query does not match (matchMedia " + info.mqWidth + ", CSS " + info.cssWidth + ")");
    if (expect && expect.media) {
      const want = expect.media === "dark";
      if (info.dark !== want || info.cssDark !== want)
        errors.push("color scheme: expected prefers-color-scheme " + expect.media + ", matchMedia dark=" + info.dark + ", CSS dark=" + info.cssDark);
    }
    if (expect && "theme" in expect && (expect.theme || null) !== info.theme) errors.push("data-theme on html is " + info.theme + ", expected " + expect.theme);
    return info;
  }

  // ---------------------------------------------------------------------------------------
  // Animations: finish transitions and finite animations, pause infinite ones at 0
  // ---------------------------------------------------------------------------------------
  function allAnimations() {
    const set = new Set(doc.getAnimations());
    for (const el of els) if (el.shadowRoot) for (const a of el.shadowRoot.getAnimations()) set.add(a);
    return set;
  }
  H.freeze = function () {
    let finished = 0, paused = 0;
    for (let round = 0; round < 3; round++) {
      const anims = allAnimations();
      let changed = 0;
      for (const a of anims) {
        const t = a.effect ? a.effect.getComputedTiming() : null;
        if (t && t.endTime === Infinity) {
          if (a.playState !== "paused" || a.currentTime !== 0) { a.pause(); a.currentTime = 0; paused++; changed++; }
        } else if (a.playState !== "finished") {
          try { a.finish(); finished++; changed++; } catch (e) { a.cancel(); }
        }
      }
      if (!changed) break;
    }
    return { finished, paused };
  };

  // ---------------------------------------------------------------------------------------
  // Computed style collection
  // ---------------------------------------------------------------------------------------
  function props() {
    if (PROPS) return PROPS;
    const cs = win.getComputedStyle(doc.documentElement);
    const list = [];
    for (let i = 0; i < cs.length; i++) if (!cs[i].startsWith("--")) list.push(cs[i]);
    return (PROPS = list);
  }
  function read(cs, P) {
    const v = new Array(P.length);
    for (let j = 0; j < P.length; j++) v[j] = cs.getPropertyValue(P[j]);
    return v;
  }
  function absent(c) { return c === "none" || c === "normal" || c === ""; }
  function collectEl(el, P) {
    const base = read(win.getComputedStyle(el), P);
    const s = { "": base };
    const want = cfg.pseudos;
    for (const ps of ["::before", "::after"]) {
      if (!want.includes(ps)) continue;
      const cs = win.getComputedStyle(el, ps);
      const c = cs.getPropertyValue("content");
      s[ps] = absent(c) ? { absent: c || "none" } : read(cs, P);
    }
    const t = el.localName;
    const disp = base[P.indexOf("display")] || "";
    if (want.includes("::marker") && (t === "li" || t === "summary" || disp.includes("list-item"))) s["::marker"] = read(win.getComputedStyle(el, "::marker"), P);
    if (want.includes("::placeholder") && el.hasAttribute("placeholder")) s["::placeholder"] = read(win.getComputedStyle(el, "::placeholder"), P);
    if (want.includes("::file-selector-button") && t === "input" && (el.getAttribute("type") || "").toLowerCase() === "file") s["::file-selector-button"] = read(win.getComputedStyle(el, "::file-selector-button"), P);
    if (want.includes("::backdrop") && t === "dialog") s["::backdrop"] = read(win.getComputedStyle(el, "::backdrop"), P);
    return s;
  }
  function snapshot(list) {
    const P = props();
    const out = new Map();
    for (const i of list) out.set(i, { label: label(els[i]), path: path(els[i]), s: collectEl(els[i], P) });
    return out;
  }

  // Chrome and Safari run ::file-selector-button transitions on a UA shadow element that
  // getAnimations() does not return, so finish() cannot reach them (and a hidden Safari page never
  // advances them). A transient "transition: none !important" for that pseudo-element cancels
  // them, which jumps to the end value; removing it changes no animated value, so nothing restarts.
  async function settle(list) {
    if (!cfg.pseudos.includes("::file-selector-button")) return 0;
    const files = list.map((i) => els[i]).filter((el) => el.localName === "input" && (el.getAttribute("type") || "").toLowerCase() === "file");
    if (!files.length) return 0;
    const t0 = performance.now();
    const roots = new Set(files.map((el) => el.getRootNode()));
    const styles = [];
    for (const r of roots) {
      const st = doc.createElement("style");
      st.textContent = "input[type=file]::file-selector-button { transition: none !important; }";
      (r === doc ? doc.head || doc.documentElement : r).appendChild(st);
      styles.push(st);
    }
    for (const el of files) win.getComputedStyle(el, "::file-selector-button").getPropertyValue("background-color");
    for (const st of styles) st.remove();
    for (const el of files) win.getComputedStyle(el, "::file-selector-button").getPropertyValue("background-color");
    return performance.now() - t0;
  }

  H.collect = async function (side) {
    const fr0 = H.freeze();
    await settle(els.map((_, i) => i));
    const t0 = performance.now();
    const all = els.map((_, i) => i);
    const snap = { props: props(), els: snapshot(all), n: els.length };
    const t1 = performance.now();
    const tokens = collectTokens();
    const t2 = performance.now();
    store[side] = Object.assign(snap, { tokens });
    const fr = H.freeze();
    let pseudoCount = 0;
    for (const e of snap.els.values()) pseudoCount += Object.keys(e.s).filter((k) => k && Array.isArray(e.s[k])).length;
    return {
      elements: els.length, pseudo: pseudoCount, props: snap.props.length,
      tokens: tokens.names.length, anchors: tokens.anchors.length, groups: tokens.groups,
      freezeBefore: fr0, freezeAfterTokens: fr, msStyles: t1 - t0, msTokens: t2 - t1,
      errors: harnessErrors.splice(0),
    };
  };

  function diffStyleMaps(res, refMap, testMap, P, state) {
    for (const [i, r] of refMap) {
      const t = testMap.get(i);
      if (!t) { harnessErrors.push("element " + i + " missing on the test side"); continue; }
      if (r.label !== t.label) harnessErrors.push("element " + i + " differs between sides: " + r.label + " vs " + t.label);
      const el = els[i];
      const keys = new Set([...Object.keys(r.s), ...Object.keys(t.s)]);
      for (const ps of keys) {
        const a = r.s[ps], b = t.s[ps];
        const base = { kind: "style", state: state || "base", el: i, label: r.label, path: r.path, pseudo: ps };
        // ::marker is collected by display; a display difference is reported on the element itself.
        if (!a || !b) continue;
        const aAbs = !Array.isArray(a), bAbs = !Array.isArray(b);
        if (aAbs || bAbs) {
          if (aAbs && bAbs) continue;
          const ci = P.indexOf("content");
          addRecord(res, Object.assign(base, { prop: "content", ref: aAbs ? a.absent : a[ci], test: bAbs ? b.absent : b[ci], presence: true }), el);
          continue;
        }
        for (let j = 0; j < P.length; j++) {
          if (a[j] !== b[j] && !same(a[j], b[j])) addRecord(res, Object.assign({}, base, { prop: P[j], ref: a[j], test: b[j] }), el);
        }
      }
    }
  }

  H.diff = function () {
    const t0 = performance.now();
    const res = newResult();
    const r = store.ref, t = store.test;
    if (!r || !t) throw new Error("diff needs both snapshots");
    if (r.n !== t.n) harnessErrors.push("element count differs: ref " + r.n + ", test " + t.n);
    if (r.props.join() !== t.props.join()) harnessErrors.push("computed property lists differ between loads");
    diffStyleMaps(res, r.els, t.els, r.props, "base");
    diffTokens(res, r.tokens, t.tokens);
    res.ms = performance.now() - t0;
    res.errors = harnessErrors.splice(0);
    return res;
  };

  // ---------------------------------------------------------------------------------------
  // Tokens: names from the CSSOM, resolution through real properties at anchors
  // ---------------------------------------------------------------------------------------
  function tokenNames() {
    const names = new Set(), seen = new Set(), errors = [];
    const walkRules = (rules) => {
      for (const r of rules) {
        if (r.styleSheet) walkSheet(r.styleSheet);
        if (r.style) for (let i = 0; i < r.style.length; i++) { const n = r.style[i]; if (n.startsWith(cfg.tokenPrefix)) names.add(n); }
        if (typeof r.name === "string" && r.name.startsWith(cfg.tokenPrefix) && r.constructor && /Property/.test(r.constructor.name)) names.add(r.name);
        if (r.cssRules) walkRules(r.cssRules);
      }
    };
    const walkSheet = (s) => {
      if (!s || seen.has(s)) return;
      seen.add(s);
      let rules;
      try { rules = s.cssRules; } catch (e) { errors.push("cannot read cssRules of " + s.href + ": " + e.message); return; }
      walkRules(rules);
    };
    for (const s of doc.styleSheets) walkSheet(s);
    for (const el of els) if (el.shadowRoot) {
      for (const s of el.shadowRoot.styleSheets) walkSheet(s);
      for (const s of el.shadowRoot.adoptedStyleSheets || []) walkSheet(s);
    }
    for (const e of errors) harnessErrors.push(e);
    return [...names].sort();
  }
  function anchors() {
    const list = [], seen = new Set();
    const add = (el, root, tag) => {
      const key = index.get(el) + (tag || "");
      if (seen.has(key)) return;
      seen.add(key);
      list.push({ el, root, i: index.get(el), key, label: label(el) + (tag || "") });
    };
    add(doc.documentElement, doc.documentElement);
    if (doc.body) add(doc.body, doc.body);
    for (const el of els) {
      if (el.hasAttribute("data-theme") || el.localName === "article" || el.localName === "dialog" || el.hasAttribute("data-module")) add(el, el);
      if (el.shadowRoot) add(el, el.shadowRoot, " >>> shadow root");
    }
    return list;
  }
  function collectTokens() {
    const names = tokenNames();
    const A = anchors();
    const P = cfg.probeProps;
    const raw = [], sig = [], groupOf = new Map();
    A.forEach((a, k) => {
      const cs = win.getComputedStyle(a.el);
      const r = names.map((n) => cs.getPropertyValue(n).trim());
      raw[k] = r;
      sig[k] = cs.getPropertyValue("color-scheme") + "\u0002" + r.join("\u0001");
      if (!groupOf.has(sig[k])) groupOf.set(sig[k], k);
    });
    const resolved = new Map();
    const tmpl = P.map((p) => p + ": var(\u0003)").join("; ");
    for (const [s, k] of groupOf) {
      const a = A[k];
      const box = doc.createElement("femto-probe");
      box.setAttribute("style", "all: initial; color-scheme: inherit; display: none");
      const probes = names.map((n) => {
        const p = doc.createElement("femto-probe");
        p.setAttribute("style", tmpl.split("\u0003").join(n));
        box.appendChild(p);
        return p;
      });
      a.root.appendChild(box);
      resolved.set(s, probes.map((p) => read(win.getComputedStyle(p), P)));
      box.remove();
    }
    return {
      names, anchors: A.map((a) => ({ i: a.i, key: a.key, label: a.label, path: path(a.el) })),
      raw, sig, resolved, groups: groupOf.size,
    };
  }
  function diffTokens(res, r, t) {
    const rs = new Set(r.names), ts = new Set(t.names);
    for (const n of r.names) if (!ts.has(n)) addRecord(res, { kind: "surface-missing", token: n }, null);
    for (const n of t.names) if (!rs.has(n)) addRecord(res, { kind: "surface-added", token: n }, null);
    const common = r.names.filter((n) => ts.has(n));
    const ri = new Map(r.names.map((n, i) => [n, i])), ti = new Map(t.names.map((n, i) => [n, i]));
    const tAnch = new Map(t.anchors.map((a, k) => [a.key, k]));
    const P = cfg.probeProps;
    r.anchors.forEach((a, k) => {
      const tk = tAnch.get(a.key);
      if (tk === undefined) { harnessErrors.push("token anchor missing on the test side: " + a.label); return; }
      const el = els[a.i];
      const rr = r.resolved.get(r.sig[k]), tr = t.resolved.get(t.sig[tk]);
      for (const n of common) {
        const x = ri.get(n), y = ti.get(n);
        const rawA = r.raw[k][x], rawB = t.raw[tk][y];
        const base = { anchor: a.i, label: a.label, path: a.path, token: n, state: "base" };
        if (rawA !== rawB) addRecord(res, Object.assign({ kind: "token-raw", ref: rawA, test: rawB }, base), el);
        const va = rr[x], vb = tr[y];
        for (let j = 0; j < P.length; j++) {
          if (va[j] !== vb[j] && !same(va[j], vb[j])) addRecord(res, Object.assign({ kind: "token", prop: P[j], ref: va[j], test: vb[j] }, base), el);
        }
      }
    });
  }

  // ---------------------------------------------------------------------------------------
  // Interactive states
  // ---------------------------------------------------------------------------------------
  H.stateTargets = function () {
    const out = [];
    els.forEach((el, i) => {
      if (!el.hasAttribute("data-states")) return;
      const states = el.getAttribute("data-states").split(/\s+/).filter(Boolean);
      out.push({ el: i, label: label(el), path: path(el), states, tag: el.localName, type: (el.getAttribute("type") || "").toLowerCase() });
    });
    return out;
  };
  function deepActive() {
    let a = doc.activeElement;
    while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
    return a;
  }
  function frames(n) {
    // Two animation frames let async scrolling (Firefox APZ) settle before input is hit-tested.
    // rAF does not run in hidden pages, so a timeout caps the wait.
    // A hidden page (Safari on a locked screen) never runs rAF and never paints: nothing to wait for.
    if (document.visibilityState === "hidden") return Promise.resolve();
    return new Promise((resolve) => {
      let k = 0;
      const step = () => (++k >= n ? resolve() : win.requestAnimationFrame(step));
      win.requestAnimationFrame(step);
      setTimeout(resolve, 150);
    });
  }
  H.pointAt = async function (i) {
    const el = els[i];
    const before = win.scrollX + "," + win.scrollY;
    el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
    window.scrollTo(0, 0);
    const scrolled = before !== win.scrollX + "," + win.scrollY;
    if (scrolled) await frames(2);
    const fr = frame.getBoundingClientRect();
    const root = el.getRootNode();
    const finder = root.elementFromPoint ? root : doc;
    // Try the element's line boxes, largest first, so a wrapped inline element is pointed at on
    // its own text; keep the first point that hit-tests to the element.
    const rects = [...el.getClientRects()].filter((r) => r.width >= 1 && r.height >= 1)
      .sort((a, b) => b.width * b.height - a.width * a.height);
    if (!rects.length) rects.push(el.getBoundingClientRect());
    let best = null;
    for (const r of rects) {
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const hit = finder.elementFromPoint(cx, cy);
      const ok = !!hit && (hit === el || composedContains(el, hit));
      // A point outside the iframe viewport cannot be reached by the pointer (a transform can put
      // an element where no scrolling reaches it); report it instead of moving there.
      const inside = cx >= 0 && cy >= 0 && cx < frame.clientWidth && cy < frame.clientHeight;
      const cand = { x: Math.round(fr.left + cx), y: Math.round(fr.top + cy), size: [r.width, r.height], scrolled,
                     hit: ok && inside, outside: !inside, hitLabel: !inside ? "outside the viewport" : (hit ? label(hit) : null) };
      if (!inside) { if (!best) best = cand; continue; }
      if (!best) best = cand;
      if (ok) { best = cand; break; }
    }
    return best;
  };
  H.focusEl = function (i) {
    const el = els[i];
    el.focus();
    return { focused: deepActive() === el };
  };
  function focusables() {
    return els.filter((el) => {
      if (el.tabIndex < 0 || el.disabled || el.inert || el.closest("[inert]")) return false;
      if (el.localName === "input" && el.type === "hidden") return false;
      if (!el.getClientRects().length) return false;
      const cs = win.getComputedStyle(el);
      return cs.visibility === "visible" && cs.display !== "none";
    });
  }
  // Focus the focusable before (dir=1) or after (dir=-1) the target, so a Tab (or Shift+Tab) lands on it.
  H.prepTab = function (i, dir) {
    const el = els[i];
    const list = focusables();
    const k = list.indexOf(el);
    const other = k < 0 ? null : list[k - (dir || 1)];
    const a = deepActive();
    if (a && a.blur) a.blur();
    if (other) {
      other.focus();
      return { from: label(other), ok: deepActive() === other, inList: k >= 0 };
    }
    win.focus();
    return { from: null, ok: true, inList: k >= 0 };
  };
  H.afterState = async function (side, i, state, key) {
    const el = els[i];
    const sel = STATE_PSEUDO[state];
    const matched = !!sel && el.matches(sel);
    const info = { matched, active: deepActive() ? label(deepActive()) : null };
    if (!matched) return info;
    H.freeze();
    let wrap = el;
    for (let x = el; x; x = composedParent(x)) if (x.hasAttribute && x.hasAttribute("data-module")) { wrap = x; break; }
    const list = [];
    els.forEach((e, k) => { if (composedContains(wrap, e)) list.push(k); });
    info.settleMs = await settle(list);
    if (!el.matches(sel)) { info.matched = false; info.error = "state was lost while transitions settled"; return info; }
    const snap = snapshot(list);
    info.elements = list.length;
    if (side === "ref") {
      stateRef.set(key, snap);
      return info;
    }
    const ref = stateRef.get(key);
    if (!ref) { info.error = "no reference snapshot for state " + key; return info; }
    const res = newResult();
    diffStyleMaps(res, ref, snap, props(), state);
    res.errors = harnessErrors.splice(0);
    info.result = res;
    return info;
  };
  H.resetState = function () {
    const a = deepActive();
    if (a && a !== doc.body && a.blur) a.blur();
    return H.freeze();
  };

  // ---------------------------------------------------------------------------------------
  // Screenshots: scroll to top, cover [aria-busy=true] (its SVG animation cannot be frozen)
  // ---------------------------------------------------------------------------------------
  H.prepShot = async function () {
    H.resetState();
    const scrolled = win.scrollX !== 0 || win.scrollY !== 0;
    // Overlay scrollbars fade in and out after scrolling; hide them for the shot only.
    const hide = doc.createElement("style");
    hide.id = "femto-harness-shot";
    hide.textContent = "* { scrollbar-width: none !important; }";
    (doc.head || doc.documentElement).appendChild(hide);
    window.scrollTo(0, 0);
    // Firefox applies and paints scrolling asynchronously, and a scroll-into-view queued by the last
    // keyboard focus can land after scrollTo(). Scroll to the top until it stays there.
    let settled = 0;
    for (let k = 0; k < 20 && settled < 2; k++) {
      win.scrollTo({ left: 0, top: 0, behavior: "instant" });
      await frames(scrolled ? 2 : 1);
      settled = win.scrollX === 0 && win.scrollY === 0 ? settled + 1 : 0;
    }
    H.freeze();
    let n = 0;
    const busy = [];
    // Media controls draw their time display asynchronously (Firefox shows "0:00" in one load and
    // not the next), so they are covered too.
    for (const el of els) {
      if (el.getAttribute("aria-busy") === "true" || ((el.localName === "video" || el.localName === "audio") && el.hasAttribute("controls"))) busy.push(el);
    }
    for (const el of busy) {
      for (const r of el.getClientRects()) {
        const c = doc.createElement("femto-cover");
        c.setAttribute("style", "all: initial; position: absolute; z-index: 2147483647; background: #f0f; pointer-events: none;" +
          "left:" + (r.left + win.scrollX - 2) + "px; top:" + (r.top + win.scrollY - 2) + "px; width:" + (r.width + 4) + "px; height:" + (r.height + 4) + "px");
        doc.documentElement.appendChild(c);
        n++;
      }
    }
    return { covers: n };
  };
  H.unmask = function () {
    doc.querySelectorAll("femto-cover, style#femto-harness-shot").forEach((c) => c.remove());
    return true;
  };

  // ---------------------------------------------------------------------------------------
  // Rig probe: which pseudo-elements getComputedStyle supports in this browser
  // ---------------------------------------------------------------------------------------
  H.probePseudos = function () {
    const out = {};
    const g = (id, ps, p) => {
      try { return win.getComputedStyle(doc.getElementById(id), ps).getPropertyValue(p); } catch (e) { return "ERR " + e.message; }
    };
    const dlg = doc.getElementById("dlg");
    out["::before"] = g("b", "::before", "color") === "rgb(13, 14, 15)" && g("b", "::before", "content") === '"b"';
    out["::after"] = g("b", "::after", "color") === "rgb(16, 17, 18)";
    out["::marker"] = g("li", "::marker", "color") === "rgb(1, 2, 3)" && g("sum", "::marker", "color") === "rgb(19, 20, 21)";
    out["::placeholder"] = g("ph", "::placeholder", "color") === "rgb(4, 5, 6)";
    out["::file-selector-button"] = g("fb", "::file-selector-button", "color") === "rgb(7, 8, 9)";
    const closed = g("dlg", "::backdrop", "background-color");
    dlg.showModal();
    const open = g("dlg", "::backdrop", "background-color");
    dlg.close();
    out["::backdrop"] = open === "rgb(10, 11, 12)";
    out.backdropClosed = closed;
    out.summaryDisplay = g("sum", null, "display");
    out.props = props().length;
    return out;
  };

  // ---------------------------------------------------------------------------------------
  // Selector coverage (run.py coverage)
  // ---------------------------------------------------------------------------------------
  H.coverage = function (selectors) {
    // selectors: [{id, stripped, prefixes: [{state, stripped}]}]
    const roots = [doc];
    for (const el of els) if (el.shadowRoot) roots.push(el.shadowRoot);
    const out = {};
    const matchAll = (sel) => {
      const found = [];
      for (const r of roots) for (const e of r.querySelectorAll(sel)) found.push(e);
      return found;
    };
    for (const s of selectors) {
      const o = { matched: 0, error: null, states: {} };
      try { o.matched = matchAll(s.stripped).length; } catch (e) { o.error = e.message; }
      for (const p of s.prefixes || []) {
        let ok = false, n = 0;
        try {
          const found = matchAll(p.stripped);
          n = found.length;
          ok = found.some((e) => {
            const own = (e.getAttribute("data-states") || "").split(/\s+/);
            const desc = [...e.querySelectorAll("[data-states]")].map((d) => d.getAttribute("data-states").split(/\s+/)).flat();
            if (p.state === "hover" || p.state === "active") return own.includes(p.state) || desc.includes(p.state);
            if (p.state === "focus") return own.includes("focus") || own.includes("focus-visible");
            if (p.state === "focus-visible") return own.includes("focus-visible");
            if (p.state === "focus-within") return [...own, ...desc].some((x) => x === "focus" || x === "focus-visible");
            return false;
          });
        } catch (e) { o.error = o.error || e.message; }
        o.states[p.state + " " + p.stripped] = { elements: n, covered: ok };
      }
      out[s.id] = o;
    }
    return out;
  };
})();
