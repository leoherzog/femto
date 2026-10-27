/*
 * Fixture loader for the femto parity harness. Every fixture page includes this one script in <head>.
 *
 * Query string:
 *   css   = comma-separated root-relative stylesheet URLs, written as blocking <link>s in order
 *   theme = light | dark          -> data-theme on <html>
 *   dir   = rtl                   -> dir="rtl" on <html>
 *   class = comma-separated list  -> classes added to <html>
 *
 * After DOMContentLoaded: sets .indeterminate on [data-indeterminate], calls showModal() on
 * dialog[data-show-modal], and gives every [data-shadow] host an open shadow root holding the same
 * stylesheets followed by a clone of the host's <template> child.
 *
 * window.__femto.ready resolves once every stylesheet (document and shadow roots) has loaded or failed;
 * window.__femto.errors lists failures. The harness waits on it and treats any error as a harness error.
 */
(function () {
  "use strict";
  var q = new URLSearchParams(location.search);
  var list = function (v) {
    return (v || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean);
  };
  var css = list(q.get("css"));
  var html = document.documentElement;
  var theme = q.get("theme");
  var femto = (window.__femto = { css: css, errors: [], ready: null, stage: "head" });

  if (theme === "light" || theme === "dark") html.setAttribute("data-theme", theme);
  else if (theme) femto.errors.push("unknown theme=" + theme);
  if (q.get("dir") === "rtl") html.setAttribute("dir", "rtl");
  else if (q.get("dir") && q.get("dir") !== "ltr") femto.errors.push("unknown dir=" + q.get("dir"));
  list(q.get("class")).forEach(function (c) { html.classList.add(c); });

  var esc = function (s) {
    return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  };
  css.forEach(function (href) {
    if (href.charAt(0) !== "/") femto.errors.push("stylesheet URL is not root-relative: " + href);
    document.write('<link rel="stylesheet" data-femto-css href="' + esc(href) + '">');
  });

  var waitFor = function (link) {
    return new Promise(function (resolve) {
      var done = function (ok) {
        if (!ok || !link.sheet) femto.errors.push("stylesheet failed to load: " + link.getAttribute("href"));
        resolve();
      };
      // A <link> that already finished has a sheet (success) or none (failure, checked after load).
      if (link.sheet) return resolve();
      link.addEventListener("load", function () { done(true); });
      link.addEventListener("error", function () { done(false); });
    });
  };

  var loaded = new Promise(function (resolve) {
    if (document.readyState === "complete") resolve();
    else window.addEventListener("load", function () { resolve(); });
  });

  var setup = new Promise(function (resolve) {
    document.addEventListener("DOMContentLoaded", function () {
      femto.stage = "dom";
      var pending = [];
      document.querySelectorAll("[data-indeterminate]").forEach(function (el) { el.indeterminate = true; });
      document.querySelectorAll("dialog[data-show-modal]").forEach(function (d) {
        try { d.showModal(); } catch (e) { femto.errors.push("showModal failed: " + e); }
      });
      document.querySelectorAll("[data-shadow]").forEach(function (host) {
        var tpl = host.querySelector(":scope > template");
        if (!tpl) { femto.errors.push("[data-shadow] host has no <template> child"); return; }
        var root;
        try { root = host.attachShadow({ mode: "open" }); }
        catch (e) { femto.errors.push("attachShadow failed on <" + host.localName + ">: " + e); return; }
        css.forEach(function (href) {
          var link = document.createElement("link");
          link.rel = "stylesheet";
          link.setAttribute("data-femto-css", "");
          link.href = href;
          root.appendChild(link);
          pending.push(waitFor(link));
        });
        root.appendChild(tpl.content.cloneNode(true));
      });
      resolve(Promise.all(pending));
    });
  });

  femto.ready = Promise.all([setup, loaded]).then(function () {
    document.querySelectorAll("link[data-femto-css]").forEach(function (link) {
      if (!link.sheet) femto.errors.push("stylesheet failed to load: " + link.getAttribute("href"));
    });
    femto.stage = "ready";
    return femto.errors;
  });
})();
