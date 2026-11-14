/* Home, Smart Catalog, Product Detail, Interactive Nasiya Calculator & Compare Views */
import { apiFetch, esc, fmtDate, fmtUzs, renderProductCard, showToast, wireProductCardActions } from "../api.js";
import { AppState } from "../i18n.js";

export async function renderHomeView(container, reloadCartBadge) {
  const data = await apiFetch("/api/v1/catalog/home/");
  const b0 = data.banners[0] || {
    title: "ZARVON Nasiya: 12 oygacha shaffof muddatli to‘lov",
    subtitle: "Yashirin komissiyasiz, 250 BHM chegarasi ichida.",
    badge_text: "SANDBOX DEMO",
    cta_label: "Katalogga o‘tish",
  };
  const b1 = data.banners[1] || {
    title: "11.11 Aksiyasi",
    subtitle: "Chegirmadagi texnikalar",
    badge_text: "KAMPANIYA",
  };

  container.innerHTML = `
    <section class="hero-grid" aria-label="Kampaniya bannerlari">
      <div class="hero-card">
        <span class="hero-badge">${esc(b0.badge_text)}</span>
        <h1>${esc(b0.title)}</h1>
        <p style="max-width:600px;opacity:0.92;">${esc(b0.subtitle)}</p>
        <div class="flex-gap mt-4">
          <a href="#catalog" class="btn btn-gold">${esc(b0.cta_label || "Katalogni ochish")} →</a>
          <a href="#calculator" class="btn btn-outline" style="background:rgba(255,255,255,0.12);color:#fff;border-color:rgba(255,255,255,0.35);">
            Nasiya kalkulyatori
          </a>
        </div>
        <div class="flex-gap mt-4 text-xs" style="opacity:0.88;">
          <span>✓ Muddat ≤ ${data.compliance.max_months} oy</span>
          <span>✓ Maksimal xarid: ${fmtUzs(data.compliance.max_bhm_limit)} (250 BHM)</span>
          <span>✓ Erta to‘lov: 0% jarima</span>
        </div>
      </div>

      <div class="hero-card-gold flex" style="flex-direction:column;justify-content:space-between;">
        <div>
          <span class="badge badge-navy">${esc(b1.badge_text)}</span>
          <h2 class="mt-2">${esc(b1.title)}</h2>
          <p class="text-sm">${esc(b1.subtitle)}</p>
        </div>
        <div class="mt-3">
          <div class="text-xs fw-bold mb-2">Ommabop qidiruvlar:</div>
          <div class="flex-gap">
            ${data.popular_queries
              .map((q) => `<button class="btn btn-outline btn-sm" data-quick-search="${esc(q)}">${esc(q)}</button>`)
              .join("")}
          </div>
        </div>
      </div>
    </section>

    <!-- Categories -->
    <section class="mt-6">
      <div class="flex-between mb-3">
        <h2>Kategoriyalar</h2>
        <a href="#catalog" class="text-sm fw-bold">Barchasi →</a>
      </div>
      <div class="cat-strip">
        ${data.categories
          .map(
            (c) => `
          <div class="cat-tile ${c.installment_allowed ? "" : "prohibited"}" data-cat-slug="${esc(c.slug)}">
            <div class="flex-between">
              <strong class="text-sm">${esc(c.name)}</strong>
              ${
                c.installment_allowed
                  ? `<span class="badge badge-success">Nasiya</span>`
                  : `<span class="badge badge-danger">Taqiqlangan</span>`
              }
            </div>
            <span class="text-xs text-muted">${
              c.installment_allowed ? "3–12 oy muddatli to‘lov" : esc(c.prohibition_note || "Faqat naqd")
            }</span>
          </div>`
          )
          .join("")}
      </div>
    </section>

    <!-- "Oyiga ... so'mdan" Curated Picks -->
    <section class="mt-6">
      <div class="flex-between mb-3">
        <div>
          <h2>“Oyiga … so‘mdan” — Shaffof nasiya tanlovi</h2>
          <p class="text-sm text-muted" style="margin:0;">Har bir kartada muddat, jami to‘lov summasi va indikativ belgi ochiq ko‘rsatiladi (28.3).</p>
        </div>
        <a href="#catalog?installment_only=true" class="btn btn-outline btn-sm">Barcha nasiya tovarlari</a>
      </div>
      <div class="grid-4">
        ${data.installment_picks.map(renderProductCard).join("")}
      </div>
    </section>

    <!-- Discounts -->
    ${
      data.discounts.length
        ? `<section class="mt-6">
             <div class="flex-between mb-3">
               <h2>Chegirmalar va kampaniyalar</h2>
               <span class="badge badge-gold">Asl eski narx tarixi bilan</span>
             </div>
             <div class="grid-4">
               ${data.discounts.map(renderProductCard).join("")}
             </div>
           </section>`
        : ""
    }

    <!-- New / Popular Arrivals -->
    <section class="mt-6">
      <div class="flex-between mb-3">
        <h2>Ommabop va yangi mahsulotlar</h2>
        <a href="#catalog" class="text-sm fw-bold">Katalogga o‘tish →</a>
      </div>
      <div class="grid-4">
        ${data.new_arrivals.map(renderProductCard).join("")}
      </div>
    </section>

    <!-- Consumer Protection & Trust Block (Section 30.3 & 27.1) -->
    <section class="mt-6 card" style="border-left:5px solid var(--gold-500);">
      <h2>ZARVON Ishonch va Mijoz Himoyasi Kafolatlari</h2>
      <div class="grid-4 mt-3">
        <div>
          <h4>🛡 12 oy &amp; 250 BHM Chegarasi</h4>
          <p class="text-sm text-secondary">Muddatli to‘lov shartnomalari 12 oydan va 250 BHMdan oshmaydi. Yillik ustama+jarima 50% bilan cheklangan.</p>
        </div>
        <div>
          <h4>💳 0% Erta To‘lov Jarimasi</h4>
          <p class="text-sm text-secondary">Istalgan vaqtda qisman yoki to‘liq muddatidan oldin yopish mumkin — qo‘shimcha komissiya olinmaydi.</p>
        </div>
        <div>
          <h4>📦 OTP-kod bilan Topshirish</h4>
          <p class="text-sm text-secondary">Tovar kuryer yoki punktda shaxsiy OTP kod bilan topshirilgandan keyingina to‘lov jadvali faollashadi.</p>
        </div>
        <div>
          <h4>⚖ Tez Qaytarish va Apellyatsiya</h4>
          <p class="text-sm text-secondary">Shikoyatlar va skoring qarorlariga kabinetdan to‘g‘ridan-to‘g‘ri apellyatsiya yuborish huquqi.</p>
        </div>
      </div>
    </section>
  `;

  container.querySelectorAll("[data-cat-slug]").forEach((el) => {
    el.addEventListener("click", () => {
      location.hash = `#catalog?category=${encodeURIComponent(el.dataset.catSlug)}`;
    });
  });
  container.querySelectorAll("[data-quick-search]").forEach((btn) => {
    btn.addEventListener("click", () => {
      location.hash = `#catalog?q=${encodeURIComponent(btn.dataset.quickSearch)}`;
    });
  });
  wireProductCardActions(container, reloadCartBadge);
}

export async function renderCatalogView(container, queryStr, reloadCartBadge) {
  const params = new URLSearchParams(queryStr || "");
  const homeMeta = await apiFetch("/api/v1/catalog/home/");

  const q = params.get("q") || "";
  const category = params.get("category") || "";
  const brand = params.get("brand") || "";
  const installmentOnly = params.get("installment_only") || "false";
  const maxMonthly = params.get("max_monthly") || "";
  const months = params.get("months") || "12";
  const sort = params.get("sort") || "popular";

  const apiUrl = `/api/v1/catalog/products/?${new URLSearchParams({
    q,
    category,
    brand,
    installment_only: installmentOnly,
    max_monthly: maxMonthly,
    months,
    sort,
  }).toString()}`;
  const catalogData = await apiFetch(apiUrl);

  container.innerHTML = `
    <div class="flex-between mb-4">
      <div>
        <div class="text-xs text-muted"><a href="#home">Bosh sahifa</a> / Katalog</div>
        <h1 style="margin:4px 0 0;">Mahsulotlar katalogi (${catalogData.count})</h1>
        ${q ? `<p class="text-sm text-secondary">Aqlli qidiruv so‘rovi: <strong>"${esc(q)}"</strong> (lotin/kirill/oʻ/gʻ va xato yozuvga mos)</p>` : ""}
      </div>
      <div class="flex-gap">
        <label class="text-sm fw-bold" for="cat-sort">Saralash:</label>
        <select id="cat-sort" class="select-compact">
          <option value="popular" ${sort === "popular" ? "selected" : ""}>Ommabop</option>
          <option value="price_asc" ${sort === "price_asc" ? "selected" : ""}>Arzonroqdan</option>
          <option value="price_desc" ${sort === "price_desc" ? "selected" : ""}>Qimmatroqdan</option>
          <option value="monthly_asc" ${sort === "monthly_asc" ? "selected" : ""}>Oylik to‘lov bo‘yicha</option>
        </select>
      </div>
    </div>

    <div class="catalog-layout">
      <aside class="card" aria-label="Katalog filtrlari">
        <h3>Filtrlar</h3>
        <form id="catalog-filter-form">
          <div class="form-group">
            <label class="form-label" for="f-q">Qidiruv</label>
            <input id="f-q" class="form-control" value="${esc(q)}" placeholder="Masalan: айфон, gʻilof, LG">
          </div>
          <div class="form-group">
            <label class="form-label" for="f-cat">Kategoriya</label>
            <select id="f-cat" class="form-control">
              <option value="">Barcha kategoriyalar</option>
              ${homeMeta.categories
                .map((c) => `<option value="${esc(c.slug)}" ${c.slug === category ? "selected" : ""}>${esc(c.name)}</option>`)
                .join("")}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" for="f-brand">Brend</label>
            <select id="f-brand" class="form-control">
              <option value="">Barcha brendlar</option>
              ${homeMeta.brands
                .map((b) => `<option value="${esc(b.slug)}" ${b.slug === brand ? "selected" : ""}>${esc(b.name)}</option>`)
                .join("")}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" for="f-months">Nasiya muddati (indikativ)</label>
            <select id="f-months" class="form-control">
              ${[3, 6, 9, 12]
                .map((m) => `<option value="${m}" ${String(m) === String(months) ? "selected" : ""}>${m} oy</option>`)
                .join("")}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" for="f-max-monthly">Oyiga X so‘mgacha (29.2)</label>
            <input id="f-max-monthly" type="number" class="form-control" value="${esc(maxMonthly)}" placeholder="Masalan: 900000">
          </div>
          <div class="form-group">
            <label class="flex-gap" style="cursor:pointer;">
              <input id="f-inst-only" type="checkbox" ${installmentOnly === "true" ? "checked" : ""}>
              <span class="text-sm fw-bold">Faqat nasiyaga mos mahsulotlar</span>
            </label>
          </div>
          <div class="flex-gap">
            <button type="submit" class="btn btn-primary" style="flex:1;">Qo‘llash</button>
            <button type="button" id="f-reset" class="btn btn-outline">Tozalash</button>
          </div>
        </form>
      </aside>

      <section>
        ${
          catalogData.results.length
            ? `<div class="grid-3">${catalogData.results.map(renderProductCard).join("")}</div>`
            : `<div class="state-box">
                 <h3>Mahsulotlar topilmadi</h3>
                 <p class="text-muted">Qidiruv so‘rovini yumshating yoki filtrlarni tozalab ko‘ring.</p>
                 <a href="#catalog" class="btn btn-primary mt-2">Barcha mahsulotlar</a>
               </div>`
        }
      </section>
    </div>
  `;

  const applyFilters = () => {
    const np = new URLSearchParams();
    const nq = document.getElementById("f-q").value.trim();
    const ncat = document.getElementById("f-cat").value;
    const nbrand = document.getElementById("f-brand").value;
    const nmonths = document.getElementById("f-months").value;
    const nmax = document.getElementById("f-max-monthly").value.trim();
    const ninst = document.getElementById("f-inst-only").checked ? "true" : "false";
    const nsort = document.getElementById("cat-sort").value;
    if (nq) np.set("q", nq);
    if (ncat) np.set("category", ncat);
    if (nbrand) np.set("brand", nbrand);
    if (nmonths) np.set("months", nmonths);
    if (nmax) np.set("max_monthly", nmax);
    if (ninst === "true") np.set("installment_only", "true");
    if (nsort) np.set("sort", nsort);
    location.hash = `#catalog?${np.toString()}`;
  };

  document.getElementById("catalog-filter-form").addEventListener("submit", (e) => {
    e.preventDefault();
    applyFilters();
  });
  document.getElementById("cat-sort").addEventListener("change", applyFilters);
  document.getElementById("f-reset").addEventListener("click", () => {
    location.hash = "#catalog";
  });

  wireProductCardActions(container, reloadCartBadge);
}

export async function renderProductDetailView(container, slug, reloadCartBadge) {
  const p = await apiFetch(`/api/v1/catalog/products/${encodeURIComponent(slug)}/`);

  const specsRows = Object.entries(p.specs || {})
    .map(([k, v]) => `<tr><td class="text-muted">${esc(k)}</td><td class="fw-bold">${esc(v)}</td></tr>`)
    .join("");

  container.innerHTML = `
    <div class="text-xs text-muted mb-3">
      <a href="#home">Bosh sahifa</a> / <a href="#catalog?category=${esc(p.category_slug)}">${esc(p.category_name)}</a> / ${esc(p.title)}
    </div>

    <div class="grid-2" style="align-items:start;">
      <!-- Left Gallery & Specs -->
      <div class="card">
        <div style="background:var(--bg-subtle);border-radius:var(--radius-md);padding:24px;display:flex;justify-content:center;">
          <img src="${esc(p.primary_image || "/static/icons/product-default.svg")}" alt="${esc(p.title)}" style="max-height:320px;">
        </div>
        <div class="mt-4">
          <h3>Texnik xususiyatlar</h3>
          <div class="table-wrap">
            <table class="data-table">
              <tbody>
                <tr><td class="text-muted">SKU</td><td class="fw-bold tabular">${esc(p.sku)}</td></tr>
                <tr><td class="text-muted">Brend</td><td class="fw-bold">${esc(p.brand_name || "—")}</td></tr>
                <tr><td class="text-muted">Kafolat</td><td class="fw-bold">${p.warranty_months} oy</td></tr>
                <tr><td class="text-muted">Qaytarish</td><td class="fw-bold">${p.return_days} kun</td></tr>
                ${specsRows}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Right Pricing, Compliance Nasiya Calculator & Purchase -->
      <div class="card card-elevated">
        <div class="flex-between">
          <span class="badge badge-navy">🏪 ${esc(p.store_name)} (★ ${p.store_rating})</span>
          <span class="badge ${p.stock_available > 0 ? "badge-success" : "badge-danger"}">
            ${p.stock_available > 0 ? `✓ Omborda ${p.stock_available} dona` : "Tugagan"}
          </span>
        </div>

        <h1 class="mt-3" style="font-size:1.55rem;">${esc(p.title)}</h1>
        <p class="text-secondary text-sm">${esc(p.description)}</p>

        <div class="price-row tabular mt-3">
          <span style="font-size:1.85rem;font-weight:800;">${fmtUzs(p.cash_price)}</span>
          ${p.old_price ? `<span class="old-price">${fmtUzs(p.old_price)}</span>` : ""}
          ${p.discount_pct > 0 ? `<span class="badge badge-gold">-${p.discount_pct}% chegirma</span>` : ""}
        </div>

        <div class="mt-4 card" style="background:var(--navy-50);">
          <div class="flex-between mb-2">
            <h3 style="margin:0;">Nasiya (Muddatli to‘lov) kalkulyatori</h3>
            <span class="badge badge-gold">Indikativ • Sandbox</span>
          </div>

          ${
            p.installment_eligible
              ? `
            <div class="flex-gap mb-3" id="prod-term-tabs">
              ${[3, 6, 9, 12]
                .map(
                  (m) =>
                    `<button class="btn btn-sm ${m === 12 ? "btn-primary" : "btn-outline"}" data-calc-months="${m}">${m} oy</button>`
                )
                .join("")}
            </div>
            <div class="form-group">
              <label class="form-label" for="prod-down-pay">Boshlang‘ich to‘lov (ixtiyoriy, so‘m)</label>
              <input id="prod-down-pay" type="number" class="form-control tabular" value="0" min="0" step="100000">
            </div>
            <div id="prod-calc-output" class="mt-2"></div>
          `
              : `
            <div class="badge badge-danger">⚠ Qonuniy cheklov (27.1): Ushbu toifa yoki narx (>250 BHM) uchun nasiya taqiqlangan. Faqat naqd/karta orqali xarid mumkin.</div>
          `
          }
        </div>

        <div class="flex-gap mt-4">
          <button id="btn-prod-add-cart" class="btn btn-primary" style="flex:1;" ${p.stock_available <= 0 ? "disabled" : ""}>
            🛒 Savatga qo‘shish
          </button>
          <button id="btn-prod-buy-now" class="btn btn-gold" style="flex:1;" ${p.stock_available <= 0 ? "disabled" : ""}>
            ⚡ Xarid / Kassa
          </button>
        </div>
        <div class="text-xs text-muted mt-3">
          🚚 Yetkazib berish: ${p.delivery_sla_days} ish kuni • Kuryer yoki yig‘ish punkti (OTP-kod bilan topshiriladi)
        </div>
      </div>
    </div>

    <!-- Verified Reviews -->
    <section class="mt-6 card">
      <div class="flex-between mb-3">
        <div>
          <h2>Tasdiqlangan xaridorlar sharhlari (${p.reviews.length})</h2>
          <p class="text-xs text-muted" style="margin:0;">Soxta reytingga qarshi himoya (29.2 / 31.1): faqat xarid qilgan va qabul qilgan mijoz sharh yoza oladi.</p>
        </div>
      </div>

      <div id="reviews-list" class="grid-2">
        ${
          p.reviews.length
            ? p.reviews
                .map(
                  (r) => `
                <div class="card" style="background:var(--bg-subtle);">
                  <div class="flex-between">
                    <strong>${esc(r.author)}</strong>
                    <span class="badge badge-success">✓ Tasdiqlangan xarid • ★ ${r.rating}/5</span>
                  </div>
                  <p class="text-sm mt-2">${esc(r.comment)}</p>
                  ${
                    r.seller_reply
                      ? `<div class="text-xs text-secondary mt-2" style="padding-left:10px;border-left:3px solid var(--gold-500);">
                           <strong>Sotuvchi javobi:</strong> ${esc(r.seller_reply)}
                         </div>`
                      : ""
                  }
                  <div class="text-xs text-muted mt-2">${fmtDate(r.created_at)}</div>
                </div>`
                )
                .join("")
            : `<p class="text-muted">Hali sharhlar yo‘q.</p>`
        }
      </div>

      ${
        AppState.authenticated
          ? `<form id="review-form" class="mt-4" style="border-top:1px solid var(--border-color);padding-top:14px;">
               <h4>Sharh qoldirish (faqat xarid qilganlar uchun)</h4>
               <div class="grid-2">
                 <div class="form-group">
                   <label class="form-label" for="rev-rating">Baho</label>
                   <select id="rev-rating" class="form-control">
                     <option value="5">5 ★ — A’lo</option>
                     <option value="4">4 ★ — Yaxshi</option>
                     <option value="3">3 ★ — O‘rtacha</option>
                     <option value="2">2 ★ — Past</option>
                     <option value="1">1 ★ — Qoniqarsiz</option>
                   </select>
                 </div>
                 <div class="form-group">
                   <label class="form-label" for="rev-comment">Fikringiz</label>
                   <input id="rev-comment" class="form-control" placeholder="Mahsulot sifati va yetkazish haqida...">
                 </div>
               </div>
               <button type="submit" class="btn btn-outline btn-sm">Sharh yuborish</button>
             </form>`
          : ""
      }
    </section>

    ${
      p.similar_products && p.similar_products.length
        ? `<section class="mt-6">
             <h2>O‘xshash mahsulotlar</h2>
             <div class="grid-4 mt-3">${p.similar_products.map(renderProductCard).join("")}</div>
           </section>`
        : ""
    }
  `;

  // Live Interactive Uzum-Style Month Pills + Transparent Nasiya Calculator
  let activeMonths = 12;
  const runCalc = async () => {
    const out = document.getElementById("prod-calc-output");
    if (!out) return;
    const downPay = Number(document.getElementById("prod-down-pay")?.value || 0);
    try {
      const [q, q3, q6, q9, q12] = await Promise.all([
        apiFetch("/api/v1/finance/calculator/", {
          method: "POST",
          body: JSON.stringify({
            price: p.cash_price,
            down_payment: downPay,
            months: activeMonths,
            category_installment_allowed: p.category_installment_allowed,
          }),
        }),
        ...[3, 6, 9, 12].map((m) =>
          apiFetch("/api/v1/finance/calculator/", {
            method: "POST",
            body: JSON.stringify({
              price: p.cash_price,
              down_payment: downPay,
              months: m,
              category_installment_allowed: p.category_installment_allowed,
            }),
          }).catch(() => null)
        ),
      ]);

      const byM = { 3: q3, 6: q6, 9: q9, 12: q12 };
      container.querySelectorAll("[data-calc-months]").forEach((btn) => {
        const m = Number(btn.dataset.calcMonths);
        const qm = byM[m];
        btn.className = m === activeMonths ? "month-pill-btn active" : "month-pill-btn";
        btn.innerHTML = qm
          ? `<strong>${m} oy</strong><small>${fmtUzs(qm.monthly_payment)}/oy</small>`
          : `<strong>${m} oy</strong>`;
      });

      out.innerHTML = `
        <div class="grid-2 tabular" style="gap:8px;">
          <div class="kpi-card">
            <div class="kpi-label">Oylik to‘lov (${q.months} oy)</div>
            <div class="kpi-value" style="color:var(--navy-700);">${fmtUzs(q.monthly_payment)}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Jami to‘lanadigan summa</div>
            <div class="kpi-value">${fmtUzs(q.total_payable)}</div>
          </div>
        </div>
        <div class="text-xs text-secondary mt-2 tabular">
          Asosiy summa: <strong>${fmtUzs(q.principal)}</strong> • Ustama: <strong>${fmtUzs(q.markup_amount)}</strong> •
          Komissiya: <strong>${fmtUzs(q.commission_amount)}</strong> • Yillik yuklama: <strong>${q.annualized_extra_pct}%</strong> (Chegara ≤ 50%)
        </div>
        <div class="flex-between mt-2">
          <span class="text-xs text-muted">${esc(q.transparency_notice)}</span>
          <a href="#customer/kyc" class="badge badge-navy">⚡ 1 daqiqada KATM + MIB limitini tekshirish →</a>
        </div>
        <div class="psp-trust-strip mt-2" style="padding:8px 10px;">
          <span class="text-xs fw-bold">Qulay to‘lov:</span>
          <span class="psp-chip psp-chip-payme">Payme</span>
          <span class="psp-chip psp-chip-click">Click</span>
          <span class="psp-chip psp-chip-uzum">Uzum Bank</span>
          <span class="psp-chip psp-chip-paynet">Paynet</span>
        </div>
      `;
    } catch (err) {
      out.innerHTML = `<div class="badge badge-danger">⚠ ${esc(err.message)}</div>`;
    }
  };

  if (p.installment_eligible) {
    const pillRow = container.querySelector("[data-calc-months]")?.parentElement;
    if (pillRow) pillRow.className = "month-pill-grid mb-2";
    runCalc();
    container.querySelectorAll("[data-calc-months]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeMonths = Number(btn.dataset.calcMonths);
        runCalc();
      });
    });
    document.getElementById("prod-down-pay")?.addEventListener("input", runCalc);
  }

  document.getElementById("btn-prod-add-cart")?.addEventListener("click", async () => {
    if (!AppState.authenticated) {
      document.getElementById("btn-role-switcher")?.click();
      return;
    }
    await apiFetch("/api/v1/commerce/cart/", {
      method: "POST",
      body: JSON.stringify({ product_id: p.id, quantity: 1 }),
    });
    showToast("Savatga qo‘shildi!", "success");
    reloadCartBadge();
  });

  document.getElementById("btn-prod-buy-now")?.addEventListener("click", async () => {
    if (!AppState.authenticated) {
      document.getElementById("btn-role-switcher")?.click();
      return;
    }
    await apiFetch("/api/v1/commerce/cart/", {
      method: "POST",
      body: JSON.stringify({ product_id: p.id, quantity: 1 }),
    });
    await reloadCartBadge();
    location.hash = "#checkout";
  });

  document.getElementById("review-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await apiFetch(`/api/v1/catalog/products/${p.id}/reviews/`, {
        method: "POST",
        body: JSON.stringify({
          rating: Number(document.getElementById("rev-rating").value),
          comment: document.getElementById("rev-comment").value,
        }),
      });
      showToast("Sharhingiz muvaffaqiyatli qo‘shildi!", "success");
      renderProductDetailView(container, slug, reloadCartBadge);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  wireProductCardActions(container, reloadCartBadge);
}

export async function renderCalculatorView(container) {
  const comp = await apiFetch("/api/v1/governance/compliance/");
  container.innerHTML = `
    <div class="grid-2" style="align-items:start;">
      <div class="card card-elevated">
        <span class="badge badge-gold">Compliance Guard • ${esc(comp.version_code)}</span>
        <h1 class="mt-2">Shaffof Nasiya Kalkulyatori</h1>
        <p class="text-sm text-secondary">
          2027-yil 1-yanvar qoidalariga muvofiq barcha hisob-kitoblar real vaqtda tekshiriladi:
          maksimal muddat ${comp.max_months} oy, maksimal qiymat ${comp.max_bhm_multiplier} BHM (${fmtUzs(comp.max_installment_uzs)}),
          yillik qo‘shimcha xarajat ≤ ${comp.max_annual_extra_pct}%, muddatidan oldin yopish komissiyasi ${comp.early_repayment_fee_pct}%.
        </p>

        <form id="standalone-calc-form" class="mt-3">
          <div class="form-group">
            <label class="form-label" for="sc-price">Mahsulot narxi (so‘m)</label>
            <input id="sc-price" type="number" class="form-control tabular" value="8500000" min="300000" step="100000">
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label class="form-label" for="sc-down">Boshlang‘ich to‘lov (so‘m)</label>
              <input id="sc-down" type="number" class="form-control tabular" value="500000" min="0" step="100000">
            </div>
            <div class="form-group">
              <label class="form-label" for="sc-months">Muddat (oy)</label>
              <select id="sc-months" class="form-control">
                <option value="3">3 oy</option>
                <option value="6">6 oy</option>
                <option value="9">9 oy</option>
                <option value="12" selected>12 oy</option>
                <option value="18">18 oy (Compliance Guard test!)</option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <label class="flex-gap" style="cursor:pointer;">
              <input id="sc-cat-ok" type="checkbox" checked>
              <span class="text-sm fw-bold">Nasiyaga ruxsat etilgan toifa (ko‘chmas mulk emas)</span>
            </label>
          </div>
          <button type="submit" class="btn btn-primary" style="width:100%;">Hisoblash va Tekshirish</button>
        </form>
      </div>

      <div id="sc-result" class="card">
        <h3>Hisob-kitob va to‘lov jadvali</h3>
        <p class="text-muted text-sm">Parametrlarni tanlang.</p>
      </div>
    </div>
  `;

  const calc = async () => {
    const resEl = document.getElementById("sc-result");
    try {
      const q = await apiFetch("/api/v1/finance/calculator/", {
        method: "POST",
        body: JSON.stringify({
          price: Number(document.getElementById("sc-price").value),
          down_payment: Number(document.getElementById("sc-down").value),
          months: Number(document.getElementById("sc-months").value),
          category_installment_allowed: document.getElementById("sc-cat-ok").checked,
        }),
      });
      resEl.innerHTML = `
        <div class="flex-between mb-3">
          <h3 style="margin:0;">Natija (${q.months} oy)</h3>
          <span class="badge badge-success">✓ Compliance Guard o‘tdi</span>
        </div>
        <div class="grid-2 tabular mb-3">
          <div class="kpi-card"><div class="kpi-label">Oylik to‘lov</div><div class="kpi-value">${fmtUzs(q.monthly_payment)}</div></div>
          <div class="kpi-card"><div class="kpi-label">Jami to‘lov (boshlang‘ichsiz)</div><div class="kpi-value">${fmtUzs(q.total_payable)}</div></div>
          <div class="kpi-card"><div class="kpi-label">Asosiy summa</div><div class="kpi-value">${fmtUzs(q.principal)}</div></div>
          <div class="kpi-card"><div class="kpi-label">Ustama + Komissiya (${q.annualized_extra_pct}%/yil)</div><div class="kpi-value">${fmtUzs(q.total_extra)}</div></div>
        </div>
        <div class="table-wrap" style="max-height:300px;overflow-y:auto;">
          <table class="data-table tabular">
            <thead><tr><th>#</th><th>To‘lov sanasi</th><th>Summa</th></tr></thead>
            <tbody>
              ${q.preview_schedule
                .map((row) => `<tr><td>${row.installment_no}-oy</td><td>${fmtDate(row.due_date)}</td><td class="fw-bold">${fmtUzs(row.amount)}</td></tr>`)
                .join("")}
            </tbody>
          </table>
        </div>
      `;
    } catch (err) {
      resEl.innerHTML = `
        <div class="state-box" style="border-color:var(--danger-fg);">
          <span class="badge badge-danger">⛔ Compliance Guard Blokladi</span>
          <h3 class="mt-2">${esc(err.message)}</h3>
          <p class="text-sm text-secondary">Bu tizimning qonunchilik chegaralarini avtomatik himoya qilish mexanizmi (28.3).</p>
        </div>
      `;
    }
  };

  document.getElementById("standalone-calc-form").addEventListener("submit", (e) => {
    e.preventDefault();
    calc();
  });
  calc();
}

export async function renderCompareView(container) {
  const ids = AppState.compareIds;
  if (!ids.length) {
    container.innerHTML = `
      <div class="state-box">
        <h2>Taqqoslash ro‘yxati bo‘sh</h2>
        <p class="text-muted">Katalogda 2–4 ta mahsulot kartasidagi ⚖ belgisini bosing.</p>
        <a href="#catalog" class="btn btn-primary mt-2">Katalogga o‘tish</a>
      </div>
    `;
    return;
  }
  const all = await apiFetch("/api/v1/catalog/products/");
  const selected = all.results.filter((p) => ids.includes(p.id));
  container.innerHTML = `
    <div class="flex-between mb-4">
      <h1>Mahsulotlarni taqqoslash (${selected.length}/4)</h1>
      <button id="btn-clear-compare" class="btn btn-outline btn-sm">Ro‘yxatni tozalash</button>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Ko‘rsatkich</th>
            ${selected.map((p) => `<th><a href="#product/${esc(p.slug)}">${esc(p.title)}</a></th>`).join("")}
          </tr>
        </thead>
        <tbody class="tabular">
          <tr><td class="fw-bold">Naqd narx</td>${selected.map((p) => `<td class="fw-bold">${fmtUzs(p.cash_price)}</td>`).join("")}</tr>
          <tr><td class="fw-bold">Nasiya (12 oy)</td>${selected.map((p) => `<td>${p.indicative_installment ? `${fmtUzs(p.indicative_installment.monthly_payment)}/oy` : "Taqiqlangan"}</td>`).join("")}</tr>
          <tr><td class="fw-bold">Sotuvchi</td>${selected.map((p) => `<td>${esc(p.store_name)}</td>`).join("")}</tr>
          <tr><td class="fw-bold">Reyting</td>${selected.map((p) => `<td>★ ${p.rating} (${p.review_count})</td>`).join("")}</tr>
          <tr><td class="fw-bold">Kafolat</td>${selected.map((p) => `<td>${p.warranty_months} oy</td>`).join("")}</tr>
          <tr><td class="fw-bold">Yetkazish</td>${selected.map((p) => `<td>${p.delivery_sla_days} kun</td>`).join("")}</tr>
        </tbody>
      </table>
    </div>
  `;
  document.getElementById("btn-clear-compare")?.addEventListener("click", () => {
    AppState.compareIds = [];
    localStorage.setItem("zarvon_compare", "[]");
    document.getElementById("compare-count")?.classList.add("hidden");
    renderCompareView(container);
  });
}
