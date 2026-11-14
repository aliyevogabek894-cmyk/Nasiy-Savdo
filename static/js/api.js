/* Shared API client, safe escaping, formatting, modals, toasts & product cards */
import { AppState, t } from "./i18n.js";

export function esc(val) {
  if (val === null || val === undefined) return "";
  return String(val)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function fmtUzs(amount) {
  const num = Number(amount || 0);
  return `${Math.round(num).toLocaleString("ru-RU")} so‘m`;
}

export function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("uz-UZ", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return String(iso).slice(0, 10);
  }
}

export function getCsrfToken() {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export function genIdempotencyKey(prefix = "zrv") {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function showToast(message, type = "info") {
  const root = document.getElementById("toast-root");
  if (!root) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

export function openModal(title, bodyHtml, onMount = null) {
  const root = document.getElementById("modal-root");
  root.innerHTML = `
    <div class="modal-card" role="document">
      <div class="flex-between mb-3" style="border-bottom:1px solid var(--border-color);padding-bottom:10px;">
        <h3 style="margin:0;">${esc(title)}</h3>
        <button id="modal-close-x" class="icon-btn" aria-label="Yopish">✕</button>
      </div>
      <div id="modal-body">${bodyHtml}</div>
    </div>
  `;
  root.classList.remove("hidden");
  document.getElementById("modal-close-x").onclick = closeModal;
  root.onclick = (e) => {
    if (e.target === root) closeModal();
  };
  if (onMount) onMount(root);
}

export function closeModal() {
  const root = document.getElementById("modal-root");
  root.classList.add("hidden");
  root.innerHTML = "";
}

export async function apiFetch(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers["X-CSRFToken"] = getCsrfToken();
  }
  const resp = await fetch(url, {
    credentials: "same-origin",
    ...options,
    method,
    headers,
  });
  const contentType = resp.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await resp.json() : await resp.text();
  if (!resp.ok) {
    const msg =
      (data && data.error && data.error.message) ||
      (data && data.detail) ||
      `So‘rov xatosi (${resp.status})`;
    const err = new Error(msg);
    err.status = resp.status;
    err.payload = data;
    throw err;
  }
  return data;
}

export function statusBadge(status) {
  const s = String(status || "");
  if (["Approved", "Active", "DELIVERED", "Delivered", "PAID", "SUCCEEDED", "VERIFIED", "CLEAN", "ONLINE", "MATCHED", "COMPLETED", "RESOLVED", "CLOSED", "Closed", "Prepaid", "APPROVE", "CLEARED"].includes(s)) {
    return `<span class="badge badge-success">✓ ${esc(s)}</span>`;
  }
  if (["Pending Review", "Submitted", "Under Review", "Needs Info", "Pending", "Processing", "Shipped", "Awaiting Finance", "DEGRADED", "PRE_REMINDER", "SOFT", "MIDDLE", "IN_PROGRESS", "PENDING_CHECKER", "PARTIAL", "MANUAL_REVIEW"].includes(s)) {
    return `<span class="badge badge-warning">⏳ ${esc(s)}</span>`;
  }
  if (["Rejected", "Suspended", "Terminated", "Cancelled", "OVERDUE", "Overdue", "FAILED", "TIMEOUT", "HARD", "DISCREPANCY", "CONFIRMED", "DECLINE"].includes(s)) {
    return `<span class="badge badge-danger">⚠ ${esc(s)}</span>`;
  }
  return `<span class="badge badge-info">ℹ ${esc(s)}</span>`;
}

export function renderProductCard(p) {
  const isCompared = AppState.compareIds.includes(p.id);
  const isWished = AppState.wishlistIds.has(p.id);
  const inCartQty = (AppState.cartQtyMap && AppState.cartQtyMap[p.id]) || 0;
  const deliveryChip = p.delivery_badge || (p.delivery_sla_days <= 1 ? "Ertaga bepul" : `${p.delivery_sla_days} kunda bepul`);

  const nasiyaHtml = p.indicative_installment
    ? `<div class="nasiya-pill-monthly tabular" title="${p.indicative_installment.months} oyga indikativ to‘lov">
         <span>oyiga <strong>${fmtUzs(p.indicative_installment.monthly_payment).replace(" so‘m", "")}</strong> so‘m</span>
         <span class="nasiya-pill-term">${p.indicative_installment.months} oy</span>
       </div>`
    : `<div class="badge badge-warning" style="width:fit-content;">⊘ ${t("no_installment")}</div>`;

  const ctaHtml = inCartQty > 0
    ? `<div class="card-stepper" data-stepper-wrap="${esc(p.id)}">
         <button type="button" data-card-dec="${esc(p.id)}" aria-label="Kamaytirish">−</button>
         <span class="card-stepper-qty">${inCartQty}</span>
         <button type="button" data-card-inc="${esc(p.id)}" aria-label="Ko‘paytirish" ${inCartQty >= p.stock_available ? "disabled" : ""}>+</button>
       </div>`
    : `<button class="btn btn-primary btn-sm btn-cart-pill" data-add-cart="${esc(p.id)}" ${p.stock_available <= 0 ? "disabled" : ""}>
         ${p.stock_available > 0 ? "🛒 Savatga" : t("out_of_stock")}
       </button>`;

  return `
    <article class="product-card" data-product-id="${esc(p.id)}">
      <div class="product-media" data-open-product="${esc(p.slug)}">
        <img src="${esc(p.primary_image || "/static/icons/product-default.svg")}" alt="${esc(p.title)}" loading="lazy">
        <div class="product-badges">
          ${p.discount_pct > 0 ? `<span class="badge badge-danger" style="font-weight:800;">-${p.discount_pct}%</span>` : ""}
        </div>
        <div class="product-top-actions">
          <button class="chip-btn ${isWished ? "active" : ""}" data-wishlist-id="${esc(p.id)}" title="Sevimlilar" aria-label="Sevimlilarga qo‘shish">${isWished ? "♥" : "♡"}</button>
          <button class="chip-btn ${isCompared ? "active" : ""}" data-compare-id="${esc(p.id)}" title="Taqqoslash" aria-label="Taqqoslashga qo‘shish">⚖</button>
        </div>
      </div>
      <div class="product-body">
        <div class="product-title" data-open-product="${esc(p.slug)}">${esc(p.title)}</div>
        <div class="text-xs text-muted flex-between" style="gap:4px;">
          <span>★ ${esc(p.rating)} (${esc(p.review_count)})</span>
          <span style="color:#0d5c3e; font-weight:700;">🚚 ${esc(deliveryChip)}</span>
        </div>
        <div class="price-row tabular">
          <span class="cash-price">${fmtUzs(p.cash_price)}</span>
          ${p.old_price ? `<span class="old-price">${fmtUzs(p.old_price)}</span>` : ""}
        </div>
        ${nasiyaHtml}
        <div class="card-action-split">
          <div class="card-cta-slot" data-slot-pid="${esc(p.id)}" data-stock="${p.stock_available}">${ctaHtml}</div>
          <button type="button" class="btn-more-dots" data-quick-view="${esc(p.slug)}" title="Tez ko‘rish va variantlar" aria-label="Tez ko‘rish">👁</button>
        </div>
      </div>
    </article>
  `;
}

export function wireProductCardActions(container, reloadCartBadge) {
  container.querySelectorAll("[data-open-product]").forEach((el) => {
    el.addEventListener("click", () => {
      location.hash = `#product/${el.dataset.openProduct}`;
    });
  });
  container.querySelectorAll("[data-quick-view]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      openProductQuickViewModal(el.dataset.quickView, reloadCartBadge);
    });
  });

  const renderSlotStepper = (slot, productId, qty) => {
    const maxStock = Number(slot.dataset.stock || 99);
    if (qty > 0) {
      slot.innerHTML = `
        <div class="card-stepper" data-stepper-wrap="${esc(productId)}">
          <button type="button" data-card-dec="${esc(productId)}" aria-label="Kamaytirish">−</button>
          <span class="card-stepper-qty">${qty}</span>
          <button type="button" data-card-inc="${esc(productId)}" aria-label="Ko‘paytirish" ${qty >= maxStock ? "disabled" : ""}>+</button>
        </div>`;
    } else {
      slot.innerHTML = `
        <button class="btn btn-primary btn-sm btn-cart-pill" data-add-cart="${esc(productId)}" ${maxStock <= 0 ? "disabled" : ""}>
          ${maxStock > 0 ? `🛒 ${t("add_to_cart")}` : t("out_of_stock")}
        </button>`;
    }
    bindCartSlot(slot);
  };

  const applyCartDelta = async (productId, delta) => {
    if (!AppState.authenticated) {
      showToast("Savatga qo‘shish uchun avval tizimga kiring (yuqoridagi 'Kirish / Rol' tugmasi).", "error");
      document.getElementById("btn-role-switcher")?.click();
      return;
    }
    try {
      const cart = await apiFetch("/api/v1/commerce/cart/", {
        method: "POST",
        body: JSON.stringify({ product_id: productId, delta }),
      });
      const item = (cart.items || []).find((i) => String(i.product_id) === String(productId));
      const newQty = item ? Number(item.quantity) : 0;
      if (!AppState.cartQtyMap) AppState.cartQtyMap = {};
      if (newQty > 0) AppState.cartQtyMap[productId] = newQty;
      else delete AppState.cartQtyMap[productId];
      document.querySelectorAll(`.card-cta-slot[data-slot-pid="${productId}"]`).forEach((s) => renderSlotStepper(s, productId, newQty));
      if (delta > 0 && newQty === 1) showToast("Mahsulot savatga qo‘shildi!", "success");
      if (reloadCartBadge) reloadCartBadge();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  function bindCartSlot(scopeEl) {
    scopeEl.querySelectorAll("[data-add-cart]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        applyCartDelta(btn.dataset.addCart, 1);
      });
    });
    scopeEl.querySelectorAll("[data-card-inc]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        applyCartDelta(btn.dataset.cardInc, 1);
      });
    });
    scopeEl.querySelectorAll("[data-card-dec]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        applyCartDelta(btn.dataset.cardDec, -1);
      });
    });
  }

  bindCartSlot(container);

  container.querySelectorAll("[data-wishlist-id]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!AppState.authenticated) {
        showToast("Sevimlilar uchun tizimga kiring.", "error");
        return;
      }
      try {
        const res = await apiFetch("/api/v1/catalog/wishlists/", {
          method: "POST",
          body: JSON.stringify({ product_id: btn.dataset.wishlistId }),
        });
        if (res.wishlisted) {
          AppState.wishlistIds.add(btn.dataset.wishlistId);
          btn.classList.add("active");
          btn.innerHTML = "♥";
          showToast("Sevimlilarga saqlandi.", "success");
        } else {
          AppState.wishlistIds.delete(btn.dataset.wishlistId);
          btn.classList.remove("active");
          btn.innerHTML = "♡";
          showToast("Sevimlilardan olib tashlandi.");
        }
        btn.classList.remove("heart-pop");
        void btn.offsetWidth;
        btn.classList.add("heart-pop");
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  });

  container.querySelectorAll("[data-compare-id]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const pid = btn.dataset.compareId;
      const idx = AppState.compareIds.indexOf(pid);
      if (idx >= 0) {
        AppState.compareIds.splice(idx, 1);
        btn.classList.remove("active");
      } else {
        if (AppState.compareIds.length >= 4) {
          showToast("Taqqoslash uchun ko‘pi bilan 4 ta mahsulot tanlash mumkin (29.2).", "error");
          return;
        }
        AppState.compareIds.push(pid);
        btn.classList.add("active");
      }
      localStorage.setItem("zarvon_compare", JSON.stringify(AppState.compareIds));
      const badge = document.getElementById("compare-count");
      if (badge) {
        badge.textContent = AppState.compareIds.length;
        badge.classList.toggle("hidden", AppState.compareIds.length === 0);
      }
    });
  });
}

export async function openProductQuickViewModal(slug, reloadCartBadge) {
  openModal("Tez ko‘rish — mahsulot tafsiloti", `<p class="text-muted">Yuklanmoqda...</p>`);
  try {
    const p = await apiFetch(`/api/v1/catalog/products/${encodeURIComponent(slug)}/`);
    const images = (p.images && p.images.length) ? p.images : [p.primary_image || "/static/icons/product-default.svg"];
    const quotes = (p.installment_quotes || []).filter((q) => q.term_months <= 12);
    const defaultQuote = quotes[quotes.length - 1] || quotes[0];
    const monthly = defaultQuote ? defaultQuote.monthly_payment : Math.ceil(Number(p.cash_price || 0) / 12);
    const term = defaultQuote ? defaultQuote.term_months : 12;

    const specsEntries = Object.entries(p.specs || {});
    const variantLabels = specsEntries.length
      ? specsEntries.slice(0, 4).map(([k, v]) => `${k}: ${v}`)
      : ["Asosiy komplekt", "1 yil kafolat bilan"];

    const discountBadge = p.discount_pct
      ? `<span class="badge badge-danger" style="font-weight:800;">-${esc(String(p.discount_pct))}%</span>`
      : "";
    const oldPriceHtml = p.old_price && Number(p.old_price) > Number(p.cash_price)
      ? `<span class="text-muted tabular" style="text-decoration:line-through; font-size:0.9rem;">${fmtUzs(p.old_price)}</span>`
      : "";

    openModal(esc(p.title), `
      <div class="qv-grid">
        <div>
          <div class="qv-media-box">
            <img id="qv-main-img" src="${esc(images[0])}" alt="${esc(p.title)}">
          </div>
          ${images.length > 1 ? `
            <div class="flex gap-2 mt-2" style="flex-wrap:wrap;">
              ${images.slice(0, 5).map((src, idx) => `
                <button type="button" class="pd-thumb-btn ${idx === 0 ? "active" : ""}" data-qv-thumb="${esc(src)}" style="width:52px;height:52px;">
                  <img src="${esc(src)}" alt="Preview ${idx + 1}">
                </button>
              `).join("")}
            </div>
          ` : ""}
          <div class="mt-3">
            <a href="#product/${esc(p.slug)}" id="qv-full-link" class="btn btn-outline btn-sm btn-block" style="justify-content:space-between;">
              <span>Mahsulot haqidagi bor ma‘lumot</span>
              <span>›</span>
            </a>
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between gap-2 mb-2" style="flex-wrap:wrap;">
            <span class="badge badge-navy">${esc(p.store?.name || "Rasmiy do‘kon")} · ✓ Original</span>
            <span class="text-sm text-muted">★ ${Number(p.rating_avg || 4.9).toFixed(1)} (${p.rating_count || 0})</span>
          </div>

          <h3 style="margin:0 0 8px; font-size:1.15rem; line-height:1.3;">${esc(p.title)}</h3>

          <div class="mt-2">
            <div class="text-xs text-muted" style="font-weight:700;">Xususiyat / Variant:</div>
            <div class="qv-variant-pills" id="qv-variants">
              ${variantLabels.map((lbl, i) => `
                <button type="button" class="qv-var-btn ${i === 0 ? "active" : ""}" data-qv-var="${i}">${esc(lbl)}</button>
              `).join("")}
            </div>
          </div>

          <div class="flex items-center justify-between gap-2 mt-3" style="flex-wrap:wrap;">
            <div>
              <div class="flex items-center gap-2">
                ${oldPriceHtml}
                ${discountBadge}
              </div>
              <div id="qv-total-price" class="tabular" style="font-size:1.4rem; font-weight:900; color:var(--navy-900);">${fmtUzs(p.cash_price)}</div>
            </div>
            <div class="flex items-center gap-2">
              <button type="button" class="btn btn-ghost btn-sm" id="qv-qty-dec">−</button>
              <strong id="qv-qty-val" class="tabular" style="min-width:22px; text-align:center;">1</strong>
              <button type="button" class="btn btn-ghost btn-sm" id="qv-qty-inc">+</button>
            </div>
          </div>
          <div class="text-xs text-muted mt-1">
            ${p.stock_available > 0 ? `Omborda ${p.stock_available} dona mavjud` : "Vaqtincha tugagan"}
          </div>

          <button type="button" id="qv-nasiya-info-btn" class="mt-3" style="width:100%; display:flex; align-items:center; justify-content:space-between; padding:10px 12px; border-radius:10px; border:1px solid #f0b429; background:var(--gold-100); color:var(--navy-900); font-weight:700; cursor:pointer; font-size:0.86rem;">
            <span>🗓 Oyiga <strong class="tabular">${fmtUzs(monthly)}</strong>dan muddatli to‘lov (${term} oy)</span>
            <span>›</span>
          </button>

          <div class="flex gap-2 mt-3">
            <button type="button" id="qv-add-cart-btn" class="btn btn-primary" style="flex:1;" ${p.stock_available <= 0 ? "disabled" : ""}>Savatga qo‘shish</button>
            <button type="button" id="qv-buy-now-btn" class="btn btn-gold" ${p.stock_available <= 0 ? "disabled" : ""}>1 klikda xarid</button>
          </div>

          <div class="qv-info-panel text-xs">
            <div style="margin-bottom:6px;">
              <strong>🚚 Yetkazish:</strong> ${esc(p.delivery_badge || "Ertaga bepul")} — BTS Express va ZARVON topshirish punktlarigacha.
            </div>
            <div>
              <strong>🛡 Qaytarish va kafolat:</strong> 10 kun ichida qulay qaytarish, rasmiy kafolat va muddatidan oldin 0% yopish.
            </div>
          </div>
        </div>
      </div>
    `);

    let qty = 1;
    const maxQty = Math.max(1, Number(p.stock_available || 1));
    const syncPriceQty = () => {
      const qEl = document.getElementById("qv-qty-val");
      const pEl = document.getElementById("qv-total-price");
      if (qEl) qEl.textContent = String(qty);
      if (pEl) pEl.textContent = fmtUzs(Number(p.cash_price || 0) * qty);
    };

    document.querySelectorAll("[data-qv-thumb]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const main = document.getElementById("qv-main-img");
        if (main) main.src = btn.dataset.qvThumb;
        document.querySelectorAll("[data-qv-thumb]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
      });
    });

    document.querySelectorAll("[data-qv-var]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("[data-qv-var]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
      });
    });

    document.getElementById("qv-qty-dec")?.addEventListener("click", () => {
      if (qty > 1) { qty -= 1; syncPriceQty(); }
    });
    document.getElementById("qv-qty-inc")?.addEventListener("click", () => {
      if (qty < maxQty) { qty += 1; syncPriceQty(); }
    });

    document.getElementById("qv-full-link")?.addEventListener("click", () => {
      closeModal();
    });

    document.getElementById("qv-nasiya-info-btn")?.addEventListener("click", () => {
      closeModal();
      location.hash = "#nasiya-info";
    });

    const addItem = async (goCheckout = false) => {
      try {
        await apiFetch("/api/v1/commerce/cart/", {
          method: "POST",
          body: JSON.stringify({ product_id: p.id, quantity: qty }),
        });
        await reloadCartBadge?.();
        if (goCheckout) {
          closeModal();
          location.hash = "#checkout";
          return;
        }
        const addBtn = document.getElementById("qv-add-cart-btn");
        if (addBtn) {
          addBtn.textContent = "✓ Savatga qo‘shildi — O‘tish ›";
          addBtn.classList.remove("btn-primary");
          addBtn.classList.add("btn-outline");
          addBtn.onclick = () => {
            closeModal();
            location.hash = "#cart";
          };
        }
        showToast(`${p.title} savatga qo‘shildi.`, "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    };

    document.getElementById("qv-add-cart-btn")?.addEventListener("click", () => addItem(false));
    document.getElementById("qv-buy-now-btn")?.addEventListener("click", () => addItem(true));
  } catch (err) {
    openModal("Xatolik", `<p class="text-danger">${esc(err.message)}</p>`);
  }
}

export async function openDeliveryPointPickerModal(onPicked) {
  const regions = ["Barchasi", "BTS", "Toshkent", "Farg‘ona", "Furqat", "Andijon", "Samarqand", "Buxoro", "Xorazm", "Nukus", "Navoiy", "Qashqadaryo"];
  openModal("Topshirish punktlari va BTS Express", `
    <div>
      <p class="text-xs text-muted mb-2">
        O‘zbekiston bo‘ylab ZARVON PVZ va BTS Express punktlarini qidiring yoki o‘z hududingizdagi yangi punkt manzilini qo‘shing.
      </p>
      <div class="flex gap-2 mb-2">
        <input id="pvz-search-input" class="form-control" placeholder="Shahar, tuman yoki BTS nomi (masalan: Furqat, Chilonzor, BTS)..." value="">
        <button type="button" class="btn btn-gold btn-sm" id="pvz-add-toggle" style="white-space:nowrap;">+ Yangi punkt</button>
      </div>
      <div class="flex gap-1 mb-3" style="flex-wrap:wrap;" id="pvz-region-chips">
        ${regions.map((r, i) => `
          <button type="button" class="btn btn-xs ${i === 0 ? "btn-primary" : "btn-ghost"}" data-pvz-chip="${r === "Barchasi" ? "" : esc(r)}">${esc(r)}</button>
        `).join("")}
      </div>

      <form id="pvz-add-form" class="card mb-3 hidden" style="background:var(--bg-subtle); padding:12px;">
        <h4 style="margin:0 0 8px; font-size:0.92rem;">Yangi BTS / Topshirish punktini qo‘shish</h4>
        <div class="grid-2" style="gap:8px;">
          <input id="new-pvz-name" class="form-control" placeholder="Punkt nomi (masalan: BTS Express — Furqat Navbahor)" required>
          <input id="new-pvz-region" class="form-control" placeholder="Hudud / Tuman (masalan: Furqat tumani)" required>
        </div>
        <input id="new-pvz-address" class="form-control mt-2" placeholder="Aniq ko‘cha va mo‘ljal manzili" required>
        <div class="flex justify-between items-center mt-2 gap-2">
          <input id="new-pvz-hours" class="form-control" placeholder="Ish vaqti" value="09:00–20:00" style="max-width:170px;">
          <button type="submit" class="btn btn-primary btn-sm">Punktni saqlash</button>
        </div>
        <div class="text-xs text-muted mt-1" id="pvz-add-hint"></div>
      </form>

      <div id="pvz-results-list" style="max-height:310px; overflow-y:auto; display:flex; flex-direction:column; gap:8px;">
        <p class="text-muted text-sm">Yuklanmoqda...</p>
      </div>
    </div>
  `);

  const listEl = document.getElementById("pvz-results-list");
  const searchEl = document.getElementById("pvz-search-input");
  const addForm = document.getElementById("pvz-add-form");
  const addHint = document.getElementById("pvz-add-hint");

  async function loadPoints(queryStr = "") {
    if (!listEl) return;
    try {
      const url = queryStr
        ? `/api/v1/commerce/delivery-points/?q=${encodeURIComponent(queryStr)}`
        : "/api/v1/commerce/delivery-points/";
      const data = await apiFetch(url);
      const pts = data.results || [];
      if (!pts.length) {
        listEl.innerHTML = `<div class="card text-sm text-muted">Topilmadi. Yuqoridagi «+ Yangi punkt» tugmasi orqali o‘z BTS manzilingizni qo‘shishingiz mumkin.</div>`;
        return;
      }
      listEl.innerHTML = pts.map((pt) => {
        const isBts = /bts/i.test(pt.name || "");
        return `
          <button type="button" class="btn btn-outline" data-pick-pvz="${esc(String(pt.id))}" data-pvz-region="${esc(pt.region)}" data-pvz-name="${esc(pt.name)}" style="justify-content:space-between; text-align:left; padding:10px 12px; width:100%;">
            <div>
              <div style="font-weight:800;">${isBts ? "🚚 " : "📍 "}${esc(pt.name)}</div>
              <div class="text-xs text-muted">${esc(pt.region)} — ${esc(pt.address)} (${esc(pt.working_hours || "09:00–20:00")})</div>
            </div>
            <span class="badge ${isBts ? "badge-gold" : "badge-navy"}">${isBts ? "BTS" : "PVZ"}</span>
          </button>
        `;
      }).join("");

      listEl.querySelectorAll("[data-pick-pvz]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const picked = pts.find((x) => String(x.id) === String(btn.dataset.pickPvz));
          if (!picked) return;
          AppState.deliveryPoint = { id: picked.id, name: picked.name, region: picked.region, address: picked.address };
          AppState.deliveryCity = picked.region;
          localStorage.setItem("zarvon_dp", JSON.stringify(AppState.deliveryPoint));
          localStorage.setItem("zarvon_delivery_city", picked.region);
          localStorage.setItem("zarvon_delivery_point_id", String(picked.id));
          localStorage.setItem("zarvon_delivery_point_label", `${picked.name} (${picked.region})`);
          const headerCity = document.getElementById("header-dp-label");
          if (headerCity) headerCity.textContent = picked.region;
          closeModal();
          showToast(`Tanlandi: ${picked.name}`, "success");
          onPicked?.(picked);
        });
      });
    } catch (err) {
      listEl.innerHTML = `<p class="text-danger text-sm">${esc(err.message)}</p>`;
    }
  }

  let debounceId = null;
  searchEl?.addEventListener("input", () => {
    clearTimeout(debounceId);
    debounceId = setTimeout(() => loadPoints(searchEl.value.trim()), 200);
  });

  document.querySelectorAll("[data-pvz-chip]").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll("[data-pvz-chip]").forEach((c) => {
        c.classList.remove("btn-primary");
        c.classList.add("btn-ghost");
      });
      chip.classList.remove("btn-ghost");
      chip.classList.add("btn-primary");
      if (searchEl) searchEl.value = chip.dataset.pvzChip;
      loadPoints(chip.dataset.pvzChip);
    });
  });

  document.getElementById("pvz-add-toggle")?.addEventListener("click", () => {
    if (!addForm) return;
    addForm.classList.toggle("hidden");
    if (addHint && !AppState.authenticated) {
      addHint.textContent = "Eslatma: yangi punkt qo‘shish uchun hisobingizga kirgan bo‘lishingiz kerak.";
    }
  });

  addForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!AppState.authenticated) {
      showToast("Yangi punkt saqlash uchun avval tizimga kiring.", "error");
      return;
    }
    try {
      const payload = {
        name: document.getElementById("new-pvz-name").value.trim(),
        region: document.getElementById("new-pvz-region").value.trim(),
        address: document.getElementById("new-pvz-address").value.trim(),
        working_hours: document.getElementById("new-pvz-hours").value.trim() || "09:00–20:00",
      };
      const res = await apiFetch("/api/v1/commerce/delivery-points/", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const pt = res.point;
      if (pt) {
        AppState.deliveryPoint = { id: pt.id, name: pt.name, region: pt.region, address: pt.address };
        AppState.deliveryCity = pt.region;
        localStorage.setItem("zarvon_dp", JSON.stringify(AppState.deliveryPoint));
        localStorage.setItem("zarvon_delivery_city", pt.region);
        localStorage.setItem("zarvon_delivery_point_id", String(pt.id));
        localStorage.setItem("zarvon_delivery_point_label", `${pt.name} (${pt.region})`);
        const headerCity = document.getElementById("header-dp-label");
        if (headerCity) headerCity.textContent = pt.region;
        closeModal();
        showToast(`${pt.name} saqlandi va tanlandi!`, "success");
        onPicked?.(pt);
      }
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  await loadPoints("");
}
