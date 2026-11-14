/* ZARVON Main SPA Router, Auth/Demo Switcher, Smart Search Autocomplete, Theme & PWA */
import { apiFetch, closeModal, esc, fmtUzs, openModal, showToast } from "./api.js";
import { AppState, t } from "./i18n.js";
import {
  renderCalculatorView,
  renderCatalogView,
  renderCompareView,
  renderHomeView,
  renderProductDetailView,
} from "./views/marketplace.js";
import { renderCartView, renderCheckoutView, renderCustomerCabinetView } from "./views/checkout_customer.js";
import { renderSellerOnboardingView, renderSellerPortalView } from "./views/seller.js";
import { renderAdminPortalView } from "./views/admin.js";
import { enhanceHomeWithUzumSections } from "./views/psp_scoring_ui.js";

function applyTheme(theme) {
  AppState.theme = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", AppState.theme);
  localStorage.setItem("zarvon_theme", AppState.theme);
  const icon = document.getElementById("theme-icon");
  if (icon) icon.textContent = AppState.theme === "dark" ? "☀" : "🌙";
}

function applyLanguage(lang) {
  AppState.lang = ["uz", "ru", "en"].includes(lang) ? lang : "uz";
  localStorage.setItem("zarvon_lang", AppState.lang);
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
}

async function refreshCartBadge() {
  const badge = document.getElementById("cart-count");
  if (!badge) return;
  if (!AppState.authenticated) {
    badge.textContent = "0";
    return;
  }
  try {
    const cart = await apiFetch("/api/v1/commerce/cart/");
    const count = cart.items.reduce((acc, it) => acc + it.quantity, 0);
    AppState.cartCount = count;
    badge.textContent = String(count);
  } catch {
    badge.textContent = "0";
  }
}

async function refreshAuth() {
  try {
    const me = await apiFetch("/api/v1/auth/me/");
    AppState.authenticated = me.authenticated;
    AppState.user = me.user;
    AppState.mfaVerified = Boolean(me.mfa_verified);
    AppState.demoAccounts = me.demo_accounts || [];

    const roleBtn = document.getElementById("current-role-badge");
    if (roleBtn) {
      roleBtn.textContent = me.authenticated
        ? `👤 ${me.user.full_name.split(" ")[0]} (${me.user.role_label})`
        : "👤 Kirish / Rol";
    }
    if (me.authenticated) {
      const w = await apiFetch("/api/v1/catalog/wishlists/").catch(() => ({ results: [] }));
      AppState.wishlistIds = new Set(w.results.map((x) => x.product.id));
    } else {
      AppState.wishlistIds = new Set();
    }
    await refreshCartBadge();
  } catch {
    AppState.authenticated = false;
  }
}

function openAuthAndRoleModal() {
  const demoHtml = AppState.demoAccounts
    .map(
      (u) => `
      <button class="btn btn-outline btn-sm" style="justify-content:space-between;width:100%;margin-bottom:6px;" data-demo-phone="${esc(u.phone)}">
        <span><strong>${esc(u.full_name)}</strong> (${esc(u.phone)})</span>
        <span class="badge badge-navy">${esc(u.role_label)}</span>
      </button>`
    )
    .join("");

  openModal(
    AppState.authenticated ? `Hisob: ${AppState.user.full_name}` : "ZARVON Tizimiga Kirish (Password / OTP / Demo)",
    `
      ${
        AppState.authenticated
          ? `<div class="flex-between mb-3 card" style="background:var(--bg-subtle);">
               <div>
                 <strong>${esc(AppState.user.full_name)}</strong> (${esc(AppState.user.role_label)})<br>
                 <span class="text-xs text-muted">${esc(AppState.user.phone)}</span>
               </div>
               <button id="modal-logout-btn" class="btn btn-danger btn-sm">Chiqish</button>
             </div>`
          : ""
      }

      <div class="card mb-3" style="background:var(--navy-50);">
        <h4 style="margin-bottom:8px;">Telefon va OTP / Parol bilan kirish</h4>
        <form id="modal-login-form">
          <div class="grid-2">
            <div class="form-group">
              <label class="form-label" for="lg-phone">Telefon</label>
              <input id="lg-phone" class="form-control" value="+998901110001">
            </div>
            <div class="form-group">
              <label class="form-label" for="lg-pass">Parol (yoki OTP)</label>
              <input id="lg-pass" type="password" class="form-control" value="Zarvon2026!">
            </div>
          </div>
          <div class="flex-gap">
            <button type="submit" class="btn btn-primary btn-sm">Parol bilan kirish</button>
            <button type="button" id="lg-otp-req" class="btn btn-outline btn-sm">OTP kod so‘rash</button>
          </div>
          <div id="lg-otp-box" class="mt-2 hidden">
            <div class="flex-gap">
              <input id="lg-otp-code" class="form-control" style="max-width:160px;" placeholder="6 xonali OTP">
              <button type="button" id="lg-otp-login" class="btn btn-gold btn-sm">OTP bilan kirish</button>
            </div>
            <div id="lg-otp-hint" class="text-xs text-secondary mt-1"></div>
          </div>
        </form>
      </div>

      <div>
        <h4>Tezkor Sandbox Rol Almashuvi (Barcha rollarni sinash uchun)</h4>
        <div style="max-height:260px;overflow-y:auto;">${demoHtml}</div>
      </div>
    `,
    () => {
      let currentChallengeId = null;
      document.getElementById("modal-logout-btn")?.addEventListener("click", async () => {
        await apiFetch("/api/v1/auth/logout/", { method: "POST" });
        await refreshAuth();
        closeModal();
        showToast("Tizimdan chiqildi.");
        route();
      });

      document.getElementById("modal-login-form").onsubmit = async (e) => {
        e.preventDefault();
        try {
          await apiFetch("/api/v1/auth/login/", {
            method: "POST",
            body: JSON.stringify({
              phone: document.getElementById("lg-phone").value,
              password: document.getElementById("lg-pass").value,
            }),
          });
          await refreshAuth();
          closeModal();
          showToast("Muvaffaqiyatli kirdingiz!", "success");
          route();
        } catch (err) {
          showToast(err.message, "error");
        }
      };

      document.getElementById("lg-otp-req").onclick = async () => {
        try {
          const res = await apiFetch("/api/v1/auth/otp/request/", {
            method: "POST",
            body: JSON.stringify({ target: document.getElementById("lg-phone").value, purpose: "LOGIN" }),
          });
          currentChallengeId = res.challenge_id;
          document.getElementById("lg-otp-box").classList.remove("hidden");
          document.getElementById("lg-otp-hint").textContent = `Sandbox OTP kod: ${res.demo_otp_preview}`;
        } catch (err) {
          showToast(err.message, "error");
        }
      };

      document.getElementById("lg-otp-login").onclick = async () => {
        try {
          await apiFetch("/api/v1/auth/login/", {
            method: "POST",
            body: JSON.stringify({
              phone: document.getElementById("lg-phone").value,
              challenge_id: currentChallengeId,
              otp_code: document.getElementById("lg-otp-code").value,
            }),
          });
          await refreshAuth();
          closeModal();
          showToast("OTP tasdiqlandi!", "success");
          route();
        } catch (err) {
          showToast(err.message, "error");
        }
      };

      document.querySelectorAll("[data-demo-phone]").forEach((btn) => {
        btn.onclick = async () => {
          try {
            await apiFetch("/api/v1/auth/demo-switch/", {
              method: "POST",
              body: JSON.stringify({ phone: btn.dataset.demoPhone }),
            });
            await refreshAuth();
            closeModal();
            showToast(`Rol almashdi: ${AppState.user.role_label}`, "success");
            route();
          } catch (err) {
            showToast(err.message, "error");
          }
        };
      });
    }
  );
}

async function route() {
  const main = document.getElementById("main-content");
  const rawHash = (location.hash || "#home").slice(1);
  const [pathPart, queryPart] = rawHash.split("?");
  const parts = pathPart.split("/").filter(Boolean);
  const base = parts[0] || "home";

  // Highlight active nav links
  document.querySelectorAll("[data-nav]").forEach((el) => {
    el.classList.toggle("active", el.dataset.nav === base || (base === "customer" && parts[1] === "nasiya" && el.dataset.nav === "nasiya"));
  });

  try {
    if (base === "home") {
      await renderHomeView(main, refreshCartBadge);
    } else if (base === "catalog") {
      await renderCatalogView(main, queryPart, refreshCartBadge);
    } else if (base === "product" && parts[1]) {
      await renderProductDetailView(main, parts[1], refreshCartBadge);
    } else if (base === "calculator") {
      await renderCalculatorView(main);
    } else if (base === "compare") {
      await renderCompareView(main);
    } else if (base === "cart") {
      await renderCartView(main, refreshCartBadge);
    } else if (base === "checkout") {
      await renderCheckoutView(main, refreshCartBadge);
    } else if (base === "customer") {
      await renderCustomerCabinetView(main, parts[1] || "nasiya");
    } else if (base === "seller-onboarding") {
      await renderSellerOnboardingView(main);
    } else if (base === "seller") {
      await renderSellerPortalView(main, refreshAuth);
    } else if (base === "admin") {
      await renderAdminPortalView(main, refreshAuth);
    } else {
      await renderHomeView(main, refreshCartBadge);
      await enhanceHomeWithUzumSections(main);
    }
  } catch (err) {
    main.innerHTML = `
      <div class="state-box">
        <span class="badge badge-danger">⚠ Yuklashda xatolik</span>
        <h2 class="mt-2">${esc(err.message)}</h2>
        <button id="retry-route-btn" class="btn btn-primary mt-2">Qayta urinish</button>
      </div>
    `;
    document.getElementById("retry-route-btn").onclick = route;
  }
  window.scrollTo({ top: 0, behavior: "auto" });
}

function setupSmartSearch() {
  const form = document.getElementById("global-search-form");
  const input = document.getElementById("global-search-input");
  const box = document.getElementById("search-suggestions");
  let timer = null;

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const val = input.value.trim();
    if (val.length < 2) {
      box.classList.add("hidden");
      return;
    }
    timer = setTimeout(async () => {
      try {
        const res = await apiFetch(`/api/v1/catalog/products/?q=${encodeURIComponent(val)}`);
        if (!res.results.length) {
          box.innerHTML = `<div class="suggestion-item text-muted">Natija topilmadi</div>`;
        } else {
          box.innerHTML = res.results
            .slice(0, 6)
            .map(
              (p) => `
              <div class="suggestion-item" data-sug-slug="${esc(p.slug)}">
                <span>${esc(p.title)}</span>
                <strong class="tabular text-sm">${fmtUzs(p.cash_price)}</strong>
              </div>`
            )
            .join("");
          box.querySelectorAll("[data-sug-slug]").forEach((el) => {
            el.onclick = () => {
              box.classList.add("hidden");
              location.hash = `#product/${el.dataset.sugSlug}`;
            };
          });
        }
        box.classList.remove("hidden");
      } catch {
        box.classList.add("hidden");
      }
    }, 200);
  });

  document.addEventListener("click", (e) => {
    if (!form.contains(e.target)) box.classList.add("hidden");
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    box.classList.add("hidden");
    const q = input.value.trim();
    location.hash = q ? `#catalog?q=${encodeURIComponent(q)}` : "#catalog";
  });
}

async function init() {
  applyTheme(AppState.theme);
  applyLanguage(AppState.lang);

  // Compare badge init
  const cmpBadge = document.getElementById("compare-count");
  if (cmpBadge && AppState.compareIds.length) {
    cmpBadge.textContent = String(AppState.compareIds.length);
    cmpBadge.classList.remove("hidden");
  }

  document.getElementById("btn-theme-toggle")?.addEventListener("click", async () => {
    const next = AppState.theme === "dark" ? "light" : "dark";
    applyTheme(next);
    if (AppState.authenticated) {
      apiFetch("/api/v1/accounts/profile/", { method: "PATCH", body: JSON.stringify({ theme_preference: next }) }).catch(() => {});
    }
  });

  const langSel = document.getElementById("lang-switcher");
  if (langSel) {
    langSel.value = AppState.lang;
    langSel.addEventListener("change", () => applyLanguage(langSel.value));
  }

  document.getElementById("btn-nav-catalog")?.addEventListener("click", () => {
    location.hash = "#catalog";
  });
  document.getElementById("btn-role-switcher")?.addEventListener("click", openAuthAndRoleModal);

  // Offline / Online Banner
  const offBanner = document.getElementById("offline-banner");
  const syncNet = () => offBanner?.classList.toggle("hidden", navigator.onLine);
  window.addEventListener("online", syncNet);
  window.addEventListener("offline", syncNet);
  syncNet();

  // Register safe PWA Service Worker (Section 14)
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  setupSmartSearch();
  await refreshAuth();

  // Check invite query param
  const urlInvite = new URLSearchParams(location.search).get("invite");
  if (urlInvite && !location.hash) {
    location.hash = "#seller-onboarding";
  }

  window.addEventListener("hashchange", route);
  await route();
}

init();
