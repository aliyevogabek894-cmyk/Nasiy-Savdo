/* Shared UI components for KATM + MIB + INN + 50% DSTI Scoring, Due Alerts, Saved Cards & Click/Payme PSP */
import { apiFetch, closeModal, esc, fmtDate, fmtUzs, genIdempotencyKey, openModal, showToast, statusBadge } from "../api.js";
import { AppState } from "../i18n.js";

export function renderDueAlertsHtml(dueAlerts = []) {
  if (!dueAlerts.length) {
    return `
      <div class="due-alert-banner due-alert-upcoming mb-4">
        <div>
          <strong>✅ Yaqin 7 kun ichida shoshilinch to‘lov yo‘q</strong>
          <div class="text-xs">Barcha faol shartnomalaringiz grafiki nazoratda. Har oylik eslatmalar SMS/Telegram orqali oldindan keladi.</div>
        </div>
        <span class="badge badge-success">Grafik toza</span>
      </div>`;
  }

  return dueAlerts
    .map((d) => {
      const cls =
        d.urgency === "OVERDUE" || d.urgency === "DUE_TODAY"
          ? "due-alert-overdue"
          : d.urgency === "DUE_SOON_3D"
            ? "due-alert-soon"
            : "due-alert-upcoming";
      const msg =
        d.days_until_due < 0
          ? `⚠ Muddati ${Math.abs(d.days_until_due)} kun o‘tgan!`
          : d.days_until_due === 0
            ? `🔴 BUGUN to‘lov kuni!`
            : `⏰ To‘lovga ${d.days_until_due} kun qoldi (${esc(d.due_date)})`;
      return `
        <div class="due-alert-banner ${cls} mb-3 tabular">
          <div>
            <div class="fw-bold">${msg} — Shartnoma #${esc(d.contract_number)} (${d.installment_no}-oy)</div>
            <div class="text-sm">To‘lanadigan summa: <strong>${fmtUzs(d.amount)}</strong> • Payme, Click, Uzum Bank yoki saqlangan karta orqali darhol to‘lang.</div>
          </div>
          <button class="btn btn-primary btn-sm" data-psp-pay-contract="${esc(d.contract_id)}" data-psp-ref="${esc(d.contract_number)}" data-psp-amt="${d.amount}">
            💳 To‘lash (${fmtUzs(d.amount)})
          </button>
        </div>`;
    })
    .join("");
}

function renderCreditPolicyBannerHtml(creditPolicy, hasBureauReport = true) {
  if (!creditPolicy) return "";
  const isBlocked = Boolean(creditPolicy.cash_only_required);
  const bg = creditPolicy.has_overdue || creditPolicy.has_mib_debt
    ? "var(--danger-bg)"
    : isBlocked
      ? "rgba(217, 119, 6, 0.14)"
      : "var(--success-bg, rgba(21, 128, 61, 0.10))";
  const border = creditPolicy.has_overdue || creditPolicy.has_mib_debt
    ? "var(--danger-fg, #dc2626)"
    : isBlocked
      ? "#d97706"
      : "var(--success-fg, #15803d)";
  const modeBadgeClass = isBlocked ? "badge-danger" : "badge-success";

  return `
    <div class="mb-3" style="padding:12px 14px;border-radius:12px;background:${bg};border:1px solid ${border};">
      <div class="flex-between" style="flex-wrap:wrap;gap:8px;">
        <div>
          <span class="badge ${modeBadgeClass}">${esc(creditPolicy.trading_mode_label || (isBlocked ? "Faqat naqd savdo" : "Nasiya ochiq"))}</span>
          <strong style="margin-left:6px;">${esc(creditPolicy.credit_condition_label || creditPolicy.credit_condition_code)}</strong>
        </div>
        ${hasBureauReport
      ? `<span class="badge badge-navy">🛡 Nazoratchiga xabar yuborilgan</span>`
      : ""
    }
      </div>
      <div class="text-sm mt-2">${esc(creditPolicy.credit_condition_detail || "")}</div>
      ${isBlocked && creditPolicy.block_reason
      ? `<div class="text-xs fw-bold mt-1" style="color:var(--danger-fg, #b91c1c);">⛔ Savdo cheklovi: ${esc(creditPolicy.block_reason)}</div>`
      : ""
    }
    </div>
  `;
}

export function renderKatmMibDstiReportHtml(rep, creditPolicy = null) {
  if (!rep) {
    return `
      ${renderCreditPolicyBannerHtml(creditPolicy, false)}
      <div class="state-box mt-3">Hali KATM + MIB + DSTI tekshiruvi o‘tkazilmagan. Yuqoridagi forma orqali PINFL va INN kiritib limitni tekshiring.</div>
    `;
  }
  const dstiAfter = Number(rep.dsti_after_pct ?? rep.dsti_before_pct ?? 0);
  const barWidth = Math.min(100, Math.max(2, Math.round(dstiAfter)));
  const barColor = dstiAfter >= 50 ? "#dc2626" : dstiAfter >= 35 ? "#d97706" : "#15803d";

  return `
    <div class="card card-elevated mt-3 tabular" style="border-top:4px solid var(--navy-700);">
      ${renderCreditPolicyBannerHtml(creditPolicy, true)}
      <div class="flex-between mb-3">
        <div>
          <span class="badge badge-navy">${esc(rep.provider_mode)}</span>
          <span class="badge badge-gold">KATM + MIB + 50% DSTI</span>
          <h3 class="mt-2" style="margin-bottom:2px;">Tashqi Skoring va Qarz Yuki Hisoboti</h3>
          <div class="text-xs text-muted">PINFL: ${esc(rep.pinfl_masked)} • INN/STIR: ${esc(rep.inn_masked || "Kiritilmagan")} • Ref: ${esc(rep.check_reference)}</div>
        </div>
        <div style="text-align:right;">
          ${statusBadge(rep.decision)}
          <div class="text-xs text-muted mt-1">${rep.is_demo ? "Sandbox Adapter" : "Rasmiy kredit byurosi"}</div>
        </div>
      </div>

      <div class="grid-4 mb-4">
        <div class="kpi-card">
          <div class="kpi-label">KATM Kredit Skori</div>
          <div class="kpi-value">${rep.katm_score} <small class="text-sm">(${esc(rep.external_credit_history_grade)})</small></div>
          <div class="text-xs text-muted">Maks kechikish: ${rep.external_overdue_days_max} kun</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">MIB Ijro Holati</div>
          <div class="kpi-value">${rep.mib_status === "BLOCKED" ? `<span style="color:var(--danger-fg);">QARZ BOR</span>` : `<span style="color:var(--success-fg);">✓ TOZA</span>`}</div>
          <div class="text-xs text-muted">Qarz: ${fmtUzs(rep.mib_debt_uzs)} (${rep.mib_active_cases_count} ta ish)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Jami DSTI Qarz Yuki</div>
          <div class="kpi-value" style="color:${barColor};">${dstiAfter}%</div>
          <div class="text-xs text-muted">Markaziy Bank chegarasi: ≤ 50%</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Xavfsiz Nasiya Limiti</div>
          <div class="kpi-value">${fmtUzs(rep.recommended_limit_uzs)}</div>
          <div class="text-xs text-muted">Maks oylik to‘lov: ${fmtUzs(rep.max_safe_monthly_uzs)}</div>
        </div>
      </div>

      <div class="mb-4">
        <div class="flex-between text-xs mb-1">
          <span><strong>DSTI (Oylik daromaddan qarz ulushi): ${dstiAfter}%</strong> — Daromad: ${fmtUzs(rep.monthly_income_uzs)}</span>
          <span style="color:var(--danger-fg);font-weight:700;">50% Qonuniy chegara</span>
        </div>
        <div class="dsti-meter-track">
          <div class="dsti-meter-fill" style="width:${barWidth}%;background:${barColor};"></div>
          <div class="dsti-50-mark" title="50% Markaziy Bank chegarasi"></div>
        </div>
        <div class="text-xs text-muted mt-2">
          Boshqa bank/nasiyadagi oylik to‘lovlar: <strong>${fmtUzs(rep.external_monthly_obligations_uzs)}</strong> •
          ZARVON faol oylik to‘lov: <strong>${fmtUzs(rep.zarvon_active_monthly_uzs)}</strong> •
          DSTI (so‘rovdan oldin): <strong>${rep.dsti_before_pct}%</strong>
        </div>
      </div>

      ${rep.mib_details && rep.mib_details.length
      ? `<div class="mb-3" style="padding:10px;border-radius:10px;background:var(--danger-bg);color:var(--danger-fg);">
               <strong>⛔ MIB bo‘yicha aniqlangan ijro hujjatlari:</strong>
               ${rep.mib_details.map((m) => `<div class="text-xs mt-1">• ${esc(m.case_no)}: ${esc(m.reason)} — <strong>${fmtUzs(m.debt_uzs)}</strong></div>`).join("")}
             </div>`
      : ""
    }

      <div class="grid-2">
        <div>
          <h4 class="mb-2">Boshqa banklar va nasiya platformalaridagi kreditlar (${(rep.external_obligations_breakdown || []).length})</h4>
          <div class="table-wrap">
            <table class="data-table text-xs">
              <thead><tr><th>Tashkilot / Bank</th><th>Turi</th><th>Oylik</th><th>Qoldiq</th><th>Holat</th></tr></thead>
              <tbody>
                ${(rep.external_obligations_breakdown || []).length
      ? rep.external_obligations_breakdown
        .map(
          (o) => `<tr><td>${esc(o.lender)}</td><td>${esc(o.type)}</td><td>${fmtUzs(o.monthly_uzs)}</td><td>${fmtUzs(o.remaining_uzs)}</td><td>${statusBadge(o.status)}</td></tr>`
        )
        .join("")
      : `<tr><td colspan="5">KATM bo‘yicha boshqa faol kredit topilmadi ✓</td></tr>`
    }
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <h4 class="mb-2">Skoring xulosasi va sabablari</h4>
          <ul class="text-sm" style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px;">
            ${(rep.decision_reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}
          </ul>
        </div>
      </div>

      ${Array.isArray(rep.bureau_trace) && rep.bureau_trace.length
      ? `<details class="mt-3" style="background:var(--bg-subtle);border:1px solid var(--border-color);border-radius:10px;padding:8px 12px;">
           <summary class="text-xs fw-bold" style="cursor:pointer;">🌐 Tashqi API HTTP Trace (MyID / KATM / MIB — ${rep.bureau_trace.length} so‘rov)</summary>
           <pre class="text-xs mt-2" style="margin-bottom:0;overflow:auto;max-height:200px;">${esc(JSON.stringify(rep.bureau_trace, null, 2))}</pre>
         </details>`
      : ""
    }
    </div>
  `;
}

export function renderSavedCardsHtml(cards = []) {
  return `
    <div class="card card-elevated mt-4">
      <div class="flex-between mb-3">
        <div>
          <h3 style="margin:0;">Bog‘langan Kartalar (Uzcard / Humo Token Vault)</h3>
          <div class="text-xs text-muted">Karta raqami to‘liq saqlanmaydi — faqat shifrlangan PSP tokeni va niqoblangan ko‘rinish (PCI-DSS tamoyili).</div>
        </div>
        <span class="badge badge-navy">${cards.length} ta karta</span>
      </div>

      <div class="grid-2 mb-3">
        ${cards.length
      ? cards
        .map(
          (c) => `
              <div class="card" style="background:var(--bg-subtle);border:${c.is_default ? "2px solid var(--gold-500)" : "1px solid var(--border-color)"};">
                <div class="flex-between">
                  <div>
                    <span class="badge badge-navy">${esc(c.card_brand)}</span>
                    ${c.is_default ? `<span class="badge badge-gold">★ Asosiy</span>` : ""}
                    <div class="fw-bold tabular mt-1">${esc(c.card_masked_pan)}</div>
                    <div class="text-xs text-muted">Muddat: ${esc(c.expiry_masked)} • Provayder: ${esc(c.provider)}</div>
                  </div>
                  <div class="flex-gap">
                    ${!c.is_default ? `<button class="btn btn-outline btn-sm" data-card-default="${esc(c.id)}">Asosiy qilish</button>` : ""}
                    <button class="btn btn-danger btn-sm" data-card-del="${esc(c.id)}">O‘chirish</button>
                  </div>
                </div>
              </div>`
        )
        .join("")
      : `<p class="text-muted text-sm">Hali bog‘langan karta yo‘q.</p>`
    }
      </div>

      <form id="add-card-form" class="card" style="background:var(--navy-50);">
        <h4 class="mb-2">+ Yangi karta ulash${AppState.sandboxMode ? " (Sandbox Tokenizatsiya)" : ""}</h4>
        <div class="grid-3">
          <div class="form-group">
            <label class="form-label" for="card-num">16 xonali karta raqami</label>
            <input id="card-num" class="form-control tabular" maxlength="19" placeholder="8600 1234 5678 9012" value="${AppState.sandboxMode ? "8600 5500 1122 4488" : ""}">
          </div>
          <div class="form-group">
            <label class="form-label" for="card-exp">Muddati (MM/YY)</label>
            <input id="card-exp" class="form-control tabular" maxlength="5" placeholder="08/28" value="${AppState.sandboxMode ? "08/28" : ""}">
          </div>
          <div class="form-group">
            <label class="form-label" for="card-psp">PSP shlyuzi</label>
            <select id="card-psp" class="form-control">
              <option value="Uzcard/Humo">Uzcard / Humo Direct</option>
              <option value="Payme">Payme Token</option>
              <option value="Click">Click Token</option>
              <option value="Uzum Bank">Uzum Bank</option>
            </select>
          </div>
        </div>
        <button type="submit" class="btn btn-primary btn-sm">🔒 Karta tokenini xavfsiz ulash</button>
      </form>
    </div>
  `;
}

export function wireSavedCardsActions(rootEl, onRefresh) {
  const form = rootEl.querySelector("#add-card-form");
  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      try {
        const res = await apiFetch("/api/v1/finance/cards/", {
          method: "POST",
          body: JSON.stringify({
            card_number: rootEl.querySelector("#card-num").value,
            expiry: rootEl.querySelector("#card-exp").value,
            provider: rootEl.querySelector("#card-psp").value,
            is_default: true,
          }),
        });
        showToast(res.detail, "success");
        onRefresh();
      } catch (err) {
        showToast(err.message, "error");
      }
    };
  }
  rootEl.querySelectorAll("[data-card-default]").forEach((btn) => {
    btn.onclick = async () => {
      await apiFetch("/api/v1/finance/cards/", { method: "PATCH", body: JSON.stringify({ card_id: btn.dataset.cardDefault, is_default: true }) });
      showToast("Asosiy karta yangilandi!", "success");
      onRefresh();
    };
  });
  rootEl.querySelectorAll("[data-card-del]").forEach((btn) => {
    btn.onclick = async () => {
      await apiFetch(`/api/v1/finance/cards/?card_id=${encodeURIComponent(btn.dataset.cardDel)}`, { method: "DELETE" });
      showToast("Karta uzildi.", "success");
      onRefresh();
    };
  });
}

export async function openElectronicReceiptModal(paymentId) {
  if (!paymentId) return;
  openModal(
    "🧾 Elektron to‘lov cheki",
    `<div class="text-muted text-sm">Elektron chek yuklanmoqda...</div>`
  );
  try {
    const r = await apiFetch(`/api/v1/finance/payments/${paymentId}/receipt/`);
    const htmlUrl = `/api/v1/finance/payments/${encodeURIComponent(paymentId)}/receipt/?view=html`;
    openModal(
      `🧾 Elektron chek #${esc(r.receipt_number)}`,
      `
        <div class="card mb-3" style="background:var(--bg-subtle);border:1px dashed var(--border);">
          <div class="flex-between mb-2">
            <strong>ZARVON PAY</strong>
            <span class="badge ${r.is_demo ? "badge-warning" : "badge-success"}">${r.is_demo ? "NAMUNA / SANDBOX" : "RASMIY CHEK"}</span>
          </div>
          <div class="tabular fw-bold" style="font-size:1.6rem;color:#0f766e;text-align:center;margin:10px 0 14px;">
            ${fmtUzs(r.amount_uzs)}
          </div>
          <div class="table-wrap">
            <table class="data-table text-sm tabular">
              <tbody>
                <tr><td class="text-muted">Chek raqami</td><td class="fw-bold" style="text-align:right;">${esc(r.receipt_number)}</td></tr>
                <tr><td class="text-muted">To‘lov ID</td><td style="text-align:right;">${esc(r.payment_intent_id)}</td></tr>
                <tr><td class="text-muted">Provayder</td><td class="fw-bold" style="text-align:right;">${esc(r.provider)}</td></tr>
                <tr><td class="text-muted">Tashqi tranzaksiya</td><td style="text-align:right;">${esc(r.external_trans_id || "—")}</td></tr>
                <tr><td class="text-muted">Maqsadi</td><td style="text-align:right;">${esc(r.target_type)} (${esc(r.target_number)})</td></tr>
                <tr><td class="text-muted">Mijoz</td><td style="text-align:right;">${esc(r.customer_name)} (${esc(r.customer_phone_masked)})</td></tr>
                <tr><td class="text-muted">Sana</td><td style="text-align:right;">${fmtDate(r.paid_at)}</td></tr>
                <tr><td class="text-muted">Holat</td><td style="text-align:right;">${statusBadge(r.status)}</td></tr>
                <tr><td class="text-muted">Qolgan nasiya qoldig‘i</td><td class="fw-bold" style="text-align:right;">${fmtUzs(r.remaining_balance_after || 0)}</td></tr>
                <tr><td class="text-muted">Tekshiruv kodi</td><td style="text-align:right;"><code>${esc(r.verification_code)}</code></td></tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="flex-gap">
          <a href="${esc(htmlUrl)}" target="_blank" rel="noopener" class="btn btn-primary" style="flex:1;text-align:center;">🖨 Chop etish / PDF sahifasi</a>
          <button type="button" id="receipt-modal-close" class="btn btn-outline">Yopish</button>
        </div>
      `
    );
    document.getElementById("receipt-modal-close")?.addEventListener("click", closeModal);
  } catch (err) {
    openModal(
      "🧾 Elektron chek",
      `<p class="text-danger">${esc(err.message)}</p><button type="button" id="receipt-err-close" class="btn btn-outline mt-2">Yopish</button>`
    );
    document.getElementById("receipt-err-close")?.addEventListener("click", closeModal);
  }
}

export function openPspPayModal({ reference, contractId = null, suggestedAmount, cards = [], allowEarly = true, onSuccess }) {
  let selectedPsp = "Payme";
  let selectedCardId = cards.find((c) => c.is_default)?.id || cards[0]?.id || "";
  const providers = [
    { id: "Payme", badge: "psp-chip-payme", title: "Payme", sub: "JSON-RPC 2.0 • 100 tiyin aniqlik" },
    { id: "Click", badge: "psp-chip-click", title: "Click", sub: "Prepare/Complete + MD5 imzo" },
    { id: "Uzum Bank", badge: "psp-chip-uzum", title: "Uzum Bank", sub: "Tezkor bank hamyoni" },
    { id: "Paynet", badge: "psp-chip-paynet", title: "Paynet", sub: "UWS JSON-RPC • Milliy tarmoq" },
    { id: "Uzcard/Humo", badge: "", title: "Bog‘langan karta", sub: cards[0] ? cards[0].card_masked_pan : "Tokenizatsiya" },
  ];

  openModal(
    `To‘lov o‘tkazish — ${reference}`,
    `
      <div class="text-xs text-muted mb-3">${
        AppState.sandboxMode
          ? "Sandbox PSP shlyuzi orqali real Click/Payme protokoli tekshiriladi va jadval yangilanadi."
          : "Tanlangan to‘lov tizimi orqali xavfsiz to‘lov sahifasiga o‘tasiz; to‘lov tasdiqlangach qarzdorlik avtomatik kamayadi."
      }</div>
      <div class="psp-select-grid mb-3" id="psp-opt-grid">
        ${providers
      .map(
        (pr) => `
          <button type="button" class="psp-option-card ${pr.id === selectedPsp ? "active" : ""}" data-psp-pick="${esc(pr.id)}">
            <span class="psp-chip ${pr.badge}" style="width:fit-content;">${esc(pr.title)}</span>
            <span class="text-xs text-muted">${esc(pr.sub)}</span>
          </button>`
      )
      .join("")}
      </div>

      ${cards.length
      ? `<div class="form-group">
               <label class="form-label" for="psp-card-sel">Saqlangan karta (ixtiyoriy)</label>
               <select id="psp-card-sel" class="form-control">
                 ${cards.map((c) => `<option value="${esc(c.id)}" ${c.id === selectedCardId ? "selected" : ""}>${esc(c.card_brand)} ${esc(c.card_masked_pan)} (${esc(c.expiry_masked)})</option>`).join("")}
               </select>
             </div>`
      : ""
    }

      <div class="form-group">
        <label class="form-label" for="psp-amt-in">To‘lov summasi (so‘m)</label>
        <input id="psp-amt-in" type="number" class="form-control tabular" value="${suggestedAmount}" min="1000">
      </div>

      ${allowEarly && contractId && AppState.sandboxMode
      ? `<label class="flex-gap text-sm mb-3"><input type="checkbox" id="psp-early-chk"> Muddatidan oldin qisman/to‘liq yopish (0% komissiya va jarima yo‘q)</label>`
      : ""
    }

      <div id="psp-modal-trace" class="mb-3"></div>
      <div class="flex-gap">
        <button id="psp-confirm-btn" class="btn btn-gold" style="flex:1;">${
          AppState.sandboxMode ? "⚡ To‘lovni tasdiqlash (Sandbox)" : "💳 To‘lov sahifasiga o‘tish"
        }</button>
        <button id="psp-cancel-btn" class="btn btn-outline">Bekor qilish</button>
      </div>
    `
  );

  document.querySelectorAll("[data-psp-pick]").forEach((btn) => {
    btn.onclick = () => {
      selectedPsp = btn.dataset.pspPick;
      document.querySelectorAll("[data-psp-pick]").forEach((b) => b.classList.toggle("active", b === btn));
    };
  });
  document.getElementById("psp-cancel-btn").onclick = closeModal;

  document.getElementById("psp-confirm-btn").onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    const amt = Number(document.getElementById("psp-amt-in").value || 0);
    const isEarly = Boolean(document.getElementById("psp-early-chk")?.checked);
    const chosenCard = document.getElementById("psp-card-sel")?.value || null;
    try {
      let msg = "";
      let traceHtml = "";
      let paymentId = null;
      if (isEarly && contractId && AppState.sandboxMode) {
        const er = await apiFetch(`/api/v1/finance/contracts/${contractId}/repay/`, {
          method: "POST",
          body: JSON.stringify({
            amount: amt,
            payment_method: selectedPsp,
            is_early_repayment: true,
            idempotency_key: genIdempotencyKey("rep"),
          }),
        });
        paymentId = er.payment_id || null;
        msg = `0% komissiya bilan to‘lov bajarildi! Qolgan qarz: ${fmtUzs(er.remaining_balance)}`;
      } else {
        const res = await apiFetch("/api/v1/finance/psp/checkout/", {
          method: "POST",
          body: JSON.stringify({ reference, psp_provider: selectedPsp, amount_uzs: amt, card_id: chosenCard }),
        });
        paymentId = res.payment_id || null;
        msg = res.detail || `${selectedPsp} to‘lov sahifasi tayyor.`;
        const isLiveIntent = res.mode === "LIVE_CHECKOUT_INTENT";
        const linkBtn = res.checkout_url
          ? `<div class="mt-2 mb-2"><a href="${esc(res.checkout_url)}" target="_blank" rel="noopener" class="btn ${isLiveIntent ? "btn-primary" : "btn-outline btn-sm"}">${
              isLiveIntent ? `💳 ${esc(selectedPsp)} orqali ${fmtUzs(amt)} to‘lash` : `🔗 ${esc(selectedPsp)} Checkout havolasini ochish`
            }</a></div>`
          : "";
        const tracePre = Array.isArray(res.trace) && res.trace.length
          ? `<pre class="text-xs" style="background:var(--bg-subtle);padding:8px;border-radius:8px;overflow:auto;max-height:160px;">${esc(JSON.stringify(res.trace, null, 2))}</pre>`
          : "";
        traceHtml = `${linkBtn}${tracePre}`;
      }
      const receiptBtn = paymentId
        ? `<div class="mt-2 mb-2"><button type="button" id="psp-open-receipt-btn" class="btn btn-primary btn-sm">🧾 Elektron chekni ochish</button></div>`
        : "";
      document.getElementById("psp-modal-trace").innerHTML = `<span class="badge badge-success mb-1">✓ ${esc(msg)}</span>${receiptBtn}${traceHtml}`;
      const cancelBtn = document.getElementById("psp-cancel-btn");
      if (cancelBtn) cancelBtn.textContent = "Yopish";
      if (paymentId) {
        document.getElementById("psp-open-receipt-btn")?.addEventListener("click", () => openElectronicReceiptModal(paymentId));
      }
      showToast(msg, "success");
      if (onSuccess) onSuccess();
    } catch (err) {
      showToast(err.message, "error");
      btn.disabled = false;
    }
  };
}

export async function enhanceHomeWithUzumSections(mainContainer) {
  const hero = mainContainer.querySelector(".hero-carousel-grid, .hero-grid");
  if (!hero || mainContainer.querySelector("#uzum-how-strip")) return;

  const strip = document.createElement("section");
  strip.id = "uzum-how-strip";
  strip.className = "mt-4 mb-6";
  strip.innerHTML = `
    <div class="psp-trust-strip mb-4">
      <span class="fw-bold text-sm">Rasmiy to‘lov shlyuzlari va kredit byurolari:</span>
      <span class="psp-chip psp-chip-payme">Payme</span>
      <span class="psp-chip psp-chip-click">Click</span>
      <span class="psp-chip psp-chip-uzum">Uzum Bank</span>
      <span class="psp-chip psp-chip-paynet">Paynet</span>
      <span class="psp-chip">💳 Uzcard / Humo</span>
      <span class="psp-chip">🛡 KATM + MIB Skoring</span>
      <span class="psp-chip">⚖ ≤50% DSTI &amp; ≤12 oy</span>
    </div>

    <div class="card card-elevated mb-4" style="background:linear-gradient(135deg, var(--navy-900) 0%, #1c4270 100%);color:#ffffff;border:1.5px solid var(--gold-500);">
      <div class="flex-between">
        <div>
          <span class="hero-badge" style="margin-bottom:6px;">UZUM NASIYA STRUKTURASI • KATM + MIB SKORING</span>
          <h2 style="color:#ffffff;margin-bottom:4px;">1 daqiqada INN / PINFL orqali shaxsiy nasiya limitingizni biling</h2>
          <div class="text-sm" style="color:#cbd5e1;">Boshqa banklardagi kreditlaringiz, MIB qarzdorlik holati va Markaziy Bankning 50% DSTI mezoni bir zumda hisoblanadi.</div>
        </div>
        <div class="flex-gap">
          <a href="#customer/kyc" class="btn btn-gold">⚡ Limitni hozir tekshirish →</a>
          <a href="#calculator" class="btn btn-outline" style="color:#ffffff;border-color:rgba(255,255,255,0.4);">Kalkulyator</a>
        </div>
      </div>
    </div>

    <div class="how-strip-grid">
      <div class="how-step-card">
        <span class="how-step-num">1</span>
        <strong>PINFL / INN va MyID roziligi</strong>
        <div class="text-xs text-secondary">14 xonali PINFL va ixtiyoriy 9 xonali INN/STIR kiritiladi; ma’lumotlar Fernet bilan shifrlanadi.</div>
      </div>
      <div class="how-step-card">
        <span class="how-step-num">2</span>
        <strong>KATM, MIB va 50% DSTI tahlili</strong>
        <div class="text-xs text-secondary">MIB ijro qarzlari, boshqa bank/nasiya kreditlari va oylik to‘lov yukingiz avtomatik tekshiriladi.</div>
      </div>
      <div class="how-step-card">
        <span class="how-step-num">3</span>
        <strong>3–12 oylik shaffof jadval</strong>
        <div class="text-xs text-secondary">Har bir mahsulot sahifasida aniq oylik to‘lov, yillik chegara (≤50%) va 0% erta yopish kafolati.</div>
      </div>
      <div class="how-step-card">
        <span class="how-step-num">4</span>
        <strong>Click / Payme &amp; Eslatmalar</strong>
        <div class="text-xs text-secondary">To‘lovga 7, 3 va 1 kun qolganda avtomatik xabar keladi — 1 bosishda to‘lang!</div>
      </div>
    </div>
  `;
  hero.insertAdjacentElement("afterend", strip);
}
