/* Cart, 3-Step Checkout (Nasiya / Multi-Bank / PSP), and Full Customer Cabinet */
import { apiFetch, closeModal, esc, fmtDate, fmtUzs, genIdempotencyKey, openDeliveryPointPickerModal, openModal, showToast, statusBadge } from "../api.js";
import { AppState } from "../i18n.js";
import {
  openElectronicReceiptModal,
  openPspPayModal,
  renderDueAlertsHtml,
  renderKatmMibDstiReportHtml,
  renderSavedCardsHtml,
  wireSavedCardsActions,
} from "./psp_scoring_ui.js";

function requireLoginPrompt(container) {
  container.innerHTML = `
    <div class="state-box">
      <h2>Shaxsiy kabinet va kassa uchun tizimga kiring</h2>
      <p class="text-muted">${
        AppState.sandboxMode
          ? `Demo rejimida yuqoridagi “Kirish / Rol” tugmasi orqali <strong>Customer (Azizbek Karimov)</strong> yoki boshqa rolni bir bosishda tanlashingiz mumkin.`
          : "Buyurtma berish, nasiya limitini ko‘rish va to‘lov cheklarini ochish uchun telefon raqamingiz bilan tizimga kiring."
      }</p>
      <button id="prompt-login-btn" class="btn btn-primary mt-2">${
        AppState.sandboxMode ? "👤 Kirish / Demo rol tanlash" : "👤 Tizimga kirish"
      }</button>
    </div>
  `;
  document.getElementById("prompt-login-btn")?.addEventListener("click", () => {
    document.getElementById("btn-role-switcher")?.click();
  });
}

export async function renderCartView(container, reloadCartBadge) {
  if (!AppState.authenticated) return requireLoginPrompt(container);
  const cart = await apiFetch("/api/v1/commerce/cart/");

  if (!cart.items.length) {
    container.innerHTML = `
      <div class="state-box">
        <h2>Savatingiz bo‘sh</h2>
        <p class="text-muted">Katalogdan mahsulotlarni tanlang va naqd yoki 12 oygacha shaffof muddatli to‘lovga xarid qiling.</p>
        <a href="#catalog" class="btn btn-primary mt-2">Katalogga o‘tish</a>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <h1 class="mb-4">Savat (${cart.items.length} xil mahsulot)</h1>
    <div class="grid-2" style="grid-template-columns:2fr 1fr;align-items:start;">
      <div class="card">
        ${cart.items
          .map(
            (it) => `
          <div class="flex-between" style="padding:12px 0;border-bottom:1px solid var(--border-color);">
            <div class="flex-gap">
              <img src="${esc(it.primary_image || "/static/icons/product-default.svg")}" alt="" width="64" height="64" style="border-radius:8px;background:var(--bg-subtle);padding:6px;">
              <div>
                <a href="#product/${esc(it.slug)}" class="fw-bold">${esc(it.title)}</a>
                <div class="text-xs text-muted">Do‘kon: ${esc(it.store_name)} • ${it.installment_eligible ? "Nasiya mumkin" : "Faqat naqd"}</div>
                <div class="text-sm fw-bold tabular mt-1">${fmtUzs(it.cash_price)} × ${it.quantity} = ${fmtUzs(it.line_total)}</div>
              </div>
            </div>
            <div class="flex-gap">
              <button class="btn btn-outline btn-sm" data-qty-minus="${esc(it.product_id)}" data-qty="${it.quantity}">−</button>
              <span class="fw-bold tabular">${it.quantity}</span>
              <button class="btn btn-outline btn-sm" data-qty-plus="${esc(it.product_id)}" data-qty="${it.quantity}">+</button>
              <button class="btn btn-danger btn-sm" data-del-item="${esc(it.product_id)}">✕</button>
            </div>
          </div>`
          )
          .join("")}
      </div>

      <div class="card card-elevated">
        <h3>Buyurtma xulosasi</h3>
        <div class="text-sm text-secondary mb-2">
          Sotuvchilar bo‘yicha ajratish (7.2): <strong>${cart.seller_groups.length} ta sub-buyurtma</strong>
        </div>
        ${cart.seller_groups
          .map((g) => `<div class="flex-between text-xs text-muted mb-1"><span>${esc(g.store_name)} (${g.items_count} dona)</span><span class="tabular">${fmtUzs(g.subtotal)}</span></div>`)
          .join("")}
        <hr style="border:none;border-top:1px solid var(--border-color);margin:12px 0;">
        <div class="flex-between tabular mb-3">
          <span class="fw-bold">Jami summa:</span>
          <span style="font-size:1.35rem;font-weight:800;">${fmtUzs(cart.subtotal)}</span>
        </div>
        ${
          cart.cash_only_required
            ? `<div class="badge badge-danger mb-3" style="white-space:normal;padding:10px 12px;line-height:1.4;">
                 💵 <strong>Faqat naqd savdo:</strong> ${esc((cart.credit_policy && cart.credit_policy.block_reason) || cart.prohibited_reasons.join(" "))}
               </div>`
            : !cart.installment_eligible
            ? `<div class="badge badge-warning mb-3" style="white-space:normal;">⚠ ${esc(cart.prohibited_reasons.join(" "))}</div>`
            : `<div class="badge badge-success mb-3">✓ Barcha tovarlar nasiyaga mos (≤ 250 BHM • kredit cheklovi yo‘q)</div>`
        }
        <a href="#checkout" class="btn btn-gold" style="width:100%;">3 qadamli kassaga o‘tish →</a>
      </div>
    </div>
  `;

  container.querySelectorAll("[data-qty-plus]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await apiFetch("/api/v1/commerce/cart/", {
          method: "POST",
          body: JSON.stringify({ product_id: btn.dataset.qtyPlus, quantity: Number(btn.dataset.qty) + 1, set_exact: true }),
        });
        await reloadCartBadge();
        renderCartView(container, reloadCartBadge);
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  });
  container.querySelectorAll("[data-qty-minus]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const next = Number(btn.dataset.qty) - 1;
      if (next <= 0) {
        await apiFetch(`/api/v1/commerce/cart/?product_id=${btn.dataset.qtyMinus}`, { method: "DELETE" });
      } else {
        await apiFetch("/api/v1/commerce/cart/", {
          method: "POST",
          body: JSON.stringify({ product_id: btn.dataset.qtyMinus, quantity: next, set_exact: true }),
        });
      }
      await reloadCartBadge();
      renderCartView(container, reloadCartBadge);
    });
  });
  container.querySelectorAll("[data-del-item]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiFetch(`/api/v1/commerce/cart/?product_id=${btn.dataset.delItem}`, { method: "DELETE" });
      await reloadCartBadge();
      renderCartView(container, reloadCartBadge);
    });
  });
}

export async function renderCheckoutView(container, reloadCartBadge) {
  if (!AppState.authenticated) return requireLoginPrompt(container);

  const [cart, dps, consentsData, cabinet] = await Promise.all([
    apiFetch("/api/v1/commerce/cart/"),
    apiFetch("/api/v1/commerce/delivery-points/"),
    apiFetch("/api/v1/finance/consents/"),
    apiFetch("/api/v1/finance/cabinet/"),
  ]);

  if (!cart.items.length) {
    location.hash = "#cart";
    return;
  }

  let step = 1;
  let deliveryType = AppState.deliveryPoint?.id ? "PICKUP" : "COURIER";
  let deliveryAddress = "Toshkent sh., Chilonzor tumani, 5-mavze";
  let deliveryPointId = AppState.deliveryPoint?.id || dps.results[0]?.id || "";
  let recipientPhone = AppState.user?.phone || "";
  const creditBlocked = Boolean(cart.cash_only_required || cabinet.credit_policy?.cash_only_required);
  const installmentLocked = !cart.installment_eligible || creditBlocked;
  let paymentChannel = installmentLocked ? "DIRECT_PAY" : "ZARVON_NASIYA";
  let pspProvider = "Payme";
  let months = 12;
  let downPayment = 0;
  let promoCode = "";
  let promoDiscount = 0;
  let latestCalc = null;

  const consentMap = {};
  consentsData.consents.forEach((c) => (consentMap[c.purpose] = c.is_granted));

  const renderStep = async () => {
    const netTotal = Math.max(1000, cart.subtotal - promoDiscount);
    if (paymentChannel === "ZARVON_NASIYA" && cart.installment_eligible) {
      try {
        latestCalc = await apiFetch("/api/v1/finance/calculator/", {
          method: "POST",
          body: JSON.stringify({
            price: netTotal,
            down_payment: downPayment,
            months,
            category_installment_allowed: true,
          }),
        });
      } catch {
        latestCalc = null;
      }
    }

    container.innerHTML = `
      <h1 class="mb-2">3 qadamli Kassa (Checkout)</h1>
      <div class="step-pills">
        <span class="step-pill ${step === 1 ? "active" : step > 1 ? "done" : ""}">1. Manzil va yetkazish</span>
        <span class="step-pill ${step === 2 ? "active" : step > 2 ? "done" : ""}">2. To‘lov / Nasiya / Bank</span>
        <span class="step-pill ${step === 3 ? "active" : ""}">3. Tasdiqlash va Shartnoma</span>
      </div>

      <div class="grid-2" style="grid-template-columns:2fr 1fr;align-items:start;">
        <div class="card card-elevated">
          ${
            step === 1
              ? `
            <h2>1-qadam: Olish usuli va Buyurtma oluvchi</h2>
            <div class="flex-gap mb-3">
              <button type="button" id="chk-del-pickup" class="btn ${deliveryType === "PICKUP" ? "btn-primary" : "btn-outline"}">📍 Topshirish punkti / BTS (bepul)</button>
              <button type="button" id="chk-del-courier" class="btn ${deliveryType === "COURIER" ? "btn-primary" : "btn-outline"}">🚚 Kuryer bilan manzilga</button>
            </div>
            ${
              deliveryType === "COURIER"
                ? `<div class="form-group">
                     <label class="form-label" for="chk-addr">Yetkazib berish manzili</label>
                     <input id="chk-addr" class="form-control" value="${esc(deliveryAddress)}">
                     <span class="form-hint">Topshirishda kuryerga shaxsiy OTP-kod aytiladi (firibgarlikka qarshi himoya).</span>
                   </div>`
                : `<div class="form-group">
                     <div class="flex justify-between items-center mb-1" style="flex-wrap:wrap; gap:6px;">
                       <label class="form-label" for="chk-dp" style="margin:0;">Topshirish punkti yoki BTS Express filiali</label>
                       <button type="button" id="chk-pick-bts-btn" class="btn btn-gold btn-xs">🗺 Barcha BTS punktlaridan qidirish / Yangi joy qo‘shish</button>
                     </div>
                     <select id="chk-dp" class="form-control">
                       ${dps.results.map((d) => `<option value="${esc(d.id)}" ${String(d.id) === String(deliveryPointId) ? "selected" : ""}>${esc(d.name)} — ${esc(d.region)}, ${esc(d.address)} (${esc(d.working_hours)})</option>`).join("")}
                     </select>
                   </div>`
            }

            <div class="card mb-3" style="background:var(--bg-subtle); padding:14px;">
              <div class="flex justify-between items-center mb-2" style="flex-wrap:wrap; gap:6px;">
                <strong>👤 Buyurtmani oluvchi (Telefon orqali aniqlash)</strong>
                <button type="button" id="chk-switch-user-btn" class="btn btn-ghost btn-xs">Hisobni almashtirish / OTP</button>
              </div>
              <div class="grid-2" style="gap:10px; align-items:center;">
                <div>
                  <label class="form-label text-xs" for="chk-rec-phone">Oluvchi telefon raqami</label>
                  <input id="chk-rec-phone" class="form-control" value="${esc(recipientPhone)}" placeholder="+998 90 123 45 67">
                </div>
                <div id="chk-rec-lookup-badge" class="text-xs" style="padding:8px 10px; border-radius:8px; background:var(--bg-surface); border:1px solid var(--border-color);">
                  <strong>${esc(AppState.user?.full_name || "Mijoz")}</strong> (${esc(AppState.user?.phone || "")})
                </div>
              </div>
            </div>

            <div class="mb-3">
              <div class="text-xs text-muted mb-1"><strong>📦 Ertaga / eng yaqin sanaga yetkaziladigan tovarlar (${cart.items.length} ta):</strong></div>
              <div class="order-thumb-row">
                ${cart.items.map((it) => `
                  <div class="order-thumb-item" title="${esc(it.title)} × ${it.quantity}">
                    <img src="${esc(it.primary_image || "/static/icons/product-default.svg")}" alt="${esc(it.title)}">
                    <span class="order-thumb-qty">×${it.quantity}</span>
                  </div>
                `).join("")}
              </div>
            </div>

            <button id="chk-next-1" class="btn btn-gold mt-2">Keyingi qadam: To‘lov usuli →</button>
          `
              : step === 2
              ? `
            <h2>2-qadam: To‘lov yoki Muddatli to‘lovni tanlang</h2>
            ${
              creditBlocked
                ? `<div class="card mb-3" style="background:var(--danger-bg);border:1px solid var(--danger-fg, #dc2626);">
                     <div class="flex-between" style="flex-wrap:wrap;gap:6px;">
                       <strong>${esc(cabinet.credit_policy?.credit_condition_label || "⛔ Kredit cheklovi — Faqat naqd savdo")}</strong>
                       <span class="badge badge-danger">${esc(cabinet.credit_policy?.trading_mode_label || "Faqat naqd savdo")}</span>
                     </div>
                     <p class="text-sm mt-2 mb-1">${esc(cart.credit_policy?.block_reason || cabinet.credit_policy?.block_reason || (cart.prohibited_reasons || []).join(" "))}</p>
                     <div class="text-xs text-muted">Faol krediti yoki kechikkan to‘lovi bor mijozlarga faqat naqd / Click / Payme / Uzum / Karta to‘lovi ruxsat etiladi.</div>
                   </div>`
                : !cart.installment_eligible
                ? `<div class="badge badge-warning mb-3" style="white-space:normal;">⚠ ${esc((cart.prohibited_reasons || []).join(" "))}</div>`
                : ""
            }
            <div class="flex-gap mb-4">
              <button type="button" class="btn ${paymentChannel === "ZARVON_NASIYA" ? "btn-primary" : "btn-outline"}" data-ch="ZARVON_NASIYA" ${installmentLocked ? "disabled" : ""}>
                💳 ZARVON Nasiya (≤12 oy)
              </button>
              <button type="button" class="btn ${paymentChannel === "BANK_GATEWAY" ? "btn-primary" : "btn-outline"}" data-ch="BANK_GATEWAY" ${installmentLocked ? "disabled" : ""}>
                🏦 Bank krediti${AppState.sandboxMode ? " (Sandbox)" : ""}
              </button>
              <button type="button" class="btn ${paymentChannel === "DIRECT_PAY" ? "btn-primary" : "btn-outline"}" data-ch="DIRECT_PAY">
                💵 Click / Payme / Uzum / Karta
              </button>
            </div>

            <div class="flex-gap mb-4">
              <input id="chk-promo" class="form-control" style="max-width:240px;" placeholder="Promo-kod (masalan: ZARVON11)" value="${esc(promoCode)}">
              <button type="button" id="chk-apply-promo" class="btn btn-outline">Promo qo‘llash</button>
            </div>

            ${
              paymentChannel === "ZARVON_NASIYA"
                ? `
              <div class="card" style="background:var(--navy-50);">
                <div class="flex-between mb-2">
                  <strong>Sizning bo‘sh nasiya limitingiz${AppState.sandboxMode ? " (DEMO)" : ""}:</strong>
                  <span class="badge badge-navy tabular">${fmtUzs(cabinet.limit.available_limit_uzs)} (${esc(cabinet.limit.tier)})</span>
                </div>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label" for="chk-months">Muddat</label>
                    <select id="chk-months" class="form-control">
                      ${[3, 6, 9, 12].map((m) => `<option value="${m}" ${m === months ? "selected" : ""}>${m} oy</option>`).join("")}
                    </select>
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="chk-down">Boshlang‘ich to‘lov (so‘m)</label>
                    <input id="chk-down" type="number" class="form-control tabular" value="${downPayment}" min="0" step="100000">
                  </div>
                </div>

                ${
                  latestCalc
                    ? `<div class="nasiya-callout mt-2 tabular">
                         <div class="nasiya-monthly">Oyiga: ${fmtUzs(latestCalc.monthly_payment)} × ${months} oy</div>
                         <div>Asosiy summa: ${fmtUzs(latestCalc.principal)} • Ustama: ${fmtUzs(latestCalc.markup_amount)} • Komissiya: ${fmtUzs(latestCalc.commission_amount)}</div>
                         <div class="fw-bold mt-1">Jami to‘lanadigan summa: ${fmtUzs(latestCalc.total_payable)} (Yillik yuklama: ${latestCalc.annualized_extra_pct}% ≤ 50%)</div>
                       </div>`
                    : `<div class="badge badge-danger">⚠ Tanlangan parametrlar compliance tekshiruvidan o‘tmadi.</div>`
                }

                <div class="mt-3">
                  <div class="fw-bold text-sm mb-2">Alohida maqsadli roziliklar (8.1 / 28.4):</div>
                  <label class="flex-gap text-sm mb-1"><input type="checkbox" id="c-id" ${consentMap.IDENTITY ? "checked" : ""}> Shaxsni tasdiqlash (MyID / OneID)</label>
                  <label class="flex-gap text-sm mb-1"><input type="checkbox" id="c-cb" ${consentMap.CREDIT_BUREAU ? "checked" : ""}> Kredit byurosiga so‘rov yuborish</label>
                </div>
              </div>
            `
                : paymentChannel === "BANK_GATEWAY"
                ? `
              <div class="card" style="background:var(--navy-50);">
                <span class="badge badge-gold mb-2">Multi-Bank Kredit Ariza Tizimi${AppState.sandboxMode ? " (Sandbox)" : ""}</span>
                <p class="text-sm">Arizangiz bir vaqtda hamkor banklarga correlation ID bilan yuboriladi. Bir bank ishlamasa ham boshqa banklar taklif qaytaradi.</p>
                <div class="form-group">
                  <label class="form-label" for="chk-months">So‘raladigan muddat</label>
                  <select id="chk-months" class="form-control">
                    ${[6, 9, 12].map((m) => `<option value="${m}" ${m === months ? "selected" : ""}>${m} oy</option>`).join("")}
                  </select>
                </div>
                <label class="flex-gap text-sm mb-1"><input type="checkbox" id="c-cb" ${consentMap.CREDIT_BUREAU ? "checked" : ""}> Kredit hisoboti so‘rovi roziligi</label>
                <label class="flex-gap text-sm"><input type="checkbox" id="c-bk" ${consentMap.BANK_TRANSFER ? "checked" : ""}> Hamkor banklarga ma’lumot uzatish roziligi</label>
              </div>
            `
                : `
              <div class="card" style="background:var(--navy-50);">
                <label class="form-label">To‘lov tizimini tanlang${AppState.sandboxMode ? " (Sandbox PSP)" : ""}</label>
                <div class="psp-select-grid mt-2">
                  ${["Payme", "Click", "Uzum Bank", "Paynet", "Uzcard/Humo"]
                    .map((p) => {
                      const desc =
                        p === "Payme"
                          ? "JSON-RPC 2.0"
                          : p === "Click"
                          ? "Prepare/Complete MD5"
                          : p === "Uzum Bank"
                          ? "Tezkor bank"
                          : p === "Paynet"
                          ? "Milliy tarmoq"
                          : "Token karta";
                      return `<button type="button" class="psp-option-card ${pspProvider === p ? "active" : ""}" data-psp="${p}"><strong>${p}</strong><span class="text-xs text-muted">${desc}</span></button>`;
                    })
                    .join("")}
                </div>
              </div>
            `
            }

            <div class="flex-between mt-4">
              <button id="chk-back-2" class="btn btn-outline">← Orqaga</button>
              <button id="chk-next-2" class="btn btn-gold">3-qadam: Shartnoma va Tasdiqlash →</button>
            </div>
          `
              : `
            <h2>3-qadam: Shartnoma Xulosasi va Tasdiqlash</h2>
            <div class="card mb-3" style="background:var(--gold-100);border-color:var(--gold-500);">
              <h4 style="margin-bottom:6px;">Oddiy va shaffof shartnoma xulosasi (30.4)</h4>
              <ul class="text-sm" style="margin:0;padding-left:18px;">
                <li>Tanlangan usul: <strong>${esc(paymentChannel === "ZARVON_NASIYA" ? `ZARVON Nasiya (${months} oy)` : paymentChannel === "BANK_GATEWAY" ? `Hamkor banklar (${months} oy)` : pspProvider)}</strong></li>
                <li>Tovar naqd qiymati: <strong class="tabular">${fmtUzs(netTotal)}</strong></li>
                ${
                  paymentChannel === "ZARVON_NASIYA" && latestCalc
                    ? `<li class="fw-bold">Jami to‘lanadigan summa: <span class="tabular">${fmtUzs(latestCalc.total_payable)}</span> (${fmtUzs(latestCalc.monthly_payment)}/oy)</li>`
                    : ""
                }
                <li><strong>Muddatidan oldin to‘lash huquqi:</strong> Istalgan vaqtda qisman yoki to‘liq 0% jarima bilan yopish mumkin.</li>
                <li><strong>Shikoyat huquqi:</strong> Har qanday tushunmovchilikda kabinetdagi “Murojaatlar” bo‘limiga murojaat qiling.</li>
              </ul>
            </div>

            ${
              paymentChannel === "ZARVON_NASIYA" && latestCalc
                ? `
              <div class="table-wrap mb-3" style="max-height:220px;overflow-y:auto;">
                <table class="data-table tabular">
                  <thead><tr><th>Oy</th><th>Sana</th><th>To‘lov</th></tr></thead>
                  <tbody>
                    ${latestCalc.preview_schedule.map((s) => `<tr><td>${s.installment_no}-oy</td><td>${fmtDate(s.due_date)}</td><td>${fmtUzs(s.amount)}</td></tr>`).join("")}
                  </tbody>
                </table>
              </div>
            `
                : ""
            }

            <div class="form-group">
              <label class="form-label" for="chk-sign-method">Tasdiqlash / Imzolash usuli</label>
              <select id="chk-sign-method" class="form-control">
                <option value="OTP">SMS OTP kod orqali tasdiqlash${AppState.sandboxMode ? " (Sandbox)" : ""}</option>
                <option value="E_IMZO">E-IMZO elektron kalit orqali${AppState.sandboxMode ? " (Sandbox)" : ""}</option>
              </select>
            </div>

            <div class="flex-between mt-4">
              <button id="chk-back-3" class="btn btn-outline">← Orqaga</button>
              <button id="chk-confirm-btn" class="btn btn-success">✓ Buyurtma va shartnomani tasdiqlash</button>
            </div>
          `
          }
        </div>

        <aside class="card">
          <h3>Savat tafsiloti</h3>
          ${cart.items
            .map((it) => `<div class="flex-between text-sm mb-2"><span>${esc(it.title)} × ${it.quantity}</span><strong class="tabular">${fmtUzs(it.line_total)}</strong></div>`)
            .join("")}
          <hr style="border:none;border-top:1px solid var(--border-color);margin:10px 0;">
          ${promoDiscount > 0 ? `<div class="flex-between text-sm text-secondary mb-1"><span>Promo chegirma (${esc(promoCode)}):</span><strong class="tabular">−${fmtUzs(promoDiscount)}</strong></div>` : ""}
          <div class="flex-between fw-bold tabular">
            <span>Tovarlar jami:</span>
            <span>${fmtUzs(netTotal)}</span>
          </div>
          <div class="text-xs text-muted mt-3">Sotuvchi sub-buyurtmalari soni: ${cart.seller_groups.length} ta</div>
        </aside>
      </div>
    `;

    // Event bindings for current step
    document.getElementById("chk-del-courier")?.addEventListener("click", () => {
      deliveryType = "COURIER";
      renderStep();
    });
    document.getElementById("chk-del-pickup")?.addEventListener("click", () => {
      deliveryType = "PICKUP";
      renderStep();
    });
    document.getElementById("chk-pick-bts-btn")?.addEventListener("click", () => {
      openDeliveryPointPickerModal((picked) => {
        if (!dps.results.some((x) => String(x.id) === String(picked.id))) {
          dps.results.unshift(picked);
        }
        deliveryPointId = picked.id;
        deliveryType = "PICKUP";
        renderStep();
      });
    });
    document.getElementById("chk-dp")?.addEventListener("change", (e) => {
      deliveryPointId = e.target.value;
    });
    document.getElementById("chk-switch-user-btn")?.addEventListener("click", () => {
      document.getElementById("btn-role-switcher")?.click();
    });

    let recTimer = null;
    const recInput = document.getElementById("chk-rec-phone");
    const recBadge = document.getElementById("chk-rec-lookup-badge");
    const runRecLookup = async () => {
      if (!recInput || !recBadge) return;
      recipientPhone = recInput.value.trim();
      if (recipientPhone.replace(/\D/g, "").length < 9) {
        recBadge.textContent = "Kamida 9 ta raqam kiriting (tizim oluvchini aniqlaydi).";
        return;
      }
      try {
        const info = await apiFetch("/api/v1/auth/phone-lookup/", {
          method: "POST",
          body: JSON.stringify({ phone: recipientPhone }),
        });
        if (info.exists) {
          recBadge.innerHTML = `<strong style="color:#15803d;">✓ Aniqlandi: ${esc(info.masked_name)}</strong> <span class="badge badge-navy">${esc(info.role_label)}</span>`;
        } else {
          recBadge.innerHTML = `<strong style="color:#b45309;">✦ Yangi oluvchi (${esc(info.normalized_phone)})</strong> — OTP xabari shu raqamga keladi.`;
        }
      } catch {
        /* ignore minor format transient */
      }
    };
    recInput?.addEventListener("input", () => {
      clearTimeout(recTimer);
      recTimer = setTimeout(runRecLookup, 250);
    });
    if (recInput && recipientPhone) runRecLookup();

    document.getElementById("chk-next-1")?.addEventListener("click", () => {
      if (deliveryType === "COURIER") deliveryAddress = document.getElementById("chk-addr").value;
      else deliveryPointId = document.getElementById("chk-dp").value;
      if (recInput) recipientPhone = recInput.value.trim();
      step = 2;
      renderStep();
    });

    container.querySelectorAll("[data-ch]").forEach((btn) => {
      btn.addEventListener("click", () => {
        paymentChannel = btn.dataset.ch;
        renderStep();
      });
    });
    container.querySelectorAll("[data-psp]").forEach((btn) => {
      btn.addEventListener("click", () => {
        pspProvider = btn.dataset.psp;
        container.querySelectorAll("[data-psp]").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
      });
    });
    document.getElementById("chk-months")?.addEventListener("change", (e) => {
      months = Number(e.target.value);
      renderStep();
    });
    document.getElementById("chk-down")?.addEventListener("change", (e) => {
      downPayment = Math.max(0, Number(e.target.value || 0));
      renderStep();
    });
    document.getElementById("chk-apply-promo")?.addEventListener("click", async () => {
      const code = document.getElementById("chk-promo").value.trim();
      if (!code) return;
      try {
        const res = await apiFetch("/api/v1/catalog/promo/validate/", {
          method: "POST",
          body: JSON.stringify({ code, subtotal: cart.subtotal }),
        });
        promoCode = res.code;
        promoDiscount = res.discount_amount;
        showToast(`Promo qo‘llandi: −${fmtUzs(promoDiscount)}`, "success");
        renderStep();
      } catch (err) {
        showToast(err.message, "error");
      }
    });
    document.getElementById("chk-back-2")?.addEventListener("click", () => {
      step = 1;
      renderStep();
    });
    document.getElementById("chk-next-2")?.addEventListener("click", async () => {
      // Save consent checkboxes if present
      const updates = {};
      const cid = document.getElementById("c-id");
      const ccb = document.getElementById("c-cb");
      const cbk = document.getElementById("c-bk");
      if (cid) updates.IDENTITY = cid.checked;
      if (ccb) updates.CREDIT_BUREAU = ccb.checked;
      if (cbk) updates.BANK_TRANSFER = cbk.checked;
      if (Object.keys(updates).length) {
        await apiFetch("/api/v1/finance/consents/", {
          method: "POST",
          body: JSON.stringify({ purposes: updates }),
        });
        Object.assign(consentMap, updates);
      }
      step = 3;
      renderStep();
    });
    document.getElementById("chk-back-3")?.addEventListener("click", () => {
      step = 2;
      renderStep();
    });
    document.getElementById("chk-confirm-btn")?.addEventListener("click", async () => {
      const btn = document.getElementById("chk-confirm-btn");
      btn.disabled = true;
      try {
        const res = await apiFetch("/api/v1/commerce/checkout/", {
          method: "POST",
          body: JSON.stringify({
            idempotency_key: genIdempotencyKey("chk"),
            delivery_type: deliveryType,
            delivery_address: deliveryAddress,
            delivery_point_id: deliveryPointId,
            payment_channel: paymentChannel,
            payment_method_label: paymentChannel === "DIRECT_PAY" ? (AppState.sandboxMode ? `${pspProvider} (Sandbox)` : pspProvider) : paymentChannel,
            psp_provider: pspProvider,
            plan_id: latestCalc?.plan_id,
            down_payment: downPayment,
            months,
            promo_code: promoCode,
            signed_method: document.getElementById("chk-sign-method")?.value || "OTP",
          }),
        });
        await reloadCartBadge();
        showToast("Buyurtma muvaffaqiyatli rasmiylashtirildi!", "success");
        const pickedDp = dps.results.find((d) => String(d.id) === String(deliveryPointId));
        container.innerHTML = `
          <div class="card card-elevated order-success-card">
            <div class="order-check-circle" aria-hidden="true">✓</div>
            <span class="badge badge-success">Buyurtma qabul qilindi</span>
            <h1 class="mt-2" style="margin-bottom:4px;">Buyurtma #${esc(res.order_number)}</h1>
            <p class="text-secondary text-sm mb-3">
              ${
                deliveryType === "PICKUP" && pickedDp
                  ? `📍 Topshirish punkti: <strong>${esc(pickedDp.name)}</strong> (${esc(pickedDp.region)}, ${esc(pickedDp.address)})`
                  : `🚚 Kuryer manzili: <strong>${esc(deliveryAddress)}</strong>`
              }
            </p>
            <div class="order-thumb-row mb-3" style="justify-content:center;">
              ${cart.items.map((it) => `
                <div class="order-thumb-item" title="${esc(it.title)}">
                  <img src="${esc(it.primary_image || "/static/icons/product-default.svg")}" alt="${esc(it.title)}">
                  <span class="order-thumb-qty">×${it.quantity}</span>
                </div>
              `).join("")}
            </div>
            <div class="table-wrap mt-3">
              <table class="data-table">
                <thead><tr><th>Sub-buyurtma</th><th>Do‘kon</th><th>Topshirish OTP-kodi</th></tr></thead>
                <tbody>
                  ${res.sub_orders
                    .map((s) => `<tr><td class="fw-bold">${esc(s.sub_order_number)}</td><td>${esc(s.store)}</td><td><span class="badge badge-gold tabular">${esc(s.delivery_otp_demo)}</span></td></tr>`)
                    .join("")}
                </tbody>
              </table>
            </div>
            ${
              res.finance && res.finance.contract_number
                ? `<div class="nasiya-callout mt-3">Nasiya shartnomasi: <strong>${esc(res.finance.contract_number)}</strong> • Oylik: <strong>${fmtUzs(res.finance.monthly_payment)}</strong></div>`
                : ""
            }
            ${
              res.finance && res.finance.application_number
                ? `<div class="nasiya-callout mt-3">Bank gateway arizasi: <strong>${esc(res.finance.application_number)}</strong> — javoblar kabinetingizda!</div>`
                : ""
            }
            ${
              paymentChannel === "DIRECT_PAY"
                ? AppState.sandboxMode
                  ? `<div class="card mt-3" style="text-align:left;background:var(--bg-subtle);">
                       <div class="flex-between">
                         <strong>⚡ ${esc(pspProvider)} Gateway Sandbox Protokoli (${fmtUzs(res.total_amount || netTotal)})</strong>
                         <button id="chk-run-psp-sim" class="btn btn-gold btn-sm">Click / Payme / Uzum Protokolini Sinash</button>
                       </div>
                       ${
                         res.finance?.psp_checkout?.checkout_url
                           ? `<div class="mt-2"><a href="${esc(res.finance.psp_checkout.checkout_url)}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">🔗 ${esc(pspProvider)} to‘lov havolasini ochish</a></div>`
                           : ""
                       }
                       <div id="chk-psp-trace" class="text-xs mt-2 text-muted">Buyurtma rasmiylashtirildi. Yuqoridagi tugma bilan to‘lov shlyuzining real Prepare/Complete, JSON-RPC 2.0 yoki Uzum /check→/create→/confirm izini tekshiring.</div>
                     </div>`
                  : `<div class="card mt-3" style="text-align:left;background:var(--bg-subtle);">
                       <div class="flex-between" style="flex-wrap:wrap;gap:8px;">
                         <strong>💳 To‘lovni yakunlash — ${esc(pspProvider)} (${fmtUzs(res.total_amount || netTotal)})</strong>
                         ${
                           res.finance?.psp_checkout?.checkout_url
                             ? `<a href="${esc(res.finance.psp_checkout.checkout_url)}" target="_blank" rel="noopener" class="btn btn-gold btn-sm">🔗 ${esc(pspProvider)} orqali to‘lash</a>`
                             : ""
                         }
                       </div>
                       <div class="text-xs mt-2 text-muted">Buyurtmangiz yaratildi. Tanlangan to‘lov tizimi orqali to‘lovni tasdiqlaganingizdan so‘ng holat avtomatik yangilanadi.</div>
                     </div>`
                : ""
            }
            <div class="flex-gap mt-4" style="justify-content:center;">
              <a href="#customer/orders" class="btn btn-primary">Buyurtmalarim</a>
              <a href="#catalog" class="btn btn-outline">Xaridlarni davom ettirish</a>
            </div>
          </div>
        `;
        document.getElementById("chk-run-psp-sim")?.addEventListener("click", async (e) => {
          const b = e.currentTarget;
          b.disabled = true;
          try {
            const sim = await apiFetch("/api/v1/finance/psp/checkout/", {
              method: "POST",
              body: JSON.stringify({ reference: res.order_number, psp_provider: pspProvider, amount_uzs: res.total_amount || netTotal }),
            });
            document.getElementById("chk-psp-trace").innerHTML = `
              <span class="badge badge-success">✓ ${esc(sim.psp_provider)} — ${esc(sim.mode)}</span>
              <pre class="mt-2" style="background:var(--bg-surface);padding:8px;border-radius:8px;overflow:auto;">${esc(JSON.stringify(sim.trace, null, 2))}</pre>
            `;
            showToast(sim.detail, "success");
          } catch (err) {
            showToast(err.message, "error");
          } finally {
            b.disabled = false;
          }
        });
      } catch (err) {
        showToast(err.message, "error");
        btn.disabled = false;
      }
    });
  };

  renderStep();
}

export async function renderCustomerCabinetView(container, initialTab = "nasiya") {
  if (!AppState.authenticated) return requireLoginPrompt(container);

  let activeTab = initialTab || "nasiya";
  const tabs = [
    ["nasiya", "💳 Nasiya va Limit"],
    ["orders", "📦 Buyurtmalarim"],
    ["banks", "🏦 Bank arizalari"],
    ["kyc", "🪪 Profil va KYC"],
    ["privacy", "🔒 Roziliklar va Maxfiylik"],
    ["wishlists", "♥ Sevimlilar"],
    ["notifications", "🔔 Bildirishnomalar"],
    ["support", "💬 Murojaatlar va Apellyatsiya"],
  ];

  const load = async () => {
    container.innerHTML = `
      <div class="flex-between mb-3">
        <div>
          <h1 style="margin:0;">Mijoz kabineti</h1>
          <div class="text-sm text-muted">${esc(AppState.user.full_name)} • ${esc(AppState.user.phone)} • KYC: ${statusBadge(AppState.user.kyc_status)}</div>
        </div>
      </div>
      <div class="portal-layout">
        <aside class="portal-sidebar" aria-label="Kabinet menyusi">
          ${tabs.map(([id, label]) => `<button class="portal-tab ${activeTab === id ? "active" : ""}" data-ctab="${id}">${label}</button>`).join("")}
        </aside>
        <section id="cust-panel" class="card">Yuklanmoqda...</section>
      </div>
    `;

    container.querySelectorAll("[data-ctab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeTab = btn.dataset.ctab;
        load();
      });
    });

    const panel = document.getElementById("cust-panel");
    if (activeTab === "nasiya") {
      const cab = await apiFetch("/api/v1/finance/cabinet/");
      const cp = cab.credit_policy;
      const cpBlocked = Boolean(cp && cp.cash_only_required);
      panel.innerHTML = `
        ${renderDueAlertsHtml(cab.due_alerts)}
        ${
          cp
            ? `<div class="card mb-4" style="background:${cpBlocked ? "var(--danger-bg)" : "var(--bg-subtle)"};border-left:4px solid ${cpBlocked ? "var(--danger-fg, #dc2626)" : "var(--success-fg, #15803d)"};">
                 <div class="flex-between" style="flex-wrap:wrap;gap:8px;">
                   <div>
                     <span class="text-xs text-muted fw-bold">KREDIT HOLATI VA SAVDO REJIMI</span>
                     <h3 style="margin:4px 0 2px;">${esc(cp.credit_condition_label)}</h3>
                   </div>
                   <span class="badge ${cpBlocked ? "badge-danger" : "badge-success"}">${esc(cp.trading_mode_label)}</span>
                 </div>
                 <p class="text-sm mt-2 mb-1">${esc(cp.credit_condition_detail)}</p>
                 ${cpBlocked && cp.block_reason ? `<div class="text-xs fw-bold" style="color:var(--danger-fg, #b91c1c);">⛔ ${esc(cp.block_reason)}</div>` : ""}
               </div>`
            : ""
        }
        <div class="grid-3 mb-4">
          <div class="kpi-card" style="border-left:4px solid var(--gold-500);">
            <div class="kpi-label">Bo‘sh nasiya limiti (${AppState.sandboxMode ? "DEMO • " : ""}${esc(cab.limit.tier)})</div>
            <div class="kpi-value tabular">${fmtUzs(cab.limit.available_limit_uzs)}</div>
            <div class="text-xs text-muted tabular">Jami: ${fmtUzs(cab.limit.total_limit_uzs)} • Band: ${fmtUzs(cab.limit.used_limit_uzs)}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Keyingi to‘lov</div>
            ${
              cab.next_payment
                ? `<div class="kpi-value tabular">${fmtUzs(cab.next_payment.amount)}</div>
                   <div class="text-xs text-muted">${fmtDate(cab.next_payment.due_date)} • #${esc(cab.next_payment.contract_number)}</div>`
                : `<div class="kpi-value">0 so‘m</div><div class="text-xs text-muted">Kutilayotgan to‘lov yo‘q</div>`
            }
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Faol shartnomalar</div>
            <div class="kpi-value tabular">${cab.contracts.length} ta</div>
            <div class="text-xs text-muted">0% jarimasiz erta to‘lash huquqi</div>
          </div>
        </div>

        <h3 class="mb-3">Nasiya shartnomalari va to‘lov jadvali</h3>
        ${
          cab.contracts.length
            ? cab.contracts
                .map((c) => {
                  const totalPay = Math.max(1, Number(c.total_payable || 0));
                  const paidAmt = Math.max(0, totalPay - Number(c.remaining_balance || 0));
                  const paidPct = c.remaining_balance <= 0 ? 100 : Math.min(99, Math.round((paidAmt / totalPay) * 100));
                  return `
                <div class="card mb-4" style="background:var(--bg-subtle);">
                  <div class="flex-between mb-2">
                    <div>
                      <strong>#${esc(c.contract_number)}</strong>
                      <span class="text-xs text-muted"> • Buyurtma ${esc(c.order_number)} • ${esc(c.provider_name)}</span>
                    </div>
                    ${statusBadge(c.status)}
                  </div>
                  <div class="mb-3">
                    <div class="flex-between text-xs mb-1">
                      <span class="text-muted">To‘lov jarayoni: <strong style="color:var(--text-primary);">${paidPct}% to‘landi</strong></span>
                      <span class="tabular text-muted">${fmtUzs(paidAmt)} / ${fmtUzs(c.total_payable)}</span>
                    </div>
                    <div class="loan-progress-track" role="progressbar" aria-valuenow="${paidPct}" aria-valuemin="0" aria-valuemax="100">
                      <div class="loan-progress-fill" style="width:${paidPct}%;"></div>
                    </div>
                  </div>
                  <div class="grid-4 tabular text-sm mb-3">
                    <div><span class="text-muted">Asosiy:</span><br><strong>${fmtUzs(c.principal_amount)}</strong></div>
                    <div><span class="text-muted">Ustama + Kom.:</span><br><strong>${fmtUzs(c.markup_amount + c.commission_amount)}</strong></div>
                    <div><span class="text-muted">Jami to‘lov:</span><br><strong>${fmtUzs(c.total_payable)}</strong></div>
                    <div><span class="text-muted">Qoldiq:</span><br><strong>${fmtUzs(c.remaining_balance)}</strong></div>
                  </div>
                  ${
                    c.remaining_balance > 0
                      ? `<div class="flex-gap mb-3">
                           <button class="btn btn-primary btn-sm" data-pay-contract="${esc(c.id)}" data-amount="${c.schedule.find((s) => s.status !== "PAID")?.amount_due || c.remaining_balance}" data-early="false">
                             Navbatdagi to‘lovni qilish
                           </button>
                           <button class="btn btn-gold btn-sm" data-pay-contract="${esc(c.id)}" data-amount="${c.remaining_balance}" data-early="true">
                             ⚡ Muddatidan oldin to‘lash (0% jarima)
                           </button>
                         </div>`
                      : ""
                  }
                  <div class="table-wrap">
                    <table class="data-table tabular">
                      <thead><tr><th>#</th><th>Sana</th><th>To‘lov</th><th>To‘langan</th><th>Holat</th></tr></thead>
                      <tbody>
                        ${c.schedule
                          .map((s) => {
                            const dueTag =
                              s.status === "PAID"
                                ? ""
                                : s.days_until_due < 0
                                ? ` <span class="badge badge-danger">${Math.abs(s.days_until_due)} kun kechikdi</span>`
                                : s.days_until_due === 0
                                ? ` <span class="badge badge-danger">BUGUN</span>`
                                : s.days_until_due <= 7
                                ? ` <span class="badge badge-warning">${s.days_until_due} kun qoldi</span>`
                                : "";
                            return `<tr><td>${s.installment_no}</td><td>${fmtDate(s.due_date)}${dueTag}</td><td>${fmtUzs(s.amount_due)}</td><td>${fmtUzs(s.amount_paid)}</td><td>${statusBadge(s.status)}</td></tr>`;
                          })
                          .join("")}
                      </tbody>
                    </table>
                  </div>
                </div>`;
                })
                .join("")
            : `<p class="text-muted">Sizda hali nasiya shartnomalari yo‘q.</p>`
        }
        ${renderKatmMibDstiReportHtml(cab.latest_scoring_report, cab.credit_policy)}

        <h3 class="mt-5 mb-2">🧾 To‘lovlar tarixi va Elektron cheklar (${(cab.payments || []).length})</h3>
        ${
          (cab.payments || []).length
            ? `<div class="table-wrap mb-4">
                <table class="data-table tabular text-sm">
                  <thead><tr><th>Sana</th><th>Maqsad / Hujjat</th><th>Provayder</th><th>Summa</th><th>Holat</th><th>Elektron chek</th></tr></thead>
                  <tbody>
                    ${(cab.payments || [])
                      .map((p) => {
                        const targetLabel = p.contract_number
                          ? `Nasiya #${esc(p.contract_number)}`
                          : p.order_number
                          ? `Buyurtma #${esc(p.order_number)}`
                          : esc(p.reconciliation_ref || p.payment_intent_id);
                        return `<tr>
                          <td>${fmtDate(p.created_at)}</td>
                          <td>${targetLabel}</td>
                          <td>${esc(p.provider)}</td>
                          <td class="fw-bold">${fmtUzs(p.amount)}</td>
                          <td>${statusBadge(p.status)}</td>
                          <td><button type="button" class="btn btn-outline btn-xs" data-open-receipt="${esc(p.id)}">🧾 Chek</button></td>
                        </tr>`;
                      })
                      .join("")}
                  </tbody>
                </table>
              </div>`
            : `<p class="text-sm text-muted mb-4">Hozircha tasdiqlangan to‘lov cheklari yo‘q.</p>`
        }
      `;

      panel.querySelectorAll("[data-open-receipt]").forEach((btn) => {
        btn.addEventListener("click", () => openElectronicReceiptModal(btn.dataset.openReceipt));
      });

      panel.querySelectorAll("[data-pay-contract]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const cid = btn.dataset.payContract;
          const defaultAmt = Number(btn.dataset.amount);
          const cObj = (cab.contracts || []).find((x) => x.id === cid);
          openPspPayModal({
            reference: cObj ? cObj.contract_number : cid,
            contractId: cid,
            suggestedAmount: defaultAmt,
            cards: cab.payment_cards || [],
            allowEarly: true,
            onSuccess: load,
          });
        });
      });
      panel.querySelectorAll("[data-psp-pay-contract]").forEach((btn) => {
        btn.addEventListener("click", () => {
          openPspPayModal({
            reference: btn.dataset.pspRef,
            contractId: btn.dataset.pspPayContract,
            suggestedAmount: Number(btn.dataset.pspAmt || 0),
            cards: cab.payment_cards || [],
            allowEarly: true,
            onSuccess: load,
          });
        });
      });
      const cardsWrap = document.createElement("div");
      cardsWrap.innerHTML = renderSavedCardsHtml(cab.payment_cards || []);
      panel.appendChild(cardsWrap);
      wireSavedCardsActions(cardsWrap, load);
    } else if (activeTab === "orders") {
      const ordData = await apiFetch("/api/v1/commerce/orders/");
      const orders = ordData.orders || [];
      panel.innerHTML = `
        <h2 class="mb-3">Buyurtmalarim (${orders.length})</h2>
        ${
          orders.length
            ? orders
                .map(
                  (o) => `
              <div class="card mb-3" style="background:var(--bg-subtle);">
                <div class="flex-between mb-2">
                  <div><strong>#${esc(o.order_number)}</strong> • <span class="text-xs text-muted">${fmtDate(o.created_at)} • ${esc(o.payment_method_label)}</span></div>
                  <div class="flex-gap"><strong class="tabular">${fmtUzs(o.total_amount)}</strong> ${statusBadge(o.status)}</div>
                </div>
                ${o.seller_orders
                  .map(
                    (so) => `
                  <div class="card mt-2">
                    <div class="flex-between">
                      <div>
                        <strong>${esc(so.store_name)}</strong> (${esc(so.sub_order_number)})
                        <div class="text-xs text-muted">Tracking: ${esc(so.tracking_number)}</div>
                      </div>
                      <div class="flex-gap">
                        ${so.delivery_otp_demo ? `<span class="badge badge-gold">Topshirish OTP: ${esc(so.delivery_otp_demo)}</span>` : ""}
                        ${statusBadge(so.status)}
                      </div>
                    </div>
                    <ul class="text-sm mt-2" style="margin-bottom:8px;">
                      ${so.items.map((it) => `<li>${esc(it.title)} × ${it.qty} — <span class="tabular">${fmtUzs(it.line_total)}</span></li>`).join("")}
                    </ul>
                    ${
                      ["Delivered", "Shipped", "Confirmed"].includes(so.status) && !so.returns.length
                        ? `<button class="btn btn-outline btn-sm" data-req-return="${esc(so.id)}">Qaytarish so‘rash</button>`
                        : so.returns.map((r) => `<span class="badge badge-warning">Qaytarish: ${esc(r.status)} (${esc(r.reason)})</span>`).join("")
                    }
                  </div>`
                  )
                  .join("")}
              </div>`
                )
                .join("")
            : `<p class="text-muted">Hali buyurtmalar mavjud emas.</p>`
        }
      `;
      panel.querySelectorAll("[data-req-return]").forEach((btn) => {
        btn.addEventListener("click", () => {
          openModal(
            "Mahsulotni qaytarish so‘rovi",
            `
              <div class="form-group">
                <label class="form-label" for="ret-scope">Qaytarish turi</label>
                <select id="ret-scope" class="form-control">
                  <option value="FULL">To‘liq qaytarish (shartnoma bekor qilinadi)</option>
                  <option value="PARTIAL">Qisman qaytarish (jadval qayta hisoblanadi)</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label" for="ret-reason">Sabab va foto dalil izohi</label>
                <textarea id="ret-reason" class="form-control" rows="3" placeholder="Nuqson yoki mos kelmaslik sababini yozing..."></textarea>
              </div>
              <button id="ret-send" class="btn btn-primary" style="width:100%;">So‘rov yuborish</button>
            `,
            () => {
              document.getElementById("ret-send").onclick = async () => {
                try {
                  await apiFetch(`/api/v1/commerce/seller-orders/${btn.dataset.reqReturn}/return/`, {
                    method: "POST",
                    body: JSON.stringify({
                      return_scope: document.getElementById("ret-scope").value,
                      reason: document.getElementById("ret-reason").value,
                    }),
                  });
                  closeModal();
                  showToast("Qaytarish so‘rovi yuborildi!", "success");
                  load();
                } catch (err) {
                  showToast(err.message, "error");
                }
              };
            }
          );
        });
      });
    } else if (activeTab === "banks") {
      const cab = await apiFetch("/api/v1/finance/cabinet/");
      panel.innerHTML = `
        <h2 class="mb-2">Multi-Bank Kredit Arizalari${AppState.sandboxMode ? " (Sandbox Gateway)" : ""}</h2>
        <p class="text-xs text-muted mb-3">Bank qarori, ZARVON tavsiyasi va mijoz tanlovi aniq ajratilgan${AppState.sandboxMode ? "; test takliflar haqiqiy bank shartnomasi emas (8.3)" : ""}.</p>
        ${
          cab.credit_applications.length
            ? cab.credit_applications
                .map(
                  (ca) => `
              <div class="card mb-3" style="background:var(--bg-subtle);">
                <div class="flex-between mb-2">
                  <strong>Ariza #${esc(ca.application_number)}</strong>
                  <span>${statusBadge(ca.status)} <span class="text-xs text-muted">Corr: ${esc(ca.correlation_id)}</span></span>
                </div>
                <div class="flex-gap mb-2">
                  ${ca.submissions.map((s) => `<span class="badge ${s.error ? "badge-warning" : "badge-info"}">${esc(s.bank)}: ${esc(s.status)}</span>`).join("")}
                </div>
                ${
                  ca.offers.length
                    ? `<div class="table-wrap">
                         <table class="data-table tabular">
                           <thead><tr><th>Bank</th><th>Muddat</th><th>Stavka / To‘liq qiymat</th><th>Komissiya</th><th>Oylik</th><th>Jami</th><th>Tanlov</th></tr></thead>
                           <tbody>
                             ${ca.offers
                               .map(
                                 (of) => `
                               <tr>
                                 <td><strong>${esc(of.bank_name)}</strong>${AppState.sandboxMode ? ` <span class="badge badge-gold">DEMO</span>` : ""}</td>
                                 <td>${of.months} oy</td>
                                 <td>${of.annual_rate_pct}% / ${of.total_cost_of_credit_pct}%</td>
                                 <td>${fmtUzs(of.mandatory_commission)}</td>
                                 <td class="fw-bold">${fmtUzs(of.monthly_payment)}</td>
                                 <td>${fmtUzs(of.total_payable)}</td>
                                 <td>${
                                   of.is_selected
                                     ? `<span class="badge badge-success">✓ Tanlangan</span>`
                                     : `<button class="btn btn-primary btn-sm" data-sel-offer="${esc(of.offer_id)}">Tanlash</button>`
                                 }</td>
                               </tr>`
                               )
                               .join("")}
                           </tbody>
                         </table>
                       </div>`
                    : `<p class="text-sm text-muted">Bank javoblari kutilmoqda.</p>`
                }
              </div>`
                )
                .join("")
            : `<p class="text-muted">Hali bank gateway arizalari yuborilmagan.</p>`
        }
      `;
      panel.querySelectorAll("[data-sel-offer]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          try {
            const res = await apiFetch(`/api/v1/finance/bank-offers/${btn.dataset.selOffer}/select/`, { method: "POST" });
            showToast(`${res.selected_bank} taklifi tanlandi!`, "success");
            load();
          } catch (err) {
            showToast(err.message, "error");
          }
        });
      });
    } else if (activeTab === "kyc") {
      const [prof, cab] = await Promise.all([apiFetch("/api/v1/accounts/profile/"), apiFetch("/api/v1/finance/cabinet/")]);
      panel.innerHTML = `
        <h2 class="mb-3">INN / PINFL + KATM Kredit Tarixi + MIB Qarzdorlik &amp; 50% DSTI Skoring</h2>
        <div class="grid-2">
          <div class="card" style="background:var(--bg-subtle);">
            <h4>Shaxsni tasdiqlash va Tashqi Kredit Tekshiruvi (28.4)</h4>
            <p class="text-xs text-muted">Pasport, PINFL va INN shifrlangan saqlanadi; KATM kredit tarixi, MIB qarzdorlik va 50% DSTI yuki tekshiriladi.</p>
            <form id="kyc-form">
              <div class="grid-2">
                <div class="form-group">
                  <label class="form-label" for="k-pinfl">14 xonali PINFL *</label>
                  <input id="k-pinfl" class="form-control tabular" placeholder="31405940010099" maxlength="14" value="">
                  <span class="form-hint">Hozirgi: ${esc(prof.user.masked_pinfl || "Kiritilmagan")}</span>
                </div>
                <div class="form-group">
                  <label class="form-label" for="k-inn">INN / STIR (9 raqam, ixtiyoriy)</label>
                  <input id="k-inn" class="form-control tabular" placeholder="305112849" maxlength="9" value="">
                  <span class="form-hint">Hozirgi: ${esc(prof.user.masked_inn || "Kiritilmagan")}</span>
                </div>
              </div>
              <div class="grid-2">
                <div class="form-group">
                  <label class="form-label" for="k-pass">Pasport / ID-karta</label>
                  <input id="k-pass" class="form-control" placeholder="AD9876543" value="">
                  <span class="form-hint">Hozirgi: ${esc(prof.user.masked_passport || "Kiritilmagan")}</span>
                </div>
                <div class="form-group">
                  <label class="form-label" for="k-by">Tug‘ilgan yil (22–65 yosh)</label>
                  <input id="k-by" type="number" class="form-control tabular" value="1994">
                </div>
              </div>
              <div class="${AppState.sandboxMode ? "grid-2" : ""}">
                <div class="form-group">
                  <label class="form-label" for="k-income">Oylik rasmiy daromad (so‘m)</label>
                  <input id="k-income" type="number" class="form-control tabular" value="${AppState.sandboxMode ? "9500000" : ""}" placeholder="Masalan: 8000000" min="1500000" step="500000">
                </div>
                ${
                  AppState.sandboxMode
                    ? `<div class="form-group">
                         <label class="form-label" for="k-scen">Sandbox Tekshiruv Ssenariysi</label>
                         <select id="k-scen" class="form-control">
                           <option value="auto">Avto (PINFL bo‘yicha)</option>
                           <option value="clean">✓ Toza tarix (krediti yo‘q — Nasiya ochiq)</option>
                           <option value="moderate_credit">⚠ Boshqa bankda krediti bor (Faqat naqd savdo)</option>
                           <option value="high_debt">⚠ Boshqa kreditlar ko‘p (DSTI > 50% — Faqat naqd)</option>
                           <option value="overdue_katm">⛔ KATM 45 kun kechikish bor (Blok)</option>
                           <option value="mib_debt">⛔ MIB ijro qarzdorligi aniqlangan (Blok)</option>
                         </select>
                       </div>`
                    : ""
                }
              </div>
              <div class="mb-3">
                <label class="flex-gap text-xs"><input type="checkbox" id="k-cons-id" checked> MyID / OneID va Soliq (INN/PINFL) tekshiruviga roziman</label>
                <label class="flex-gap text-xs mt-1"><input type="checkbox" id="k-cons-cb" checked> KATM kredit byurosi va MIB ijro bazasidan so‘rashga roziman</label>
              </div>
              <button type="submit" class="btn btn-gold" style="width:100%;">⚡ KATM + MIB Tekshirish va Limit Hisoblash</button>
            </form>
          </div>
          <div class="card" style="background:var(--bg-subtle);">
            <h4>Faol sessiyalar va Xavfsizlik</h4>
            ${prof.sessions
              .map(
                (s) => `<div class="text-xs mb-2" style="padding-bottom:6px;border-bottom:1px solid var(--border-color);">
                          <strong>${esc(s.device_name.slice(0, 48))}</strong><br>
                          IP: ${esc(s.ip_address)} • ${fmtDate(s.last_active)}
                        </div>`
              )
              .join("")}
            <div class="nasiya-callout mt-3 text-xs">
              <strong>Nimalar tekshiriladi?</strong>
              <ul style="margin:4px 0 0;padding-left:16px;">
                <li>Boshqa banklar / nasiya do‘konlardagi faol kreditlar va oylik to‘lovlar</li>
                <li>MIB (Majburiy Ijro Byurosi) qarzdorligi va taqiqlar</li>
                <li>Markaziy Bank <strong>DSTI ≤ 50%</strong> qarz yuki chegarasi</li>
              </ul>
            </div>
          </div>
        </div>
        <div id="kyc-report-mount">${renderKatmMibDstiReportHtml(cab.latest_scoring_report, cab.credit_policy)}</div>
      `;
      document.getElementById("kyc-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          if (document.getElementById("k-cons-id").checked || document.getElementById("k-cons-cb").checked) {
            await apiFetch("/api/v1/finance/consents/", {
              method: "POST",
              body: JSON.stringify({
                purposes: {
                  IDENTITY: document.getElementById("k-cons-id").checked,
                  CREDIT_BUREAU: document.getElementById("k-cons-cb").checked,
                },
              }),
            });
          }
          const res = await apiFetch("/api/v1/finance/kyc/verify/", {
            method: "POST",
            body: JSON.stringify({
              pinfl: document.getElementById("k-pinfl").value,
              inn: document.getElementById("k-inn").value,
              passport: document.getElementById("k-pass").value,
              birth_year: Number(document.getElementById("k-by").value),
              monthly_income_uzs: Number(document.getElementById("k-income").value),
              scenario: document.getElementById("k-scen")?.value || "auto",
              liveness_passed: true,
            }),
          });
          const supNote = res.supervisors_notified ? ` (${res.supervisors_notified} ta nazoratchiga xabar yuborildi)` : "";
          showToast(`${res.message || `Qaror: ${res.decision}`}${supNote}`, res.decision === "DECLINE" ? "error" : "success");
          load();
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    } else if (activeTab === "privacy") {
      const [cData, pReqs] = await Promise.all([apiFetch("/api/v1/finance/consents/"), apiFetch("/api/v1/governance/privacy-requests/")]);
      panel.innerHTML = `
        <h2 class="mb-2">Roziliklar boshqaruvi va Shaxsiy ma’lumotlar huquqi (10 / 31.2)</h2>
        <p class="text-sm text-secondary mb-3">Har bir maqsad uchun rozilik alohida beriladi va istalgan vaqtda qaytarib olinishi mumkin.</p>
        <div class="card mb-4" style="background:var(--bg-subtle);">
          ${cData.consents
            .map(
              (c) => `
            <label class="flex-between mb-2" style="cursor:pointer;">
              <span><strong>${esc(c.label)}</strong> <span class="text-xs text-muted">(v${esc(c.version)})</span></span>
              <input type="checkbox" data-consent-key="${esc(c.purpose)}" ${c.is_granted ? "checked" : ""}>
            </label>`
            )
            .join("")}
          <button id="save-consents-btn" class="btn btn-primary btn-sm mt-2">Roziliklarni saqlash</button>
        </div>

        <h3>Ma’lumot eksporti / tuzatish / o‘chirish so‘rovi</h3>
        <div class="flex-gap mt-2 mb-3">
          <button class="btn btn-outline btn-sm" data-priv-req="EXPORT">📥 Ma’lumotlarim nusxasini olish</button>
          <button class="btn btn-outline btn-sm" data-priv-req="CORRECTION">✏ Ma’lumotni tuzatish</button>
          <button class="btn btn-danger btn-sm" data-priv-req="DELETION">🗑 Ma’lumotlarni o‘chirish so‘rovi</button>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>So‘rov turi</th><th>Holat</th><th>Sana</th></tr></thead>
            <tbody>${pReqs.results.map((r) => `<tr><td>${esc(r.request_type)}</td><td>${statusBadge(r.status)}</td><td>${fmtDate(r.created_at)}</td></tr>`).join("") || "<tr><td colspan='3'>So‘rovlar yo‘q</td></tr>"}</tbody>
          </table>
        </div>
      `;
      document.getElementById("save-consents-btn").onclick = async () => {
        const purposes = {};
        panel.querySelectorAll("[data-consent-key]").forEach((el) => (purposes[el.dataset.consentKey] = el.checked));
        await apiFetch("/api/v1/finance/consents/", { method: "POST", body: JSON.stringify({ purposes }) });
        showToast("Roziliklar yangilandi.", "success");
        load();
      };
      panel.querySelectorAll("[data-priv-req]").forEach((btn) => {
        btn.onclick = async () => {
          await apiFetch("/api/v1/governance/privacy-requests/", {
            method: "POST",
            body: JSON.stringify({ request_type: btn.dataset.privReq, reason: "Mijoz kabinetidan yuborilgan so‘rov" }),
          });
          showToast("Maxfiylik so‘rovi qabul qilindi.", "success");
          load();
        };
      });
    } else if (activeTab === "wishlists") {
      const wData = await apiFetch("/api/v1/catalog/wishlists/");
      panel.innerHTML = `
        <h2 class="mb-3">Sevimli mahsulotlar (${wData.results.length})</h2>
        <div class="grid-3">
          ${wData.results
            .map(
              (w) => `
            <div class="card">
              <a href="#product/${esc(w.product.slug)}" class="fw-bold">${esc(w.product.title)}</a>
              <div class="cash-price tabular mt-1">${fmtUzs(w.product.cash_price)}</div>
              <div class="text-xs text-muted mt-1">🔔 Narx tushganda xabar berish yoqilgan</div>
            </div>`
            )
            .join("") || `<p class="text-muted">Sevimlilar ro‘yxati bo‘sh.</p>`}
        </div>
      `;
    } else if (activeTab === "notifications") {
      const nData = await apiFetch("/api/v1/governance/notifications/");
      panel.innerHTML = `
        <h2 class="mb-3">Bildirishnomalar (OTP, To‘lov va Marketing)</h2>
        <p class="text-xs text-muted mb-3">15-bo‘lim: Xabar matnida pasport yoki maxfiy kredit raqamlari hech qachon ko‘rsatilmaydi.</p>
        ${nData.notifications
          .map(
            (n) => `<div class="card mb-2" style="background:var(--bg-subtle);">
                      <div class="flex-between"><strong>${esc(n.title)}</strong> <span class="badge badge-info">${esc(n.channel)} • ${esc(n.category)}</span></div>
                      <div class="text-sm mt-1">${esc(n.body_masked)}</div>
                      <div class="text-xs text-muted mt-1">${fmtDate(n.created_at)} • ${esc(n.status)}</div>
                    </div>`
          )
          .join("") || `<p class="text-muted">Bildirishnomalar yo‘q.</p>`}
      `;
    } else if (activeTab === "support") {
      const [tData, cab] = await Promise.all([apiFetch("/api/v1/risk/tickets/"), apiFetch("/api/v1/finance/cabinet/")]);
      panel.innerHTML = `
        <h2 class="mb-3">Yordam markazi, Shikoyatlar va Skoring Apellyatsiyasi (9 / 29.2)</h2>
        <form id="ticket-form" class="card mb-4" style="background:var(--bg-subtle);">
          <div class="grid-2">
            <div class="form-group">
              <label class="form-label" for="tk-cat">Yo‘nalish</label>
              <select id="tk-cat" class="form-control">
                <option value="GENERAL">Umumiy savol</option>
                <option value="COMPLAINT">Shikoyat</option>
                <option value="RISK_APPEAL">Skoring / Limit apellyatsiyasi</option>
                <option value="RETURN_DISPUTE">Qaytarish nizosi</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label" for="tk-sub">Mavzu</label>
              <input id="tk-sub" class="form-control" placeholder="Qisqa sarlavha...">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label" for="tk-msg">Xabar matni</label>
            <textarea id="tk-msg" class="form-control" rows="2"></textarea>
          </div>
          <button type="submit" class="btn btn-primary btn-sm">Murojaat yuborish</button>
        </form>

        ${
          cab.risk_assessments.length
            ? `<div class="card mb-4">
                 <h4>Skoring qarorlari (tushunarli sabablar bilan)</h4>
                 ${cab.risk_assessments
                   .map(
                     (r) => `<div class="flex-between mt-2">
                               <div>Model: <strong>${esc(r.model_version)}</strong> • Ball: <strong>${r.score}</strong> • Sabablar: ${esc(r.reason_codes.join(", "))}</div>
                               ${
                                 r.appeal_status === "NONE"
                                   ? `<button class="btn btn-outline btn-sm" data-appeal-ra="${esc(r.id)}">Apellyatsiya berish</button>`
                                   : statusBadge(r.appeal_status)
                               }
                             </div>`
                   )
                   .join("")}
               </div>`
            : ""
        }

        ${tData.results
          .map(
            (t) => `<div class="card mb-2">
                      <div class="flex-between"><strong>#${esc(t.ticket_number)} — ${esc(t.subject)}</strong> ${statusBadge(t.status)}</div>
                      ${t.messages.map((m) => `<div class="text-sm mt-1"><strong>${esc(m.sender)}:</strong> ${esc(m.text)}</div>`).join("")}
                    </div>`
          )
          .join("")}
      `;
      document.getElementById("ticket-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await apiFetch("/api/v1/risk/tickets/", {
            method: "POST",
            body: JSON.stringify({
              category: document.getElementById("tk-cat").value,
              subject: document.getElementById("tk-sub").value,
              message: document.getElementById("tk-msg").value,
            }),
          });
          showToast("Murojaat yaratildi!", "success");
          load();
        } catch (err) {
          showToast(err.message, "error");
        }
      });
      panel.querySelectorAll("[data-appeal-ra]").forEach((btn) => {
        btn.onclick = async () => {
          await apiFetch("/api/v1/risk/assessments/", {
            method: "POST",
            body: JSON.stringify({ assessment_id: btn.dataset.appealRa, action: "APPEAL" }),
          });
          showToast("Skoring qaroriga apellyatsiya yuborildi (Inson ko‘rigi).", "success");
          load();
        };
      });
    }
  };

  load();
}
