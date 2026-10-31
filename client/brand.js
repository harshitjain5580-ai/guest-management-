window.APP_CONFIG = Object.freeze({ brandName: "Guest Manager" });

document.querySelectorAll("[data-brand]").forEach((element) => {
  element.textContent = window.APP_CONFIG.brandName;
});
document.querySelectorAll("[data-brand-mark]").forEach((element) => {
  element.textContent = window.APP_CONFIG.brandName.slice(0, 1).toUpperCase();
});
document.querySelectorAll("[data-page-title]").forEach((element) => {
  document.title = `${element.dataset.pageTitle} · ${window.APP_CONFIG.brandName}`;
});
