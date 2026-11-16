/* ZARVON Main SPA Router, Auth/Demo Switcher, Smart Search Autocomplete, Theme & PWA */
import {
  apiFetch,
  closeModal,
  esc,
  fmtUzs,
  openDeliveryPointPickerModal,
  openModal,
  openProductQuickViewModal,
  showToast,
} from "./api.js";
import { AppState, t } from "./i18n.js";
import {
  renderCalculatorView,
  renderCatalogView,
  renderCompareView,
  renderHomeView,
  renderNasiyaInfoView,
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
    AppState.cartQtyMap = {};
    badge.textContent = "0";
    return;
  }
  try {
    const cart = await apiFetch("/api/v1/commerce/cart/");
    const qtyMap = {};
    let count = 0;
    (cart.items || []).forEach((it) => {
      qtyMap[String(it.product_id)] = Number(it.quantity || 0);
      count += Number(it.quantity || 0);
    });
    const prevCount = AppState.cartCount || 0;
    AppState.cartQtyMap = qtyMap;
    AppState.cartCount = count;
    badge.textContent = String(count);
    if (count !== prevCount) {
      badge.classList.remove("badge-pop");
      void badge.offsetWidth;
      badge.classList.add("badge-pop");
    }
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
    AppState.sandboxMode = Boolean(me.sandbox_mode);
    AppState.demoAccounts = me.demo_accounts || [];

    document.getElementById("sandbox-top-chip")?.classList.toggle("hidden", !AppState.sandboxMode);
    document.getElementById("footer-sandbox-note")?.classList.toggle("hidden", !AppState.sandboxMode);

    const roleBtn = document.getElementById("current-role-badge");
    if (roleBtn) {
      roleBtn.textContent = me.authenticated
        ? `👤 ${me.user.full_name.split(" ")[0]} (${me.user.role_label})`
        : AppState.sandboxMode
        ? "👤 Kirish / Rol"
        : "👤 Kirish";
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
  const showDemoSwitcher = AppState.sandboxMode && (AppState.demoAccounts || []).length > 0;
  const demoHtml = showDemoSwitcher
    ? AppState.demoAccounts
        .map(
          (u) => `
      <button class="btn btn-outline btn-sm" style="justify-content:space-between;width:100%;margin-bottom:6px;" data-demo-phone="${esc(u.phone)}">
        <span><strong>${esc(u.full_name)}</strong> (${esc(u.phone)})</span>
        <span class="badge badge-navy">${esc(u.role_label)}</span>
      </button>`
        )
        .join("")
    : "";

  openModal(
    AppState.authenticated
      ? `Hisob: ${AppState.user.full_name}`
      : AppState.sandboxMode
      ? "ZARVON Tizimiga Kirish (Password / OTP / Demo)"
      : "ZARVON — Shaxsiy kabinetga kirish",
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
        <h4 style="margin-bottom:8px;">Telefon raqami va SMS OTP / Parol bilan kirish</h4>
        <form id="modal-login-form">
          <div class="grid-2">
            <div class="form-group">
              <label class="form-label" for="lg-phone">Telefon</label>
              <input id="lg-phone" class="form-control" value="${AppState.sandboxMode ? "+998901110001" : ""}" placeholder="+998 90 123 45 67">
            </div>
            <div class="form-group">
              <label class="form-label" for="lg-pass">Parol (yoki OTP)</label>
              <input id="lg-pass" type="password" class="form-control" value="${AppState.sandboxMode ? "Zarvon2026!" : ""}" placeholder="Parolni kiriting">
            </div>
          </div>
          <div id="lg-identity-box" class="text-xs mb-2" style="padding:7px 10px; border-radius:8px; background:var(--bg-surface); border:1px solid var(--border-color);">
            Raqamingizni kiriting — tizim egasini avtomatik aniqlaydi.
          </div>
          <div id="lg-fullname-wrap" class="form-group hidden">
            <label class="form-label" for="lg-fullname">Ism va familiyangiz (yangi mijoz uchun)</label>
            <input id="lg-fullname" class="form-control" placeholder="Masalan: Sardorbek Alimov">
          </div>
          <div class="flex-gap">
            <button type="submit" class="btn btn-primary btn-sm">Parol bilan kirish</button>
            <button type="button" id="lg-otp-req" class="btn btn-outline btn-sm">SMS OTP kod so‘rash</button>
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

      ${
        showDemoSwitcher
          ? `<div>
               <h4>Tezkor Sandbox Rol Almashuvi (Barcha rollarni sinash uchun)</h4>
               <div style="max-height:260px;overflow-y:auto;">${demoHtml}</div>
             </div>`
          : ""
      }
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

      let lookupTimer = null;
      const runPhoneLookup = async () => {
        const phoneInput = document.getElementById("lg-phone");
        const box = document.getElementById("lg-identity-box");
        const nameWrap = document.getElementById("lg-fullname-wrap");
        if (!phoneInput || !box) return;
        const val = phoneInput.value.trim();
        if (val.replace(/\D/g, "").length < 9) {
          box.textContent = "Kamida 9 ta raqam kiriting (masalan: 90 111 00 01).";
          box.style.borderColor = "var(--border-color)";
          nameWrap?.classList.add("hidden");
          return;
        }
        try {
          const info = await apiFetch("/api/v1/auth/phone-lookup/", {
            method: "POST",
            body: JSON.stringify({ phone: val }),
          });
          if (info.exists) {
            box.innerHTML = `<strong style="color:#15803d;">✓ ${esc(info.masked_name)}</strong> <span class="badge badge-navy">${esc(info.role_label)}</span> — raqam aniqlandi, parol yoki OTP bilan kiring.`;
            box.style.borderColor = "#16a34a";
            nameWrap?.classList.add("hidden");
          } else {
            box.innerHTML = `<strong style="color:#b45309;">✦ Yangi raqam (${esc(info.normalized_phone)})</strong> — OTP so‘rang va ismingizni kiriting.`;
            box.style.borderColor = "#d97706";
            nameWrap?.classList.remove("hidden");
          }
        } catch {
          box.textContent = "Raqam formatini tekshiring: +998 XX XXX XX XX.";
        }
      };

      document.getElementById("lg-phone")?.addEventListener("input", () => {
        clearTimeout(lookupTimer);
        lookupTimer = setTimeout(runPhoneLookup, 260);
      });
      runPhoneLookup();

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
          document.getElementById("lg-otp-hint").textContent = res.demo_otp_preview
            ? `Sandbox OTP kod: ${res.demo_otp_preview}`
            : res.message || "Tasdiqlash kodi telefoningizga yuborildi.";
        } catch (err) {
          showToast(err.message, "error");
        }
      };

      document.getElementById("lg-otp-login").onclick = async () => {
        try {
          const fullName = document.getElementById("lg-fullname")?.value.trim();
          const body = {
            phone: document.getElementById("lg-phone").value,
            challenge_id: currentChallengeId,
            otp_code: document.getElementById("lg-otp-code").value,
          };
          if (fullName) body.full_name = fullName;
          await apiFetch("/api/v1/auth/login/", {
            method: "POST",
            body: JSON.stringify(body),
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
    } else if (base === "nasiya-info") {
      await renderNasiyaInfoView(main);
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

  async function renderSearchPopover(val) {
    try {
      const endpoint = val.length >= 1
        ? `/api/v1/catalog/products/?q=${encodeURIComponent(val)}`
        : `/api/v1/catalog/products/?sort=popular`;
      const res = await apiFetch(endpoint);
      const items = (res.results || []).slice(0, 6);
      if (!items.length) {
        box.innerHTML = `<div class="suggestion-item text-muted">«${esc(val)}» bo‘yicha natija topilmadi</div>`;
        box.classList.remove("hidden");
        return;
      }
      box.innerHTML = `
        <div class="flex items-center justify-between text-xs text-muted mb-1">
          <strong>${val ? `«${esc(val)}» bo‘yicha topilgan mahsulotlar` : "🔥 Ommabop qidiruvlar"}</strong>
          ${val ? `<a href="#catalog?q=${encodeURIComponent(val)}" id="search-view-all" style="color:var(--navy-700); font-weight:700;">Barchasini ko‘rish ›</a>` : ""}
        </div>
        <div class="search-rich-grid">
          ${items.map((p) => {
            const mPay = p.indicative_installment ? p.indicative_installment.monthly_payment : Math.ceil(Number(p.cash_price || 0) / 12);
            return `
              <div class="search-mini-card" data-sug-slug="${esc(p.slug)}">
                <img src="${esc(p.primary_image || "/static/icons/product-default.svg")}" alt="${esc(p.title)}">
                <div style="font-size:0.78rem; font-weight:700; line-height:1.25; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;">${esc(p.title)}</div>
                <div class="tabular" style="font-size:0.84rem; font-weight:900; color:var(--navy-900);">${fmtUzs(p.cash_price)}</div>
                <span class="badge badge-gold tabular" style="font-size:0.68rem; width:fit-content;">oyiga ${fmtUzs(mPay).replace(" so‘m", "")} so‘m</span>
              </div>
            `;
          }).join("")}
        </div>
      `;
      box.querySelector("#search-view-all")?.addEventListener("click", () => {
        box.classList.add("hidden");
      });
      box.querySelectorAll("[data-sug-slug]").forEach((el) => {
        el.onclick = () => {
          box.classList.add("hidden");
          openProductQuickViewModal(el.dataset.sugSlug, refreshCartBadge);
        };
      });
      box.classList.remove("hidden");
    } catch {
      box.classList.add("hidden");
    }
  }

  input.addEventListener("focus", () => {
    clearTimeout(timer);
    timer = setTimeout(() => renderSearchPopover(input.value.trim()), 80);
  });

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const val = input.value.trim();
    timer = setTimeout(() => renderSearchPopover(val), 180);
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

  const noticeBar = document.getElementById("top-notice-bar");
  if (noticeBar) {
    if (localStorage.getItem("zarvon_notice_dismissed") === "1") {
      noticeBar.classList.add("hidden");
    }
    document.getElementById("btn-dismiss-notice")?.addEventListener("click", () => {
      noticeBar.classList.add("hidden");
      localStorage.setItem("zarvon_notice_dismissed", "1");
    });
  }

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

  let megaCatsCache = null;
  const catBtn = document.getElementById("btn-nav-catalog");
  const megaDrawer = document.getElementById("mega-catalog-drawer");
  catBtn?.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!megaDrawer) {
      location.hash = "#catalog";
      return;
    }
    const willOpen = megaDrawer.classList.contains("hidden");
    megaDrawer.classList.toggle("hidden", !willOpen);
    catBtn.setAttribute("aria-expanded", String(willOpen));
    if (!willOpen) return;
    if (!megaCatsCache) {
      try {
        const res = await apiFetch("/api/v1/catalog/categories/");
        megaCatsCache = res.results || res || [];
      } catch {
        megaCatsCache = [];
      }
    }
    megaDrawer.innerHTML = `
      <div class="container">
        <div class="flex items-center justify-between mb-2">
          <strong>⊞ Barcha turkumlar</strong>
          <div class="flex gap-2">
            <a href="#catalog" class="btn btn-primary btn-xs" data-close-mega="1">Barcha mahsulotlar ›</a>
            <a href="#nasiya-info" class="btn btn-gold btn-xs" data-close-mega="1">💳 Muddatli to‘lov qoidalari</a>
          </div>
        </div>
        <div class="mega-cat-grid">
          ${megaCatsCache.map((c) => `
            <a href="#catalog?category=${esc(c.slug)}" class="mega-cat-card" data-close-mega="1">
              <span style="font-size:1.35rem;">📦</span>
              <div>
                <div style="font-weight:800; font-size:0.88rem;">${esc(c.name)}</div>
                <div class="text-xs text-muted">${c.is_real_estate ? "Naqd savdo" : "Nasiya va naqd"}</div>
              </div>
            </a>
          `).join("")}
        </div>
      </div>
    `;
    megaDrawer.querySelectorAll("[data-close-mega]").forEach((el) => {
      el.addEventListener("click", () => {
        megaDrawer.classList.add("hidden");
        catBtn.setAttribute("aria-expanded", "false");
      });
    });
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


/* --- ZARVON Pickup Point Selector, Mega-Catalog & Ribbon Yana Interactions --- */
function setupUzumShellInteractions() {
  const labelEl = document.getElementById("header-dp-label");
  if (labelEl && (AppState.deliveryPoint?.region || AppState.deliveryCity)) {
    labelEl.textContent = AppState.deliveryPoint?.region || AppState.deliveryCity;
  }

  const openPvzModal = () => {
    openDeliveryPointPickerModal((picked) => {
      AppState.deliveryPoint = picked;
      localStorage.setItem("zarvon_dp", JSON.stringify(picked));
      if (labelEl) labelEl.textContent = picked.region;
    });
  };

  ["btn-delivery-point", "btn-open-pvz-list"].forEach((id) => {
    const el = document.getElementById(id);
    if (el && !el.dataset.wired) {
      el.dataset.wired = "1";
      el.addEventListener("click", openPvzModal);
    }
  });

  const yanaBtn = document.getElementById("btn-yana-cats");
  const yanaPanel = document.getElementById("yana-dropdown-panel");
  if (yanaBtn && yanaPanel && !yanaBtn.dataset.wired) {
    yanaBtn.dataset.wired = "1";
    yanaBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const willOpen = yanaPanel.classList.contains("hidden");
      if (willOpen) {
        const rect = yanaBtn.getBoundingClientRect();
        yanaPanel.style.top = `${Math.round(rect.bottom + 6)}px`;
        yanaPanel.style.right = `${Math.max(12, Math.round(window.innerWidth - rect.right))}px`;
      }
      yanaPanel.classList.toggle("hidden", !willOpen);
      yanaBtn.setAttribute("aria-expanded", String(willOpen));
    });
    yanaPanel.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", () => {
        yanaPanel.classList.add("hidden");
        yanaBtn.setAttribute("aria-expanded", "false");
      });
    });
  }

  if (!document.body.dataset.shellDocWired) {
    document.body.dataset.shellDocWired = "1";
    document.addEventListener("click", (e) => {
      const megaDrawer = document.getElementById("mega-catalog-drawer");
      const catBtn = document.getElementById("btn-nav-catalog");
      if (megaDrawer && !megaDrawer.classList.contains("hidden") && !megaDrawer.contains(e.target) && !catBtn?.contains(e.target)) {
        megaDrawer.classList.add("hidden");
        catBtn?.setAttribute("aria-expanded", "false");
      }
      if (yanaPanel && !yanaPanel.classList.contains("hidden") && !yanaPanel.contains(e.target) && !yanaBtn?.contains(e.target)) {
        yanaPanel.classList.add("hidden");
        yanaBtn?.setAttribute("aria-expanded", "false");
      }
    });
  }

  const applyViewMotion = () => {
    const viewRoot = document.getElementById("main-content");
    if (!viewRoot) return;
    viewRoot.classList.remove("view-enter");
    void viewRoot.offsetWidth;
    viewRoot.classList.add("view-enter");
  };
  window.addEventListener("hashchange", applyViewMotion);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", setupUzumShellInteractions);
} else {
  setupUzumShellInteractions();
}
