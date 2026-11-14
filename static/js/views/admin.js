/* Comprehensive Multi-Role Admin, Compliance, Risk, Banking, Collections & Audit Console */
import { apiFetch, closeModal, esc, fmtDate, fmtUzs, openModal, showToast, statusBadge } from "../api.js";
import { AppState } from "../i18n.js";

const ADMIN_ROLES = new Set([
  "SUPER_ADMIN",
  "MARKETPLACE_ADMIN",
  "FINANCE_OFFICER",
  "RISK_MANAGER",
  "COLLECTIONS_AGENT",
  "FRAUD_ANALYST",
  "CONTENT_MANAGER",
  "DELIVERY_MANAGER",
  "FINANCE_OPERATIONS",
  "SUPPORT_AGENT",
  "AUDITOR",
]);

export async function renderAdminPortalView(container, refreshAuthCallback) {
  if (!AppState.authenticated || !ADMIN_ROLES.has(AppState.user.role)) {
    container.innerHTML = `
      <div class="state-box">
        <span class="badge badge-danger">⛔ Admin va Operatsiyalar Paneli Himoyalangan (RBAC)</span>
        <h2 class="mt-2">Vakolatli xodim sifatida tizimga kiring</h2>
        <p class="text-muted">Mijoz yoki sotuvchi akkauntlari admin API so‘rovlariga kira olmaydi (backend 403 cheklovi).</p>
        <div class="flex-gap mt-3" style="justify-content:center;">
          <button class="btn btn-primary" data-adm-sw="SUPER_ADMIN">🛡 Super Admin sifatida kirish</button>
          <button class="btn btn-outline" data-adm-sw="MARKETPLACE_ADMIN">📦 Marketplace Admin</button>
          <button class="btn btn-outline" data-adm-sw="RISK_MANAGER">⚖ Risk Manager</button>
          <button class="btn btn-outline" data-adm-sw="AUDITOR">👁 Auditor (Faqat o‘qish)</button>
        </div>
      </div>
    `;
    container.querySelectorAll("[data-adm-sw]").forEach((btn) => {
      btn.onclick = async () => {
        await apiFetch("/api/v1/auth/demo-switch/", { method: "POST", body: JSON.stringify({ role: btn.dataset.admSw }) });
        await refreshAuthCallback();
        renderAdminPortalView(container, refreshAuthCallback);
      };
    });
    return;
  }

  let activeTab = "dashboard";
  const adminTabs = [
    ["dashboard", "📊 Dashboard & Voronka"],
    ["sellers", "🏪 Sotuvchilar & Taklifnomalar"],
    ["moderation", "🔍 Mahsulot moderatsiyasi"],
    ["cms", "🏷 Kategoriyalar & CMS/Promo"],
    ["nasiya", "⚖ Nasiya & Compliance"],
    ["banks", "🏦 Banklar & Webhook"],
    ["reconciliation", "💰 To‘lov & Reconciliation"],
    ["collections", "📞 Undirish (DPD) & Restrukt."],
    ["fraud", "🚨 Firibgarlik & Xavfsizlik"],
    ["appeals", "💬 Murojaatlar & Apellyatsiya"],
    ["governance", "🔐 Xodimlar, Maker-Checker & Audit"],
  ];

  const load = async () => {
    container.innerHTML = `
      <div class="flex-between mb-3">
        <div>
          <h1 style="margin:0;">ZARVON Admin &amp; Operatsiyalar Konsoli</h1>
          <div class="text-sm text-muted">
            Xodim: <strong>${esc(AppState.user.full_name)}</strong> • Rol: <span class="badge badge-navy">${esc(AppState.user.role_label)}</span>
            • MFA: ${AppState.mfaVerified ? `<span class="badge badge-success">✓ Tasdiqlangan</span>` : `<button id="adm-mfa-btn" class="btn btn-outline btn-sm">MFA Tasdiqlash</button>`}
          </div>
        </div>
      </div>
      <div class="portal-layout">
        <aside class="portal-sidebar" aria-label="Admin menyusi">
          ${adminTabs.map(([id, lbl]) => `<button class="portal-tab ${activeTab === id ? "active" : ""}" data-atab="${id}">${lbl}</button>`).join("")}
        </aside>
        <section id="admin-panel" class="card">Yuklanmoqda...</section>
      </div>
    `;

    document.getElementById("adm-mfa-btn")?.addEventListener("click", async () => {
      await apiFetch("/api/v1/auth/mfa-verify/", { method: "POST", body: JSON.stringify({ code: "123456" }) });
      await refreshAuthCallback();
      showToast("MFA qayta autentifikatsiyasi tasdiqlandi!", "success");
      load();
    });

    container.querySelectorAll("[data-atab]").forEach((btn) => {
      btn.onclick = () => {
        activeTab = btn.dataset.atab;
        load();
      };
    });

    const panel = document.getElementById("admin-panel");

    try {
      if (activeTab === "dashboard") {
        const d = await apiFetch("/api/v1/risk/dashboard/");
        const k = d.kpis;
        panel.innerHTML = `
          <h2 class="mb-3">Ijroiya KPI va Platforma Holati (3.1 / 16 / 28.8)</h2>
          <div class="grid-4 mb-4 tabular">
            <div class="kpi-card"><div class="kpi-label">Umumiy GMV</div><div class="kpi-value">${fmtUzs(k.gmv_uzs)}</div><div class="text-xs text-muted">Buyurtmalar: ${k.total_orders} • Bekor: ${k.cancel_rate_pct}%</div></div>
            <div class="kpi-card"><div class="kpi-label">Faol Nasiya Portfeli</div><div class="kpi-value">${fmtUzs(k.active_portfolio_uzs)}</div><div class="text-xs text-muted">Shartnomalar: ${k.active_nasiya_contracts} • PAR30: ${k.par30_pct}%</div></div>
            <div class="kpi-card"><div class="kpi-label">Navbatlar (Sotuvchi / Moder.)</div><div class="kpi-value">${k.pending_seller_apps} / ${k.moderation_queue}</div><div class="text-xs text-muted">Faol do‘konlar: ${k.active_stores}</div></div>
            <div class="kpi-card"><div class="kpi-label">Bank API &amp; Xavfsizlik</div><div class="kpi-value">${k.banks_online} Online</div><div class="text-xs text-muted">Fraud: ${k.open_fraud_cases} • Security: ${k.open_security_alerts}</div></div>
          </div>

          <div class="grid-2">
            <div class="card" style="background:var(--bg-subtle);">
              <h3>Konversiya Voronkasi (33-bo‘lim)</h3>
              ${d.funnel
                .map(
                  (f) => `
                <div class="mb-2">
                  <div class="flex-between text-sm"><span>${esc(f.stage)}</span><strong class="tabular">${f.count} (${f.pct}%)</strong></div>
                  <div class="progress-track mt-1"><div class="progress-fill" style="width:${f.pct}%;"></div></div>
                </div>`
                )
                .join("")}
            </div>
            <div class="card" style="background:var(--bg-subtle);">
              <h3>Customer 360 (Niqoblangan PII — 33-bo‘lim)</h3>
              <div class="table-wrap">
                <table class="data-table text-sm tabular">
                  <thead><tr><th>Mijoz</th><th>KYC</th><th>PINFL</th><th>Buyurtma / Nasiya</th></tr></thead>
                  <tbody>
                    ${d.customer_360_preview
                      .map((c) => `<tr><td><strong>${esc(c.full_name)}</strong><br><span class="text-xs text-muted">${esc(c.phone)}</span></td><td>${statusBadge(c.kyc_status)}</td><td>${esc(c.masked_pinfl || "—")}</td><td>${c.orders_count} / ${c.contracts_count}</td></tr>`)
                      .join("")}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        `;
      } else if (activeTab === "sellers") {
        const [invData, appData] = await Promise.all([apiFetch("/api/v1/sellers/invitations/"), apiFetch("/api/v1/sellers/applications/")]);
        panel.innerHTML = `
          <h2 class="mb-3">Sotuvchi Taklifnomalari va KYC Verifikatsiyasi (4-bo‘lim)</h2>
          <form id="adm-inv-form" class="card mb-4" style="background:var(--navy-50);">
            <h4>Yangi bir martalik taklifnoma yaratish</h4>
            <div class="grid-3 mt-2">
              <input id="ai-comp" class="form-control" placeholder="Kompaniya / Do‘kon nomi" required>
              <input id="ai-phone" class="form-control" placeholder="+99890..." required>
              <input id="ai-email" class="form-control" placeholder="partner@company.uz">
            </div>
            <button type="submit" class="btn btn-gold btn-sm mt-2">🔐 Token yaratish (bazada xesh saqlanadi)</button>
            <div id="ai-token-out" class="mt-2"></div>
          </form>

          <h3>Sotuvchi arizalari (${appData.applications.length})</h3>
          <div class="table-wrap mb-4">
            <table class="data-table">
              <thead><tr><th>Kompaniya</th><th>Vakil / Tel</th><th>Bank (niqob)</th><th>Holat</th><th>Qaror</th></tr></thead>
              <tbody>
                ${appData.applications
                  .map(
                    (a) => `
                  <tr>
                    <td><strong>${esc(a.public_name)}</strong><br><span class="text-xs text-muted">${esc(a.legal_name)} (${esc(a.entity_type)})</span></td>
                    <td>${esc(a.representative_name)}<br><span class="text-xs">${esc(a.official_phone)}</span></td>
                    <td class="tabular text-xs">${esc(a.masked_bank || "****")}</td>
                    <td>${statusBadge(a.status)}</td>
                    <td>
                      <div class="flex-gap">
                        <button class="btn btn-success btn-sm" data-sdec="${esc(a.id)}" data-st="Approved">Tasdiqlash</button>
                        <button class="btn btn-outline btn-sm" data-sdec="${esc(a.id)}" data-st="Needs Info">Ma’lumot so‘rash</button>
                        <button class="btn btn-danger btn-sm" data-sdec="${esc(a.id)}" data-st="Rejected">Rad etish</button>
                      </div>
                    </td>
                  </tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>

          <h4>Yuborilgan taklifnomalar (${invData.results.length})</h4>
          <div class="table-wrap">
            <table class="data-table text-sm">
              <thead><tr><th>Kompaniya</th><th>Telefon</th><th>Token SHA-256 prefiksi</th><th>Holat</th></tr></thead>
              <tbody>${invData.results.map((i) => `<tr><td>${esc(i.company_name)}</td><td>${esc(i.target_phone)}</td><td class="tabular">${esc(i.token_hash_prefix)}</td><td>${statusBadge(i.status)}</td></tr>`).join("")}</tbody>
            </table>
          </div>
        `;
        document.getElementById("adm-inv-form").onsubmit = async (e) => {
          e.preventDefault();
          try {
            const res = await apiFetch("/api/v1/sellers/invitations/", {
              method: "POST",
              body: JSON.stringify({
                company_name: document.getElementById("ai-comp").value,
                target_phone: document.getElementById("ai-phone").value,
                target_email: document.getElementById("ai-email").value,
                expires_hours: 72,
              }),
            });
            document.getElementById("ai-token-out").innerHTML = `
              <div class="badge badge-success" style="white-space:normal;">
                ✓ Bir martalik token: <strong>${esc(res.one_time_invite_token)}</strong> (Onboarding sahifasida tekshiring!)
              </div>
            `;
            showToast("Taklifnoma yaratildi!", "success");
          } catch (err) {
            showToast(err.message, "error");
          }
        };
        panel.querySelectorAll("[data-sdec]").forEach((btn) => {
          btn.onclick = async () => {
            const st = btn.dataset.st;
            const note = st === "Approved" ? "KYC va hujjatlar tasdiqlandi." : "Qo‘shimcha hujjat yoki izoh talab etiladi.";
            try {
              await apiFetch(`/api/v1/sellers/applications/${btn.dataset.sdec}/decide/`, {
                method: "POST",
                body: JSON.stringify({ status: st, reason_code: st.toUpperCase(), note }),
              });
              showToast(`Sotuvchi holati yangilandi: ${st}`, "success");
              load();
            } catch (err) {
              showToast(err.message, "error");
            }
          };
        });
      } else if (activeTab === "moderation") {
        const mod = await apiFetch("/api/v1/sellers/moderation-queue/");
        panel.innerHTML = `
          <h2 class="mb-3">Mahsulot Moderatsiyasi Navbati (${mod.queue.length})</h2>
          ${
            mod.queue.length
              ? mod.queue
                  .map(
                    (p) => `
                <div class="card mb-3" style="background:var(--bg-subtle);">
                  <div class="flex-between">
                    <div>
                      <strong>${esc(p.title)}</strong> (${esc(p.sku)}) • Do‘kon: ${esc(p.store_name)} • <strong class="tabular">${fmtUzs(p.cash_price)}</strong>
                      ${
                        p.latest_version
                          ? `<div class="text-xs text-secondary mt-1">Tahrir farqi: Eski (${fmtUzs(p.latest_version.previous.cash_price)}) → Yangi (${fmtUzs(p.latest_version.proposed.cash_price)})</div>`
                          : ""
                      }
                    </div>
                    <div class="flex-gap">
                      ${statusBadge(p.status)}
                      <button class="btn btn-success btn-sm" data-mdec="${esc(p.id)}" data-d="Approved">✓ Tasdiqlash</button>
                      <button class="btn btn-danger btn-sm" data-mdec="${esc(p.id)}" data-d="Rejected">✕ Rad etish</button>
                    </div>
                  </div>
                </div>`
                  )
                  .join("")
              : `<p class="text-muted">Moderatsiya navbati bo‘sh.</p>`
          }
          <h3 class="mt-4">Moderatsiya tarixi</h3>
          <div class="table-wrap mt-2">
            <table class="data-table text-sm">
              <thead><tr><th>Mahsulot</th><th>Moderator</th><th>Qaror</th><th>Sabab</th><th>Sana</th></tr></thead>
              <tbody>${mod.history.map((h) => `<tr><td>${esc(h.product_title)}</td><td>${esc(h.moderator)}</td><td>${statusBadge(h.decision)}</td><td>${esc(h.reason_code)} ${esc(h.comment)}</td><td>${fmtDate(h.created_at)}</td></tr>`).join("") || "<tr><td colspan='5'>Tarix bo‘sh</td></tr>"}</tbody>
            </table>
          </div>
        `;
        panel.querySelectorAll("[data-mdec]").forEach((btn) => {
          btn.onclick = async () => {
            const dec = btn.dataset.d;
            try {
              await apiFetch(`/api/v1/sellers/moderation-queue/${btn.dataset.mdec}/decide/`, {
                method: "POST",
                body: JSON.stringify({
                  decision: dec,
                  reason_code: dec === "Approved" ? "CATALOG_OK" : "DESC_OR_PRICE_ISSUE",
                  comment: dec === "Approved" ? "Katalog standartlariga mos" : "Tavsif yoki narx aniqlashtirilishi kerak",
                }),
              });
              showToast(`Mahsulot ${dec} qilindi!`, "success");
              load();
            } catch (err) {
              showToast(err.message, "error");
            }
          };
        });
      } else if (activeTab === "cms") {
        const [cats, cms] = await Promise.all([apiFetch("/api/v1/catalog/categories/"), apiFetch("/api/v1/catalog/cms/")]);
        panel.innerHTML = `
          <h2 class="mb-3">Kategoriyalar (Compliance bayrog‘i), CMS Bannerlar va Promo-kodlar</h2>
          <div class="grid-2 mb-4">
            <div class="card" style="background:var(--bg-subtle);">
              <h4>Kategoriyalar va Nasiya ruxsati</h4>
              ${cats.results
                .map(
                  (c) => `<div class="flex-between text-sm mb-2">
                            <span><strong>${esc(c.name)}</strong> (${esc(c.slug)})</span>
                            ${c.installment_allowed ? `<span class="badge badge-success">Nasiya ruxsat</span>` : `<span class="badge badge-danger">Taqiqlangan (27.1)</span>`}
                          </div>`
                )
                .join("")}
            </div>
            <div class="card" style="background:var(--bg-subtle);">
              <h4>Faol Promo-kodlar</h4>
              ${cms.promos
                .map(
                  (p) => `<div class="flex-between text-sm mb-2">
                            <span><strong>${esc(p.code)}</strong> — ${esc(p.title)}</span>
                            <span class="tabular text-xs">Byudjet: ${fmtUzs(p.used_budget_uzs)} / ${fmtUzs(p.max_budget_uzs)}</span>
                          </div>`
                )
                .join("")}
            </div>
          </div>
          <h4>CMS Bosh sahifa bannerlari</h4>
          ${cms.banners.map((b) => `<div class="card mb-2"><strong>${esc(b.title)}</strong> <span class="badge badge-gold">${esc(b.badge_text)}</span><div class="text-sm text-muted">${esc(b.subtitle)}</div></div>`).join("")}
        `;
      } else if (activeTab === "nasiya") {
        const [comp, plans] = await Promise.all([apiFetch("/api/v1/governance/compliance/"), apiFetch("/api/v1/finance/plans/")]);
        panel.innerHTML = `
          <h2 class="mb-3">Nasiya Rejalari, BHM &amp; 2027 Compliance Guard</h2>
          <div class="card mb-4" style="background:var(--gold-100);border-color:var(--gold-500);">
            <div class="flex-between">
              <div>
                <strong>Amaldagi BHM: <span class="tabular">${fmtUzs(comp.bhm_amount_uzs)}</span></strong> •
                Maksimal nasiya (250 BHM): <strong class="tabular">${fmtUzs(comp.max_installment_uzs)}</strong> •
                Qonun versiyasi: <strong>${esc(comp.version_code)}</strong>
              </div>
              <button id="prop-bhm-btn" class="btn btn-primary btn-sm">BHM yangilash (Maker-Checker)</button>
            </div>
          </div>

          <form id="new-plan-form" class="card mb-4" style="background:var(--bg-subtle);">
            <h4>Yangi nasiya rejasini qo‘shish (Compliance Guard avtomatik tekshiradi)</h4>
            <div class="grid-3 mt-2">
              <input id="np-name" class="form-control" placeholder="Reja nomi" value="Test 15 oylik reja">
              <input id="np-months" type="number" class="form-control" placeholder="Muddat (oy)" value="15">
              <input id="np-rate" type="number" step="0.1" class="form-control" placeholder="Yillik ustama %" value="25">
            </div>
            <span class="form-hint">Eslatma: >12 oy yoki >50% yillik yuklama kiritib Compliance Guard bloklashini sinab ko‘rishingiz mumkin!</span>
            <button type="submit" class="btn btn-outline btn-sm mt-2">Rejani saqlash</button>
          </form>

          <div class="table-wrap">
            <table class="data-table tabular">
              <thead><tr><th>Reja</th><th>Muddat</th><th>Yillik ustama %</th><th>Komissiya %</th><th>Kechikish/kun</th><th>Versiya</th></tr></thead>
              <tbody>
                ${plans.results
                  .map((p) => `<tr><td><strong>${esc(p.name)}</strong></td><td>${p.months} oy</td><td>${p.annual_markup_pct}%</td><td>${p.commission_pct}%</td><td>${p.late_fee_daily_pct}%</td><td>${esc(p.compliance_version)}</td></tr>`)
                  .join("")}
              </tbody>
            </table>
          </div>
        `;
        document.getElementById("new-plan-form").onsubmit = async (e) => {
          e.preventDefault();
          try {
            await apiFetch("/api/v1/finance/plans/", {
              method: "POST",
              body: JSON.stringify({
                name: document.getElementById("np-name").value,
                months: Number(document.getElementById("np-months").value),
                annual_markup_pct: Number(document.getElementById("np-rate").value),
              }),
            });
            showToast("Yangi reja saqlandi!", "success");
            load();
          } catch (err) {
            showToast(`Compliance Guard blokladi: ${err.message}`, "error");
          }
        };
        document.getElementById("prop-bhm-btn").onclick = async () => {
          try {
            await apiFetch("/api/v1/governance/bhm-propose/", {
              method: "POST",
              body: JSON.stringify({ amount_uzs: 455000, reason: "Yangi BHM qiymati bo‘yicha hukumat qarori asosida yangilash" }),
            });
            showToast("BHM o‘zgarishi Maker-Checker tasdig‘iga yuborildi!", "success");
          } catch (err) {
            showToast(err.message, "error");
          }
        };
      } else if (activeTab === "banks") {
        const bData = await apiFetch("/api/v1/finance/bank-partners/");
        panel.innerHTML = `
          <h2 class="mb-3">Bank Hamkorlari Adapterlari va Webhook Idempotency (8.4 / 23.1)</h2>
          <p class="text-sm text-secondary mb-3">Biror bankni <strong>TIMEOUT</strong> holatiga o‘tkazib, Multi-Bank Gateway kassada qolgan banklar bilan uzluksiz ishlashini tekshiring.</p>
          <div class="table-wrap mb-4">
            <table class="data-table tabular">
              <thead><tr><th>Bank</th><th>Muhit</th><th>Uptime</th><th>Latency</th><th>Holat</th><th>Adapter testi</th></tr></thead>
              <tbody>
                ${bData.banks
                  .map(
                    (b) => `
                  <tr>
                    <td><strong>${esc(b.name)}</strong> (${esc(b.code)})</td>
                    <td>${esc(b.environment)}</td>
                    <td>${b.uptime_pct}%</td>
                    <td>${b.avg_latency_ms} ms</td>
                    <td>${statusBadge(b.adapter_status)}</td>
                    <td>
                      <div class="flex-gap">
                        <button class="btn btn-outline btn-sm" data-bst="${esc(b.id)}" data-v="ONLINE">ONLINE</button>
                        <button class="btn btn-danger btn-sm" data-bst="${esc(b.id)}" data-v="TIMEOUT">Simulyatsiya TIMEOUT</button>
                      </div>
                    </td>
                  </tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>

          <div class="flex-between mb-2">
            <h3>Oxirgi Webhook hodisalari</h3>
            <div class="flex-gap">
              <button id="wh-test-ok" class="btn btn-outline btn-sm">✓ Imzolangan webhook testi</button>
              <button id="wh-test-bad" class="btn btn-danger btn-sm">✕ Noto‘g‘ri imzo testi</button>
            </div>
          </div>
          <div class="table-wrap">
            <table class="data-table text-sm">
              <thead><tr><th>Provayder</th><th>Event ID</th><th>Imzo</th><th>Vaqt</th></tr></thead>
              <tbody>${bData.webhooks.map((w) => `<tr><td>${esc(w.provider)}</td><td>${esc(w.event_id)}</td><td>${w.signature_valid ? `<span class="badge badge-success">Yaroqli</span>` : `<span class="badge badge-danger">Noto‘g‘ri</span>`}</td><td>${fmtDate(w.received_at)}</td></tr>`).join("") || "<tr><td colspan='4'>Webhook log bo‘sh</td></tr>"}</tbody>
            </table>
          </div>
        `;
        panel.querySelectorAll("[data-bst]").forEach((btn) => {
          btn.onclick = async () => {
            await apiFetch("/api/v1/finance/bank-partners/", {
              method: "POST",
              body: JSON.stringify({ bank_id: btn.dataset.bst, adapter_status: btn.dataset.v }),
            });
            showToast(`Bank holati: ${btn.dataset.v}`, "success");
            load();
          };
        });
        document.getElementById("wh-test-ok").onclick = async () => {
          const eid = `WH-${Date.now()}`;
          await apiFetch("/api/v1/finance/webhooks/bank/", {
            method: "POST",
            headers: { "X-Zarvon-Signature": "valid-hmac-sig" },
            body: JSON.stringify({ event_id: eid, provider: "Hamkor Bank" }),
          });
          const replay = await apiFetch("/api/v1/finance/webhooks/bank/", {
            method: "POST",
            headers: { "X-Zarvon-Signature": "valid-hmac-sig" },
            body: JSON.stringify({ event_id: eid, provider: "Hamkor Bank" }),
          });
          showToast(replay.idempotent_replay ? "Webhook qabul qilindi va takroriysi idempotent bloklandi!" : "OK", "success");
          load();
        };
        document.getElementById("wh-test-bad").onclick = async () => {
          try {
            await apiFetch("/api/v1/finance/webhooks/bank/", {
              method: "POST",
              headers: { "X-Zarvon-Signature": "INVALID" },
              body: JSON.stringify({ event_id: `BAD-${Date.now()}`, provider: "Unknown" }),
            });
          } catch (err) {
            showToast(`Himoya ishladi (401): ${err.message}`, "success");
            load();
          }
        };
      } else if (activeTab === "reconciliation") {
        const rec = await apiFetch("/api/v1/finance/reconciliation/");
        panel.innerHTML = `
          <h2 class="mb-3">Kunlik Reconciliation va Sotuvchi Hisob-kitoblari (11 / 28.7)</h2>
          <div class="table-wrap mb-4">
            <table class="data-table tabular">
              <thead><tr><th>Sana</th><th>Provayder</th><th>ZARVON yozuvi</th><th>Provayder hisoboti</th><th>Farq</th><th>Holat</th></tr></thead>
              <tbody>
                ${rec.reconciliations.map((r) => `<tr><td>${fmtDate(r.date)}</td><td>${esc(r.provider)}</td><td>${fmtUzs(r.zarvon_total_uzs)}</td><td>${fmtUzs(r.provider_total_uzs)}</td><td>${fmtUzs(r.difference_uzs)}</td><td>${statusBadge(r.status)}</td></tr>`).join("")}
              </tbody>
            </table>
          </div>
          <h3>Sotuvchi sub-buyurtma hisob-kitobi</h3>
          <div class="table-wrap mt-2">
            <table class="data-table tabular text-sm">
              <thead><tr><th>Sub-buyurtma</th><th>Do‘kon</th><th>Summa</th><th>Komissiya</th><th>Holdback</th><th>Sof Payout</th><th>To‘lov holati</th></tr></thead>
              <tbody>
                ${rec.seller_payouts.map((s) => `<tr><td>${esc(s.sub_order_number)}</td><td>${esc(s.store_name)}</td><td>${fmtUzs(s.subtotal_amount)}</td><td>${fmtUzs(s.commission_amount)}</td><td>${fmtUzs(s.holdback_amount)}</td><td class="fw-bold">${fmtUzs(s.net_seller_payout)}</td><td>${statusBadge(s.payout_status)}</td></tr>`).join("")}
              </tbody>
            </table>
          </div>
        `;
      } else if (activeTab === "collections") {
        const col = await apiFetch("/api/v1/risk/collections/");
        panel.innerHTML = `
          <h2 class="mb-3">Undirish (DPD Bosqichlari) va Maker-Checker Restrukturizatsiya (28.5)</h2>
          <p class="text-xs text-muted mb-3">Collections xodimi pasport/PINFL ma’lumotlarini ko‘ra olmaydi; talabni o‘tkazish faqat MFO/Bank/Operatorga ruxsat etilgan (27.1).</p>
          ${col.cases
            .map(
              (c) => `
            <div class="card mb-3" style="background:var(--bg-subtle);">
              <div class="flex-between mb-2">
                <div><strong>${esc(c.contract_number)}</strong> • ${esc(c.customer_name)} (${esc(c.customer_phone)}) • DPD: <strong>${c.dpd_days} kun</strong></div>
                <div><strong class="tabular">${fmtUzs(c.overdue_amount_uzs)}</strong> ${statusBadge(c.stage)}</div>
              </div>
              ${c.actions.map((a) => `<div class="text-xs text-secondary mb-1">• [${esc(a.channel)}] ${esc(a.note)} ${a.respectful ? "(Odob qoidalari tasdiqlangan)" : ""}</div>`).join("")}
              <div class="flex-gap mt-2">
                <button class="btn btn-outline btn-sm" data-col-log="${esc(c.id)}">+ Aloqa qayd etish</button>
                <button class="btn btn-danger btn-sm" data-col-bad-assign="${esc(c.contract_id)}">⛔ Agentlikka sotish testi (27.1)</button>
              </div>
            </div>`
            )
            .join("")}

          <h3 class="mt-4">Restrukturizatsiya arizalari (Maker-Checker)</h3>
          <div class="table-wrap mt-2">
            <table class="data-table text-sm">
              <thead><tr><th>Shartnoma</th><th>Yangi muddat</th><th>Sabab</th><th>Tayyorladi</th><th>Holat</th><th>Checker qarori</th></tr></thead>
              <tbody>
                ${col.restructuring_cases
                  .map(
                    (r) => `
                  <tr>
                    <td>${esc(r.contract_number)}</td>
                    <td>${r.proposed_new_months} oy</td>
                    <td>${esc(r.reason)}</td>
                    <td>${esc(r.requested_by)}</td>
                    <td>${statusBadge(r.status)}</td>
                    <td>${
                      r.status === "PENDING_CHECKER"
                        ? `<button class="btn btn-success btn-sm" data-rest-dec="${esc(r.id)}">Ikkinchi tasdiq</button>`
                        : esc(r.approved_by || "—")
                    }</td>
                  </tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        `;
        panel.querySelectorAll("[data-col-log]").forEach((btn) => {
          btn.onclick = async () => {
            await apiFetch("/api/v1/risk/collections/", {
              method: "POST",
              body: JSON.stringify({
                action_kind: "LOG_CONTACT",
                case_id: btn.dataset.colLog,
                channel: "CALL_WORK_HOURS",
                note: "Ish vaqtida odob qoidalariga muvofiq eslatma berildi.",
                respectful_conduct_confirmed: true,
              }),
            });
            showToast("Aloqa qayd etildi.", "success");
            load();
          };
        });
        panel.querySelectorAll("[data-col-bad-assign]").forEach((btn) => {
          btn.onclick = async () => {
            try {
              await apiFetch("/api/v1/risk/collections/", {
                method: "POST",
                body: JSON.stringify({
                  action_kind: "ASSIGN_RECEIVABLE",
                  contract_id: btn.dataset.colBadAssign,
                  assignee_license_type: "RANDOM_COLLECTOR",
                }),
              });
            } catch (err) {
              showToast(`Qonuniy himoya ishladi: ${err.message}`, "success");
            }
          };
        });
        panel.querySelectorAll("[data-rest-dec]").forEach((btn) => {
          btn.onclick = async () => {
            try {
              await apiFetch("/api/v1/risk/collections/", {
                method: "POST",
                body: JSON.stringify({ action_kind: "DECIDE_RESTRUCTURE", restructuring_id: btn.dataset.restDec, decision: "APPROVED" }),
              });
              showToast("Restrukturizatsiya tasdiqlandi!", "success");
              load();
            } catch (err) {
              showToast(err.message, "error");
            }
          };
        });
      } else if (activeTab === "fraud") {
        const [fr, sec] = await Promise.all([apiFetch("/api/v1/risk/fraud/"), apiFetch("/api/v1/governance/security-events/")]);
        panel.innerHTML = `
          <h2 class="mb-3">Firibgarlik Signallari (31.1) va Xavfsizlik Hodisalari</h2>
          <p class="text-xs text-muted mb-3">9-bo‘lim: Fraud flag qo‘yilishi avtomatik aybdorlik emas, qo‘shimcha tekshiruvga yo‘naltiradi.</p>
          <div class="grid-2">
            <div>
              <h3>Fraud ishlari (${fr.results.length})</h3>
              ${fr.results
                .map(
                  (c) => `
                <div class="card mb-2" style="background:var(--bg-subtle);">
                  <div class="flex-between"><strong>${esc(c.signal_type)}</strong> ${statusBadge(c.status)}</div>
                  <p class="text-sm mt-1">${esc(c.summary)}</p>
                  ${
                    c.status === "OPEN"
                      ? `<div class="flex-gap mt-2">
                           <button class="btn btn-success btn-sm" data-fr-dec="${esc(c.id)}" data-st="CLEARED">Toza deb yopish</button>
                           <button class="btn btn-danger btn-sm" data-fr-dec="${esc(c.id)}" data-st="CONFIRMED">Tasdiqlash</button>
                         </div>`
                      : ""
                  }
                </div>`
                )
                .join("")}
            </div>
            <div>
              <h3>Xavfsizlik alertlari (${sec.results.length})</h3>
              ${sec.results
                .map(
                  (s) => `
                <div class="card mb-2" style="background:var(--bg-subtle);">
                  <div class="flex-between"><strong>${esc(s.event_type)}</strong> <span class="badge ${s.resolved ? "badge-success" : "badge-warning"}">${s.resolved ? "Yopilgan" : esc(s.severity)}</span></div>
                  <div class="text-sm mt-1">${esc(s.description)}</div>
                  ${!s.resolved ? `<button class="btn btn-outline btn-sm mt-2" data-sec-res="${esc(s.id)}">Hal qilindi</button>` : ""}
                </div>`
                )
                .join("")}
            </div>
          </div>
        `;
        panel.querySelectorAll("[data-fr-dec]").forEach((btn) => {
          btn.onclick = async () => {
            await apiFetch("/api/v1/risk/fraud/", {
              method: "POST",
              body: JSON.stringify({ case_id: btn.dataset.frDec, status: btn.dataset.st, resolution_note: "Fraud tahlilchisi ko‘rib chiqdi" }),
            });
            showToast("Fraud ishi yangilandi.", "success");
            load();
          };
        });
        panel.querySelectorAll("[data-sec-res]").forEach((btn) => {
          btn.onclick = async () => {
            await apiFetch("/api/v1/governance/security-events/", { method: "POST", body: JSON.stringify({ event_id: btn.dataset.secRes }) });
            showToast("Xavfsizlik hodisasi yopildi.", "success");
            load();
          };
        });
      } else if (activeTab === "appeals") {
        const [tk, ra] = await Promise.all([apiFetch("/api/v1/risk/tickets/"), apiFetch("/api/v1/risk/assessments/")]);
        panel.innerHTML = `
          <h2 class="mb-3">Mijoz murojaatlari va Skoring apellyatsiyasi (9 / 29.2)</h2>
          <div class="grid-2">
            <div>
              <h3>Ticketlar (${tk.results.length})</h3>
              ${tk.results
                .map(
                  (t) => `<div class="card mb-2" style="background:var(--bg-subtle);">
                            <div class="flex-between"><strong>#${esc(t.ticket_number)} — ${esc(t.subject)}</strong> ${statusBadge(t.status)}</div>
                            <div class="text-xs text-muted">${esc(t.user_name)} • SLA: ${t.sla_hours} soat</div>
                            ${t.messages.map((m) => `<div class="text-sm mt-1"><strong>${esc(m.sender)}:</strong> ${esc(m.text)}</div>`).join("")}
                          </div>`
                )
                .join("")}
            </div>
            <div>
              <h3>Skoring qarorlari</h3>
              ${ra.results
                .map(
                  (r) => `<div class="card mb-2" style="background:var(--bg-subtle);">
                            <div class="flex-between"><strong>${esc(r.user_name)}</strong> ${statusBadge(r.decision)}</div>
                            <div class="text-xs mt-1">Ball: ${r.score} • Apellyatsiya: ${esc(r.appeal_status)}</div>
                            ${
                              r.appeal_status === "APPEALED"
                                ? `<div class="flex-gap mt-2">
                                     <button class="btn btn-success btn-sm" data-ra-act="${esc(r.id)}" data-a="OVERTURN">Qayta tasdiqlash</button>
                                     <button class="btn btn-danger btn-sm" data-ra-act="${esc(r.id)}" data-a="UPHOLD">O‘z kuchida</button>
                                   </div>`
                                : ""
                            }
                          </div>`
                )
                .join("")}
            </div>
          </div>
        `;
        panel.querySelectorAll("[data-ra-act]").forEach((btn) => {
          btn.onclick = async () => {
            await apiFetch("/api/v1/risk/assessments/", {
              method: "POST",
              body: JSON.stringify({ assessment_id: btn.dataset.raAct, action: btn.dataset.a }),
            });
            showToast("Apellyatsiya ko‘rib chiqildi.", "success");
            load();
          };
        });
      } else if (activeTab === "governance") {
        const [stData, audData] = await Promise.all([apiFetch("/api/v1/accounts/staff/"), apiFetch("/api/v1/governance/audit-logs/")]);
        panel.innerHTML = `
          <div class="flex-between mb-3">
            <h2 style="margin:0;">Xodimlar, Maker-Checker va O‘zgarmas Audit Jurnali</h2>
            <a href="/api/v1/governance/export/" class="btn btn-outline btn-sm">📥 Niqoblangan CSV Eksport (MFA bilan)</a>
          </div>

          <h3>Maker-Checker ikki bosqichli tasdiqlar (${stData.maker_checker_requests.length})</h3>
          <div class="table-wrap mb-4">
            <table class="data-table text-sm">
              <thead><tr><th>Amal</th><th>Sabab</th><th>Tayyorladi</th><th>Holat</th><th>Tasdiq</th></tr></thead>
              <tbody>
                ${stData.maker_checker_requests
                  .map(
                    (m) => `
                  <tr>
                    <td><strong>${esc(m.action_type)}</strong></td>
                    <td>${esc(m.reason)}</td>
                    <td>${esc(m.requested_by)}</td>
                    <td>${statusBadge(m.status)}</td>
                    <td>${
                      m.status === "PENDING"
                        ? `<button class="btn btn-success btn-sm" data-mc-ok="${esc(m.id)}">Tasdiqlash</button>`
                        : esc(m.approved_by || "—")
                    }</td>
                  </tr>`
                  )
                  .join("") || "<tr><td colspan='5'>Kutilayotgan so‘rovlar yo‘q</td></tr>"}
              </tbody>
            </table>
          </div>

          <h3>Audit Jurnali (oxirgi yozuvlar)</h3>
          <div class="table-wrap">
            <table class="data-table text-xs">
              <thead><tr><th>Vaqt</th><th>Xodim / Rol</th><th>Amal</th><th>Obyekt</th><th>Sabab</th><th>Correlation ID</th></tr></thead>
              <tbody>
                ${audData.results
                  .slice(0, 25)
                  .map(
                    (a) => `<tr><td>${fmtDate(a.created_at)}</td><td><strong>${esc(a.actor)}</strong><br>${esc(a.actor_role)}</td><td>${esc(a.action)}</td><td>${esc(a.object_type)}</td><td>${esc(a.reason)}</td><td class="tabular">${esc(a.correlation_id)}</td></tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        `;
        panel.querySelectorAll("[data-mc-ok]").forEach((btn) => {
          btn.onclick = async () => {
            try {
              await apiFetch(`/api/v1/accounts/maker-checker/${btn.dataset.mcOk}/decide/`, {
                method: "POST",
                body: JSON.stringify({ decision: "APPROVED", decision_note: "Ikkinchi vakolatli xodim tomonidan tasdiqlandi" }),
              });
              showToast("Maker-Checker qarori tasdiqlandi!", "success");
              load();
            } catch (err) {
              showToast(err.message, "error");
            }
          };
        });
      }
    } catch (err) {
      panel.innerHTML = `
        <div class="state-box">
          <span class="badge badge-danger">⛔ Ruxsat cheklangan (RBAC)</span>
          <h3 class="mt-2">${esc(err.message)}</h3>
          <p class="text-sm text-muted">Sizning joriy rolingiz (${esc(AppState.user.role_label)}) ushbu bo‘limga kirish huquqiga ega emas.</p>
        </div>
      `;
    }
  };

  load();
}
