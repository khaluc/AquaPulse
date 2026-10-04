// Sample-data mode. Off by default: pages show real reports only. "?demo=1" turns it on for
// this browser tab (it follows the visitor from page to page), "?demo=0" or the banner's
// button turns it off. While on, a yellow banner says so on every page.
(() => {
  const KEY = "aquapulse.demo";
  const param = new URLSearchParams(location.search).get("demo");
  try {
    if (param === "1") sessionStorage.setItem(KEY, "1");
    if (param === "0") sessionStorage.removeItem(KEY);
  } catch {}
  let on = param === "1";
  try { on = sessionStorage.getItem(KEY) === "1"; } catch {}
  window.AquaDemo = { on };
  if (!on) return;
  const show = () => {
    const bar = document.createElement("div");
    bar.className = "demo-banner";
    bar.setAttribute("role", "status");
    const text = document.createElement("span");
    text.textContent = window.t ? t("demo.banner")
      : "Đang xem dữ liệu mẫu. Ảnh, người báo và các hoạt động demo được mô phỏng.";
    const off = document.createElement("a");
    off.href = "?demo=0";
    off.textContent = window.t ? t("demo.off") : "Tắt dữ liệu mẫu";
    bar.append(text, off);
    const siteBar = document.querySelector(".site-bar");
    siteBar ? siteBar.after(bar) : document.body.prepend(bar);
  };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", show) : show();
})();
