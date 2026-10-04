// An alert shown the way the brief asks: what happened, where the evidence comes from,
// how confident it is, who should verify, and what people should do now.
// The words come from i18n.js, so the block follows the page's language.
(() => {
  function row(dl, term, text, cls) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = text;
    if (cls) dd.className = cls;
    dl.append(dt, dd);
  }

  window.renderEvidence = (alert) => {
    const dl = document.createElement("dl");
    dl.className = "evidence";
    const e = alert.evidence;
    if (!e) {
      row(dl, t("ev.what"), t("ev.fallback", { n: alert.reports, people: alert.reporters }));
      return dl;
    }
    const signs = e.what.signals.map((s) => `${s.label} (${s.count})`).join(", ") || t("ev.signs");
    row(dl, t("ev.what"), t("ev.summary", { n: e.what.reports, r: e.what.radius_m, signs, h: e.what.hours }));
    const ev = e.evidence;
    let source = t("ev.source", { people: ev.reporters, photos: ev.photos });
    if (ev.confirmed_on_site) source += t("ev.confirmed", { n: ev.confirmed_on_site });
    else if (ev.ai_suspected) source += t("ev.ai", { n: ev.ai_suspected });
    row(dl, t("ev.evidence"), source + ".");
    let conf = `${e.confidence_label[0].toUpperCase()}${e.confidence_label.slice(1)}`;
    if (e.confidence !== null) {
      const number = e.confidence.toFixed(2);
      conf += ` (${window.AquaLang.code === "en" ? number : number.replace(".", ",")})`;
    }
    if (ev.at_night && ev.at_night * 2 > e.what.reports) conf += t("ev.night");
    row(dl, t("ev.confidence"), conf + ".");
    row(dl, t("ev.who"), e.verifier + ".");
    row(dl, t("ev.do"), e.advice, "do");
    return dl;
  };
})();
