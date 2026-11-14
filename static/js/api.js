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
    ? `<div class="nasiya-pill-monthly tabular">
         <span>oyiga <strong>${fmtUzs(p.indicative_installment.monthly_payment).replace(" so‘m", "")}</strong> so‘mdan</span>
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
         ${p.stock_available > 0 ? `🛒 ${t("add_to_cart")}` : t("out_of_stock")}
       </button>`;

  return `
    <article class="product-card" data-product-id="${esc(p.id)}">
      <div class="product-media" data-open-product="${esc(p.slug)}">
        <img src="${esc(p.primary_image || "/static/icons/product-default.svg")}" alt="${esc(p.title)}" loading="lazy">
        <div class="product-badges">
          ${p.installment_eligible ? `<span class="badge badge-nasiya-soft">✦ Nasiya mavjud</span>` : `<span class="badge badge-warning">Faqat naqd</span>`}
          ${p.discount_pct > 0 ? `<span class="badge badge-gold">-${p.discount_pct}%</span>` : ""}
        </div>
        <div class="product-top-actions">
          <button class="chip-btn ${isWished ? "active" : ""}" data-wishlist-id="${esc(p.id)}" title="Sevimlilar" aria-label="Sevimlilarga qo‘shish">${isWished ? "♥" : "♡"}</button>
          <button class="chip-btn ${isCompared ? "active" : ""}" data-compare-id="${esc(p.id)}" title="Taqqoslash" aria-label="Taqqoslashga qo‘shish">⚖</button>
        </div>
        <span class="delivery-chip">🚚 ${esc(deliveryChip)}</span>
      </div>
      <div class="product-body">
        <div class="product-title" data-open-product="${esc(p.slug)}">${esc(p.title)}</div>
        <div class="price-row tabular">
          <span class="cash-price">${fmtUzs(p.cash_price)}</span>
          ${p.old_price ? `<span class="old-price">${fmtUzs(p.old_price)}</span>` : ""}
        </div>
        ${nasiyaHtml}
        <div class="text-xs text-muted flex-between">
          <span>★ ${esc(p.rating)} (${esc(p.review_count)})</span>
          <span>${esc(p.store_name)}</span>
        </div>
        <div class="card-action-split">
          <div class="card-cta-slot" data-slot-pid="${esc(p.id)}" data-stock="${p.stock_available}">${ctaHtml}</div>
          <button type="button" class="btn-more-dots" data-open-product="${esc(p.slug)}" title="Batafsil va kalkulyator" aria-label="Batafsil">•••</button>
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
