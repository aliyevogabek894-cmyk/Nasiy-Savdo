/* Seller Invitation Onboarding & Full 14-Module Tenant-Isolated Seller Kabinet */
import { apiFetch, closeModal, esc, fmtDate, fmtUzs, genIdempotencyKey, openModal, showToast, statusBadge } from "../api.js";
import { AppState } from "../i18n.js";

export async function renderSellerOnboardingView(container) {
  const urlParams = new URLSearchParams(location.search);
  const presetToken = urlParams.get("invite") || "";

  container.innerHTML = `
    <div class="card card-elevated" style="max-width:760px;margin:0 auto;">
      <span class="badge badge-gold">4-bo‘lim: Sotuvchini taklifnoma orqali ro‘yxatdan o‘tkazish</span>
      <h1 class="mt-2">ZARVON Hamkor Do‘koni Onboarding</h1>
      <p class="text-sm text-secondary">Sotuvchilar faqat admin tomonidan yuborilgan bir martalik, muddati cheklangan token orqali qo‘shiladi (token xeshi bazada saqlanadi).</p>

      <div class="card mb-4" style="background:var(--navy-50);">
        <div class="form-group">
          <label class="form-label" for="ob-token">Taklifnoma tokeni</label>
          <div class="flex-gap">
            <input id="ob-token" class="form-control" value="${esc(presetToken)}" placeholder="Admin bergan bir martalik tokenni kiriting...">
            <button id="ob-verify-btn" type="button" class="btn btn-primary">Tokenni tekshirish</button>
          </div>
          <span class="form-hint">Test uchun Admin paneldan → “Sotuvchilar &amp; Taklifnomalar” bo‘limida yangi token yaratishingiz mumkin.</span>
        </div>
        <div id="ob-token-status"></div>
      </div>

      <form id="ob-submit-form" class="hidden">
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label" for="ob-legal">Yuridik nomi (4.3)</label>
            <input id="ob-legal" class="form-control" required placeholder="«BARAKA TECH» MChJ">
          </div>
          <div class="form-group">
            <label class="form-label" for="ob-public">Ommaviy savdo nomi</label>
            <input id="ob-public" class="form-control" required placeholder="Baraka Elektronika">
          </div>
          <div class="form-group">
            <label class="form-label" for="ob-type">Faoliyat shakli</label>
            <select id="ob-type" class="form-control">
              <option value="MChJ">MChJ</option>
              <option value="YaTT">YaTT</option>
              <option value="AJ">AJ</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" for="ob-stir">STIR / INN</label>
            <input id="ob-stir" class="form-control tabular" placeholder="309112233">
          </div>
          <div class="form-group">
            <label class="form-label" for="ob-rep">Vakolatli vakil F.I.Sh</label>
            <input id="ob-rep" class="form-control" required placeholder="Azimov Timur">
          </div>
          <div class="form-group">
            <label class="form-label" for="ob-phone">Rasmiy telefon</label>
            <input id="ob-phone" class="form-control" required placeholder="+998905556677">
          </div>
          <div class="form-group">
            <label class="form-label" for="ob-addr">Yuridik va qaytarish manzili</label>
            <input id="ob-addr" class="form-control" required value="Toshkent sh., Yunusobod 11">
          </div>
          <div class="form-group">
            <label class="form-label" for="ob-bank">Bank rekviziti (shifrlangan saqlanadi)</label>
            <input id="ob-bank" class="form-control tabular" required value="20208000555544443333">
          </div>
        </div>
        <div class="form-group">
          <label class="flex-gap" style="cursor:pointer;">
            <input id="ob-terms" type="checkbox" required>
            <span class="text-sm fw-bold">Platforma qoidalari, maxfiylik siyosati va taqiqlangan tovarlar ro‘yxatini qabul qilaman (v2026.3)</span>
          </label>
        </div>
        <button type="submit" class="btn btn-gold">KYC va Tasdiqlashga yuborish →</button>
      </form>
    </div>
  `;

  document.getElementById("ob-verify-btn").onclick = async () => {
    const token = document.getElementById("ob-token").value.trim();
    const stEl = document.getElementById("ob-token-status");
    try {
      const res = await apiFetch("/api/v1/sellers/onboarding/verify-invite/", {
        method: "POST",
        body: JSON.stringify({ token }),
      });
      stEl.innerHTML = `<div class="badge badge-success">✓ Token haqiqiy: ${esc(res.company_name)}</div>`;
      document.getElementById("ob-public").value = res.company_name;
      if (res.target_phone) document.getElementById("ob-phone").value = res.target_phone;
      document.getElementById("ob-submit-form").classList.remove("hidden");
    } catch (err) {
      stEl.innerHTML = `<div class="badge badge-danger">⚠ ${esc(err.message)}</div>`;
    }
  };

  document.getElementById("ob-submit-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await apiFetch("/api/v1/sellers/onboarding/submit/", {
        method: "POST",
        body: JSON.stringify({
          token: document.getElementById("ob-token").value.trim(),
          legal_name: document.getElementById("ob-legal").value,
          public_name: document.getElementById("ob-public").value,
          entity_type: document.getElementById("ob-type").value,
          stir_number: document.getElementById("ob-stir").value,
          representative_name: document.getElementById("ob-rep").value,
          official_phone: document.getElementById("ob-phone").value,
          legal_address: document.getElementById("ob-addr").value,
          return_address: document.getElementById("ob-addr").value,
          bank_details: document.getElementById("ob-bank").value,
          terms_accepted: document.getElementById("ob-terms").checked,
        }),
      });
      showToast(`Ariza yuborildi! Holat: ${res.status}`, "success");
      location.hash = "#seller";
    } catch (err) {
      showToast(err.message, "error");
    }
  };
}

export async function renderSellerPortalView(container, refreshAuthCallback) {
  if (!AppState.authenticated || !["SELLER_OWNER", "SELLER_STAFF", "SUPER_ADMIN", "MARKETPLACE_ADMIN"].includes(AppState.user.role)) {
    container.innerHTML = `
      <div class="state-box">
        <span class="badge badge-danger">⛔ Sotuvchi kabinetiga kirish cheklangan</span>
        <h2 class="mt-2">Sotuvchi (Seller Owner / Seller Staff) sifatida kiring</h2>
        <p class="text-muted">Yuqoridagi “Kirish / Rol” tugmasi orqali <strong>Sardor Alimov (TexnoUz)</strong> yoki <strong>Dilshod Xasanov (Xodim)</strong> rolini tanlang.</p>
        <div class="flex-gap mt-3" style="justify-content:center;">
          <button id="sw-seller-btn" class="btn btn-primary">🏪 TexnoUz Seller sifatida kirish</button>
          <a href="#seller-onboarding" class="btn btn-outline">Taklifnoma orqali qo‘shilish</a>
        </div>
      </div>
    `;
    document.getElementById("sw-seller-btn")?.addEventListener("click", async () => {
      await apiFetch("/api/v1/auth/demo-switch/", { method: "POST", body: JSON.stringify({ role: "SELLER_OWNER" }) });
      await refreshAuthCallback();
      renderSellerPortalView(container, refreshAuthCallback);
    });
    return;
  }

  let activeTab = "overview";
  const sellerTabs = [
    ["overview", "📊 Umumiy ko‘rinish"],
    ["products", "📦 Mahsulotlar"],
    ["add-product", "➕ Mahsulot qo‘shish"],
    ["import", "📥 Import markazi (XLSX/CSV)"],
    ["integrations", "🔌 Tashqi integratsiya (API)"],
    ["inventory", "🏭 Ombor va Narxlar"],
    ["orders", "🚚 Buyurtmalar va Yetkazish"],
    ["returns", "↩ Qaytarishlar"],
    ["profile", "🏪 Do‘kon profili va Xodimlar"],
    ["help", "📘 Yordam va Qoidalar"],
  ];

  const loadTab = async () => {
    let cab = null;
    try {
      cab = await apiFetch("/api/v1/sellers/my-store/");
    } catch (err) {
      container.innerHTML = `<div class="state-box"><h3>${esc(err.message)}</h3><a href="#seller-onboarding" class="btn btn-primary mt-2">Onboarding holatini ko‘rish</a></div>`;
      return;
    }

    container.innerHTML = `
      <div class="flex-between mb-3">
        <div>
          <h1 style="margin:0;">${esc(cab.store.public_name)} — Sotuvchi kabineti</h1>
          <div class="text-sm text-muted">
            ${esc(cab.store.legal_name)} • Komissiya: ${cab.store.commission_pct}% • Holdback: ${cab.store.holdback_pct}% •
            ${cab.is_owner ? '<span class="badge badge-navy">Seller Owner</span>' : '<span class="badge badge-info">Seller Staff</span>'}
          </div>
        </div>
      </div>
      <div class="portal-layout">
        <aside class="portal-sidebar" aria-label="Sotuvchi menyusi">
          ${sellerTabs.map(([id, lbl]) => `<button class="portal-tab ${activeTab === id ? "active" : ""}" data-stab="${id}">${lbl}</button>`).join("")}
        </aside>
        <section id="seller-panel" class="card">Yuklanmoqda...</section>
      </div>
    `;
    container.querySelectorAll("[data-stab]").forEach((b) => {
      b.onclick = () => {
        activeTab = b.dataset.stab;
        loadTab();
      };
    });

    const panel = document.getElementById("seller-panel");

    if (activeTab === "overview") {
      panel.innerHTML = `
        <h2 class="mb-3">Do‘kon ko‘rsatkichlari</h2>
        <div class="grid-4 mb-4 tabular">
          <div class="kpi-card"><div class="kpi-label">Jami savdo</div><div class="kpi-value">${fmtUzs(cab.kpis.total_sales_uzs)}</div></div>
          <div class="kpi-card"><div class="kpi-label">Sof hisob-kitob (Payout)</div><div class="kpi-value">${fmtUzs(cab.kpis.net_payout_uzs)}</div></div>
          <div class="kpi-card"><div class="kpi-label">Ushlab qolingan (Holdback)</div><div class="kpi-value">${fmtUzs(cab.kpis.total_holdback_uzs)}</div></div>
          <div class="kpi-card"><div class="kpi-label">Buyurtmalar / Qaytarish</div><div class="kpi-value">${cab.kpis.total_orders} / ${cab.kpis.open_returns}</div></div>
        </div>

        <div class="grid-2">
          <div class="card" style="background:var(--bg-subtle);">
            <h4>Katalog holati</h4>
            <div class="flex-gap mt-2">
              <span class="badge badge-success">Faol: ${cab.kpis.approved_products}</span>
              <span class="badge badge-warning">Moderatsiyada: ${cab.kpis.pending_moderation}</span>
              <span class="badge badge-danger">Rad etilgan: ${cab.kpis.rejected_products}</span>
            </div>
          </div>
          <div class="card" style="background:var(--bg-subtle);">
            <h4>Ombor ogohlantirishlari (Low-stock)</h4>
            ${
              cab.low_stock_alerts.length
                ? cab.low_stock_alerts.map((a) => `<div class="text-sm mt-1">⚠ <strong>${esc(a.title)}</strong> — qoldiq: <span class="badge badge-danger">${a.available} dona</span></div>`).join("")
                : `<p class="text-sm text-muted mt-1">Barcha mahsulotlarda qoldiq yetarli.</p>`
            }
          </div>
        </div>
      `;
    } else if (activeTab === "products") {
      const pData = await apiFetch("/api/v1/sellers/my-products/");
      panel.innerHTML = `
        <div class="flex-between mb-3">
          <h2 style="margin:0;">Do‘kon mahsulotlari (${pData.results.length})</h2>
          <button id="go-add-prod" class="btn btn-primary btn-sm">+ Yangi mahsulot</button>
        </div>
        <div class="table-wrap">
          <table class="data-table tabular">
            <thead><tr><th>SKU</th><th>Mahsulot</th><th>Kategoriya</th><th>Naqd narx</th><th>Qoldiq</th><th>Holat</th><th>Amal</th></tr></thead>
            <tbody>
              ${pData.results
                .map(
                  (p) => `
                <tr>
                  <td>${esc(p.sku)}</td>
                  <td><strong>${esc(p.title)}</strong>${p.rejection_reason ? `<div class="text-xs form-error">${esc(p.rejection_reason)}</div>` : ""}</td>
                  <td>${esc(p.category_name)}</td>
                  <td class="fw-bold">${fmtUzs(p.cash_price)}</td>
                  <td>${p.stock_available} dona</td>
                  <td>${statusBadge(p.status)}</td>
                  <td><button class="btn btn-outline btn-sm" data-edit-prod="${esc(p.id)}" data-price="${p.cash_price}" data-title="${esc(p.title)}">Tahrirlash</button></td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      `;
      document.getElementById("go-add-prod").onclick = () => {
        activeTab = "add-product";
        loadTab();
      };
      panel.querySelectorAll("[data-edit-prod]").forEach((btn) => {
        btn.onclick = () => {
          openModal(
            "Mahsulotni tahrirlash (keskin o‘zgarish qayta moderatsiyaga tushadi)",
            `
              <div class="form-group">
                <label class="form-label" for="ep-title">Nomi</label>
                <input id="ep-title" class="form-control" value="${esc(btn.dataset.title)}">
              </div>
              <div class="form-group">
                <label class="form-label" for="ep-price">Yangi naqd narx (so‘m)</label>
                <input id="ep-price" type="number" class="form-control tabular" value="${btn.dataset.price}">
              </div>
              <button id="ep-save" class="btn btn-primary" style="width:100%;">Saqlash</button>
            `,
            () => {
              document.getElementById("ep-save").onclick = async () => {
                try {
                  const res = await apiFetch(`/api/v1/sellers/my-products/${btn.dataset.editProd}/`, {
                    method: "PATCH",
                    body: JSON.stringify({
                      title: document.getElementById("ep-title").value,
                      cash_price: Number(document.getElementById("ep-price").value),
                    }),
                  });
                  closeModal();
                  showToast(`Saqlandi! Joriy holat: ${res.status}`, "success");
                  loadTab();
                } catch (err) {
                  showToast(err.message, "error");
                }
              };
            }
          );
        };
      });
    } else if (activeTab === "add-product") {
      const cats = await apiFetch("/api/v1/catalog/categories/");
      panel.innerHTML = `
        <h2 class="mb-3">Yangi mahsulot qo‘shish (5.1)</h2>
        <form id="add-prod-form">
          <div class="grid-2">
            <div class="form-group">
              <label class="form-label" for="ap-title">Mahsulot nomi</label>
              <input id="ap-title" class="form-control" required placeholder="Samsung Galaxy Z Flip 6">
            </div>
            <div class="form-group">
              <label class="form-label" for="ap-sku">Noyob SKU</label>
              <input id="ap-sku" class="form-control" required placeholder="SAM-ZF6-256">
            </div>
            <div class="form-group">
              <label class="form-label" for="ap-cat">Kategoriya</label>
              <select id="ap-cat" class="form-control">
                ${cats.results.map((c) => `<option value="${esc(c.id)}">${esc(c.name)} ${c.installment_allowed ? "" : "(Nasiya taqiqlangan)"}</option>`).join("")}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label" for="ap-brand">Brend</label>
              <input id="ap-brand" class="form-control" value="Samsung">
            </div>
            <div class="form-group">
              <label class="form-label" for="ap-price">Naqd narx (so‘m)</label>
              <input id="ap-price" type="number" class="form-control tabular" required min="1000" value="9500000">
            </div>
            <div class="form-group">
              <label class="form-label" for="ap-stock">Ombor soni</label>
              <input id="ap-stock" type="number" class="form-control tabular" required min="0" value="10">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label" for="ap-img">Rasm URL (ixtiyoriy)</label>
            <input id="ap-img" class="form-control" value="/static/icons/smartphone.svg">
          </div>
          <div class="form-group">
            <label class="form-label" for="ap-desc">Texnik tavsif</label>
            <textarea id="ap-desc" class="form-control" rows="2">Rasmiy kafolat va to‘liq komplektatsiya.</textarea>
          </div>
          <div class="flex-gap">
            <button type="submit" class="btn btn-primary">Moderatsiyaga yuborish (Pending Review)</button>
            <button type="button" id="ap-draft-btn" class="btn btn-outline">Qoralama sifatida saqlash (Draft)</button>
          </div>
        </form>
      `;
      const submitProd = async (isSubmit) => {
        try {
          const res = await apiFetch("/api/v1/sellers/my-products/", {
            method: "POST",
            body: JSON.stringify({
              title: document.getElementById("ap-title").value,
              sku: document.getElementById("ap-sku").value,
              category_id: document.getElementById("ap-cat").value,
              brand_name: document.getElementById("ap-brand").value,
              cash_price: Number(document.getElementById("ap-price").value),
              stock_quantity: Number(document.getElementById("ap-stock").value),
              image_url: document.getElementById("ap-img").value,
              description: document.getElementById("ap-desc").value,
              submit: isSubmit,
            }),
          });
          showToast(`Mahsulot yaratildi! Holat: ${res.status}`, "success");
          activeTab = "products";
          loadTab();
        } catch (err) {
          showToast(err.message, "error");
        }
      };
      document.getElementById("add-prod-form").onsubmit = (e) => {
        e.preventDefault();
        submitProd(true);
      };
      document.getElementById("ap-draft-btn").onclick = () => submitProd(false);
    } else if (activeTab === "import") {
      const batches = await apiFetch("/api/v1/imports/batches/");
      panel.innerHTML = `
        <div class="flex-between mb-3">
          <div>
            <h2 style="margin:0;">Excel (.xlsx) / CSV Import Markazi (6.1)</h2>
            <p class="text-xs text-muted" style="margin:0;">Formula injection (=,+,-,@) himoyasi, dublikat SKU nazorati, idempotency key va xato hisoboti bilan.</p>
          </div>
          <a href="/api/v1/imports/sample-template/" class="btn btn-outline btn-sm">📥 Namuna .XLSX yuklab olish</a>
        </div>

        <form id="imp-upload-form" class="card mb-4" style="background:var(--navy-50);">
          <div class="flex-gap">
            <input id="imp-file" type="file" accept=".xlsx,.csv" class="form-control" style="max-width:360px;" required>
            <button type="submit" class="btn btn-primary">1. Yuklash va Oldindan ko‘rish (Preview)</button>
          </div>
        </form>

        <div id="imp-preview-area" class="mb-4"></div>

        <h3>Oxirgi importlar tarixi</h3>
        <div class="table-wrap mt-2">
          <table class="data-table tabular">
            <thead><tr><th>Fayl</th><th>Holat</th><th>Jami</th><th>Yangi</th><th>Yangilash</th><th>Dublikat</th><th>Xato</th><th>Hisobot</th></tr></thead>
            <tbody>
              ${batches.results
                .map(
                  (b) => `<tr>
                    <td>${esc(b.file_name)}</td>
                    <td>${statusBadge(b.status)}</td>
                    <td>${b.total_rows}</td>
                    <td>${b.new_count}</td>
                    <td>${b.update_count}</td>
                    <td>${b.duplicate_count}</td>
                    <td>${b.error_count}</td>
                    <td><a href="/api/v1/imports/${esc(b.id)}/error-report/" class="btn btn-outline btn-sm">CSV</a></td>
                  </tr>`
                )
                .join("") || "<tr><td colspan='8'>Import tarixi bo‘sh</td></tr>"}
            </tbody>
          </table>
        </div>
      `;

      document.getElementById("imp-upload-form").onsubmit = async (e) => {
        e.preventDefault();
        const file = document.getElementById("imp-file").files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append("file", file);
        fd.append("idempotency_key", genIdempotencyKey("imp"));
        try {
          const prev = await apiFetch("/api/v1/imports/upload/", { method: "POST", body: fd });
          const area = document.getElementById("imp-preview-area");
          area.innerHTML = `
            <div class="card card-elevated" style="border-color:var(--gold-500);">
              <div class="flex-between mb-2">
                <h4>Preview natijasi (Batch: ${esc(prev.batch_id.slice(0, 8))})</h4>
                <div class="flex-gap">
                  <span class="badge badge-success">Yangi: ${prev.summary.new}</span>
                  <span class="badge badge-info">Yangilanadi: ${prev.summary.update}</span>
                  <span class="badge badge-warning">Dublikat: ${prev.summary.duplicate}</span>
                  <span class="badge badge-danger">Xato: ${prev.summary.error}</span>
                </div>
              </div>
              <div class="table-wrap mb-3">
                <table class="data-table text-sm">
                  <thead><tr><th>Satr</th><th>SKU</th><th>Nomi</th><th>Narx</th><th>Holat</th><th>Xato izohi</th></tr></thead>
                  <tbody>
                    ${prev.rows
                      .map(
                        (r) => `<tr><td>${r.row}</td><td>${esc(r.sku)}</td><td>${esc(r.title)}</td><td class="tabular">${fmtUzs(r.cash_price)}</td><td>${statusBadge(r.status)}</td><td class="form-error">${esc(r.error)}</td></tr>`
                      )
                      .join("")}
                  </tbody>
                </table>
              </div>
              <div class="flex-gap">
                <button id="imp-confirm-btn" class="btn btn-success">✓ Valid satrlarni moderatsiyaga yuborish</button>
                <a href="/api/v1/imports/${esc(prev.batch_id)}/error-report/" class="btn btn-outline">Xato hisobotini yuklab olish (CSV)</a>
              </div>
            </div>
          `;
          document.getElementById("imp-confirm-btn").onclick = async () => {
            const res = await apiFetch(`/api/v1/imports/${prev.batch_id}/confirm/`, { method: "POST" });
            showToast(`${res.processed_count} ta mahsulot moderatsiya navbatiga qo‘shildi!`, "success");
            loadTab();
          };
        } catch (err) {
          showToast(err.message, "error");
        }
      };
    } else if (activeTab === "integrations") {
      const intData = await apiFetch("/api/v1/imports/integrations/");
      panel.innerHTML = `
        <h2 class="mb-2">Tashqi katalog API integratsiyasi (6.2 — SSRF &amp; Secret Vault)</h2>
        <p class="text-xs text-muted mb-3">API tokenlar faqat shifrlangan vaultda saqlanadi va frontendga qaytarilmaydi; ichki tarmoq IP manzillari bloklanadi.</p>
        <form id="ext-add-form" class="card mb-4" style="background:var(--bg-subtle);">
          <div class="grid-3">
            <div class="form-group">
              <label class="form-label" for="ex-name">Manba nomi</label>
              <input id="ex-name" class="form-control" value="1C / MoySklad ERP">
            </div>
            <div class="form-group">
              <label class="form-label" for="ex-url">Allowlisted API URL</label>
              <input id="ex-url" class="form-control" value="https://api.sandbox-erp.uz/v1/catalog">
            </div>
            <div class="form-group">
              <label class="form-label" for="ex-key">API Key (shifrlanadi)</label>
              <input id="ex-key" type="password" class="form-control" value="sk_live_sandbox_123456">
            </div>
          </div>
          <button type="submit" class="btn btn-primary btn-sm">Integratsiya qo‘shish</button>
        </form>

        ${intData.results
          .map(
            (i) => `
          <div class="card mb-2">
            <div class="flex-between">
              <div>
                <strong>${esc(i.provider_name)}</strong> (${esc(i.endpoint_url)})
                <div class="text-xs text-muted">Kalit (vault): ${esc(i.masked_api_key)} • Jadval: ${esc(i.sync_schedule)}</div>
              </div>
              <button class="btn btn-outline btn-sm" data-sync-int="${esc(i.id)}">🔄 Manual Sync</button>
            </div>
          </div>`
          )
          .join("") || `<p class="text-muted">Ulangan tashqi API manbalari yo‘q.</p>`}
      `;
      document.getElementById("ext-add-form").onsubmit = async (e) => {
        e.preventDefault();
        try {
          await apiFetch("/api/v1/imports/integrations/", {
            method: "POST",
            body: JSON.stringify({
              provider_name: document.getElementById("ex-name").value,
              endpoint_url: document.getElementById("ex-url").value,
              api_key: document.getElementById("ex-key").value,
            }),
          });
          showToast("Tashqi API ulanishi xavfsiz saqlandi.", "success");
          loadTab();
        } catch (err) {
          showToast(err.message, "error");
        }
      };
      panel.querySelectorAll("[data-sync-int]").forEach((btn) => {
        btn.onclick = async () => {
          const res = await apiFetch(`/api/v1/imports/integrations/${btn.dataset.syncInt}/sync/`, { method: "POST" });
          showToast(`Sync yakunlandi: ${res.items_processed} ta qayta ishlandi, ${res.queued_moderation} ta moderatsiyaga tushdi.`, "success");
          loadTab();
        };
      });
    } else if (activeTab === "inventory") {
      const inv = await apiFetch("/api/v1/inventory/stock/");
      panel.innerHTML = `
        <h2 class="mb-3">Ombor qoldig‘i va harakatlar (7-bo‘lim)</h2>
        <div class="table-wrap">
          <table class="data-table tabular">
            <thead><tr><th>SKU</th><th>Mahsulot</th><th>Jami</th><th>Band</th><th>Mavjud</th><th>Holat</th><th>Kirim/Tuzatish</th></tr></thead>
            <tbody>
              ${inv.results
                .map(
                  (s) => `
                <tr>
                  <td>${esc(s.sku)}</td>
                  <td>${esc(s.product_title)}</td>
                  <td>${s.quantity}</td>
                  <td>${s.reserved}</td>
                  <td class="fw-bold">${s.available}</td>
                  <td>${s.is_low_stock ? `<span class="badge badge-danger">⚠ Kam qoldi</span>` : `<span class="badge badge-success">✓ Yetarli</span>`}</td>
                  <td><button class="btn btn-outline btn-sm" data-add-stock="${esc(s.stock_id)}">+5 kirim</button></td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      `;
      panel.querySelectorAll("[data-add-stock]").forEach((btn) => {
        btn.onclick = async () => {
          await apiFetch("/api/v1/inventory/stock/", {
            method: "POST",
            body: JSON.stringify({ stock_id: btn.dataset.addStock, delta: 5, note: "Sotuvchi ombor kirimi (+5)" }),
          });
          showToast("Ombor qoldig‘i +5 ga yangilandi.", "success");
          loadTab();
        };
      });
    } else if (activeTab === "orders" || activeTab === "returns") {
      const ordData = await apiFetch("/api/v1/commerce/orders/");
      const subs = ordData.seller_orders || [];
      if (activeTab === "orders") {
        panel.innerHTML = `
          <h2 class="mb-3">Sotuvchi sub-buyurtmalari va Topshirish OTP</h2>
          ${subs
            .map(
              (so) => `
            <div class="card mb-3" style="background:var(--bg-subtle);">
              <div class="flex-between mb-2">
                <div><strong>${esc(so.sub_order_number)}</strong> • Mijoz: ${esc(so.customer_name)} • Tracking: ${esc(so.tracking_number)}</div>
                ${statusBadge(so.status)}
              </div>
              <div class="text-sm tabular mb-2">
                Summa: <strong>${fmtUzs(so.subtotal_amount)}</strong> • Komissiya: ${fmtUzs(so.commission_amount)} • Holdback: ${fmtUzs(so.holdback_amount)} • <strong>Sof payout: ${fmtUzs(so.net_seller_payout)}</strong>
              </div>
              <div class="flex-gap">
                ${so.status === "Pending" || so.status === "Confirmed" ? `<button class="btn btn-primary btn-sm" data-so-next="${esc(so.id)}" data-st="Processing">Tayyorlash (Processing)</button>` : ""}
                ${so.status === "Processing" || so.status === "Confirmed" ? `<button class="btn btn-gold btn-sm" data-so-next="${esc(so.id)}" data-st="Shipped">Jo‘natildi (Shipped)</button>` : ""}
                ${so.status === "Shipped" ? `<button class="btn btn-success btn-sm" data-so-deliver="${esc(so.id)}">OTP bilan topshirildi (Delivered)</button>` : ""}
              </div>
            </div>`
            )
            .join("") || `<p class="text-muted">Buyurtmalar yo‘q.</p>`}
        `;
        panel.querySelectorAll("[data-so-next]").forEach((btn) => {
          btn.onclick = async () => {
            await apiFetch(`/api/v1/commerce/seller-orders/${btn.dataset.soNext}/status/`, {
              method: "POST",
              body: JSON.stringify({ status: btn.dataset.st }),
            });
            showToast(`Holat o‘zgardi: ${btn.dataset.st}`, "success");
            loadTab();
          };
        });
        panel.querySelectorAll("[data-so-deliver]").forEach((btn) => {
          btn.onclick = () => {
            openModal(
              "Mijozning topshirish OTP-kodini tasdiqlang (28.4 / 31.1)",
              `
                <div class="form-group">
                  <label class="form-label" for="del-otp-in">6 xonali topshirish OTP-kodi</label>
                  <input id="del-otp-in" class="form-control tabular" placeholder="Mijoz kabinetidagi kod">
                </div>
                <button id="del-otp-go" class="btn btn-success" style="width:100%;">Topshirishni tasdiqlash</button>
              `,
              () => {
                document.getElementById("del-otp-go").onclick = async () => {
                  try {
                    await apiFetch(`/api/v1/commerce/seller-orders/${btn.dataset.soDeliver}/status/`, {
                      method: "POST",
                      body: JSON.stringify({ status: "Delivered", delivery_otp: document.getElementById("del-otp-in").value }),
                    });
                    closeModal();
                    showToast("Topshirish OTP tasdiqlandi! Shartnoma va hisob-kitob faollashdi.", "success");
                    loadTab();
                  } catch (err) {
                    showToast(err.message, "error");
                  }
                };
              }
            );
          };
        });
      } else {
        const withRet = subs.filter((s) => s.returns.length);
        panel.innerHTML = `
          <h2 class="mb-3">Qaytarish so‘rovlari</h2>
          ${withRet
            .map((so) =>
              so.returns
                .map(
                  (r) => `
                <div class="card mb-2">
                  <div class="flex-between"><strong>${esc(so.sub_order_number)} (${esc(r.scope)})</strong> ${statusBadge(r.status)}</div>
                  <p class="text-sm mt-1">Sabab: ${esc(r.reason)}</p>
                  ${
                    r.status === "PENDING"
                      ? `<div class="flex-gap mt-2">
                           <button class="btn btn-success btn-sm" data-ret-dec="${esc(r.id)}" data-d="APPROVED">Tasdiqlash (Refund)</button>
                           <button class="btn btn-danger btn-sm" data-ret-dec="${esc(r.id)}" data-d="REJECTED">Rad etish</button>
                         </div>`
                      : ""
                  }
                </div>`
                )
                .join("")
            )
            .join("") || `<p class="text-muted">Faol qaytarish so‘rovlari yo‘q.</p>`}
        `;
        panel.querySelectorAll("[data-ret-dec]").forEach((btn) => {
          btn.onclick = async () => {
            await apiFetch(`/api/v1/commerce/returns/${btn.dataset.retDec}/decide/`, {
              method: "POST",
              body: JSON.stringify({ decision: btn.dataset.d, decision_note: "Sotuvchi ko‘rib chiqdi" }),
            });
            showToast("Qaytarish qarori saqlandi.", "success");
            loadTab();
          };
        });
      }
    } else if (activeTab === "profile") {
      panel.innerHTML = `
        <h2 class="mb-3">Do‘kon profili va Xodimlar RBAC</h2>
        <div class="grid-2">
          <form id="store-prof-form" class="card" style="background:var(--bg-subtle);">
            <h4>Profil sozlamalari</h4>
            <div class="form-group">
              <label class="form-label" for="sp-name">Ommaviy nomi</label>
              <input id="sp-name" class="form-control" value="${esc(cab.store.public_name)}" ${!cab.is_owner ? "disabled" : ""}>
            </div>
            <div class="form-group">
              <label class="form-label" for="sp-hours">Ish vaqti</label>
              <input id="sp-hours" class="form-control" value="${esc(cab.store.working_hours)}" ${!cab.is_owner ? "disabled" : ""}>
            </div>
            <div class="form-group">
              <label class="form-label" for="sp-ret">Qaytarish siyosati</label>
              <textarea id="sp-ret" class="form-control" rows="2" ${!cab.is_owner ? "disabled" : ""}>${esc(cab.store.return_policy)}</textarea>
            </div>
            ${cab.is_owner ? `<button type="submit" class="btn btn-primary btn-sm">Profilni saqlash</button>` : `<span class="badge badge-warning">Faqat Seller Owner tahrirlaydi (2-bo‘lim)</span>`}
          </form>

          <div class="card" style="background:var(--bg-subtle);">
            <h4>Do‘kon xodimlari (${cab.staff.length})</h4>
            ${cab.staff.map((st) => `<div class="text-sm mb-2"><strong>${esc(st.full_name)}</strong> (${esc(st.position_title)})<br><span class="text-xs text-muted">Bo‘limlar: ${esc(st.allowed_sections.join(", "))}</span></div>`).join("")}
            ${
              cab.is_owner
                ? `<form id="staff-add-form" class="mt-3" style="border-top:1px solid var(--border-color);padding-top:10px;">
                     <div class="form-group"><input id="ss-name" class="form-control" placeholder="Xodim F.I.Sh" required></div>
                     <div class="form-group"><input id="ss-phone" class="form-control" placeholder="+99890..." required></div>
                     <button type="submit" class="btn btn-outline btn-sm">+ Seller Staff qo‘shish</button>
                   </form>`
                : ""
            }
          </div>
        </div>
      `;
      document.getElementById("store-prof-form")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await apiFetch("/api/v1/sellers/my-store/", {
            method: "PATCH",
            body: JSON.stringify({
              public_name: document.getElementById("sp-name").value,
              working_hours: document.getElementById("sp-hours").value,
              return_policy: document.getElementById("sp-ret").value,
            }),
          });
          showToast("Do‘kon profili saqlandi.", "success");
        } catch (err) {
          showToast(err.message, "error");
        }
      });
      document.getElementById("staff-add-form")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await apiFetch("/api/v1/sellers/my-store/staff/", {
            method: "POST",
            body: JSON.stringify({
              full_name: document.getElementById("ss-name").value,
              phone: document.getElementById("ss-phone").value,
            }),
          });
          showToast("Xodim qo‘shildi!", "success");
          loadTab();
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    } else {
      panel.innerHTML = `
        <h2>Sotuvchi qoidalari va Onboarding yo‘riqnomasi</h2>
        <ul>
          <li>Har bir yangi yoki muhim o‘zgargan mahsulot <strong>Moderatsiya</strong>dan o‘tgandan keyin katalogda ko‘rinadi (5.2).</li>
          <li>Buyurtmalar mijozga topshirilganda <strong>OTP-kod</strong> bilan tasdiqlanadi; holdback qaytarish muddatidan keyin yechiladi (28.7).</li>
          <li>Barcha import fayllari formula injection va dublikat SKU tekshiruvidan o‘tkaziladi.</li>
        </ul>
      `;
    }
  };

  loadTab();
}
