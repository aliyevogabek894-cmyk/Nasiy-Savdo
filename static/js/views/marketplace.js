/* Home, Smart Catalog, Product Detail, Interactive Nasiya Calculator & Compare Views */
import { apiFetch, esc, fmtDate, fmtUzs, renderProductCard, showToast, wireProductCardActions } from "../api.js";
import { AppState } from "../i18n.js";

const CAT_ICONS = {
  smartfonlar: "📱",
  noutbuklar: "💻",
  televizorlar: "📺",
  sovutgichlar: "🧊",
  "kir-yuvish": "🧺",
  mebel: "🛋",
  "kochmas-mulk": "🏠",
};

const STUDIO_CAT_THUMBS = {
  smartfonlar: "/static/img/products/iphone-16-pro.jpg",
  telefonlar: "/static/img/products/iphone-16-pro.jpg",
  kompyuterlar: "/static/img/products/macbook-air-m3.jpg",
  noutbuklar: "/static/img/products/macbook-air-m3.jpg",
  "maishiy-texnika": "/static/img/products/bosch-washer.jpg",
  "kir-yuvish": "/static/img/products/bosch-washer.jpg",
  sovutgichlar: "/static/img/products/samsung-fridge.jpg",
  televizorlar: "/static/img/products/lg-qned-tv.jpg",
  mebellar: "/static/img/products/loft-sofa.jpg",
  mebel: "/static/img/products/loft-sofa.jpg",
  "kochmas-mulk": "/static/img/products/commercial-office.jpg",
};

function computeSimpleEstimate(price, downPct, months, annualRatePct = 24) {
  const down = Math.round((price * downPct) / 100);
  const principal = Math.max(0, price - down);
  const extra = Math.round(principal * (annualRatePct / 100) * (months / 12));
  const totalPayable = principal + extra;
  const monthly = months > 0 ? Math.round(totalPayable / months) : 0;
  return { down, principal, extra, totalPayable, monthly };
}

function renderBankOffersHtml(banks, principalAmount, months = 12) {
  if (!banks || !banks.length) return "";
  const safePrincipal = Math.max(1_000_000, Number(principalAmount || 9_600_000));
  const minRate = Math.min(...banks.map((b) => Number(b.base_annual_rate_pct || 30)));
  return banks
    .map((b) => {
      const rate = Number(b.base_annual_rate_pct || 28);
      const effMonths = Math.min(months, Number(b.max_months || 12));
      const est = computeSimpleEstimate(safePrincipal, 0, effMonths, rate);
      const isBest = rate === minRate;
      const statusCls = b.adapter_status === "ONLINE" ? "badge-success" : "badge-warning";
      return `
        <article class="bank-offer-card ${isBest ? "bank-offer-best" : ""}">
          <div class="flex-between">
            <strong style="font-size:1rem;">🏦 ${esc(b.name)}</strong>
            <span class="badge ${statusCls}">${esc(b.adapter_status)}</span>
          </div>
          <div class="flex-between text-xs text-muted">
            <span>Yillik stavka: <strong style="color:var(--text-primary);">${rate}%</strong></span>
            <span>Maks: <strong>${b.max_months} oy</strong></span>
          </div>
          <div class="tabular" style="padding:8px 10px;border-radius:10px;background:var(--bg-subtle);">
            <div class="text-xs text-muted">${effMonths} oylik taxminiy to‘lov:</div>
            <div class="fw-bold" style="font-size:1.08rem;">${fmtUzs(est.monthly)} / oy</div>
          </div>
          <div class="flex-between mt-auto pt-1">
            ${isBest ? `<span class="badge badge-gold">★ Eng past foiz</span>` : `<span class="text-xs text-muted">SLA: ${b.uptime_pct}%</span>`}
            <a href="#customer/banks" class="btn btn-outline btn-sm">Ariza holati →</a>
          </div>
        </article>`;
    })
    .join("");
}

export async function renderHomeView(container, reloadCartBadge) {
  const data = await apiFetch("/api/v1/catalog/home/");
  const banners = data.banners && data.banners.length
    ? data.banners
    : [
        {
          badge_text: "ZARVON NASIYA",
          title: "Kerakli mahsulot — qulay to‘lov bilan",
          subtitle: "Bir nechta bank taklifini solishtiring va o‘zingizga mos to‘lovni tanlang.",
          cta_label: "Mahsulotlarni ko‘rish",
          target_route: "#catalog",
          theme_variant: "navy",
        },
      ];

  const slideVisuals = [
    "/static/img/hero-showcase.jpg",
    "/static/img/products/iphone-16-pro.jpg",
    "/static/img/products/macbook-air-m3.jpg",
  ];

  const eligibleCats = (data.categories || []).filter((c) => c.installment_allowed !== false);
  const cashOnlyCats = (data.categories || []).filter((c) => c.installment_allowed === false);
  const topFiveCats = eligibleCats.slice(0, 5);

  const popularPool = (data.installment_picks && data.installment_picks.length
    ? data.installment_picks
    : data.new_arrivals || []
  ).slice(0, 4);

  const bankPartners = data.bank_partners || [];
  const initCalc = computeSimpleEstimate(11_990_000, 20, 12, 0);

  container.innerHTML = `
    <!-- 1. Luxury Full-Width Navy Hero Banner -->
    <section class="hero-luxury-wrap" aria-label="Asosiy banner">
      <div class="hero-luxury-card" id="hero-carousel">
        <div class="hero-luxury-content">
          <div class="hero-badge" id="hero-slide-badge" style="width:fit-content;">${esc(banners[0].badge_text || "ZARVON FINTECH")}</div>
          <h1 id="hero-slide-title">${esc(banners[0].title)}</h1>
          <p id="hero-slide-sub">${esc(banners[0].subtitle)}</p>
          <div class="hero-luxury-actions">
            <a id="hero-slide-cta" href="${esc(banners[0].target_route || "#catalog")}" class="btn btn-gold">
              🛒 ${esc(banners[0].cta_label || "Mahsulotlarni ko‘rish")} ›
            </a>
            <a href="#calculator" class="btn-hero-ghost">🧮 Nasiya hisoblash</a>
          </div>
        </div>
        <div class="hero-luxury-visual">
          <img id="hero-slide-img" src="${slideVisuals[0]}" alt="ZARVON elektronika va maishiy texnika kolleksiyasi">
        </div>
        ${
          banners.length > 1
            ? `<div class="hero-luxury-dots" id="hero-dots">
                 ${banners.map((_, idx) => `<button type="button" class="hero-dot ${idx === 0 ? "active" : ""}" data-hero-dot="${idx}" aria-label="${idx + 1}-slayd"></button>`).join("")}
               </div>`
            : ""
        }
      </div>
    </section>

    <!-- 2. Overlapping 5-Card Floating Category Strip -->
    <section class="cat-float-wrap" aria-label="Asosiy toifalar">
      <div class="cat-float-grid">
        ${topFiveCats
          .map((c) => {
            const thumb = STUDIO_CAT_THUMBS[c.slug] || "/static/img/products/iphone-16-pro.jpg";
            return `
            <a href="#catalog?category=${esc(c.slug)}" class="cat-float-card">
              <div class="cat-float-thumb">
                <img src="${esc(thumb)}" alt="${esc(c.name)}" loading="lazy">
              </div>
              <div class="cat-float-name">
                <span>${esc(c.name)}</span>
                <span aria-hidden="true" style="color:var(--text-muted);">›</span>
              </div>
            </a>`;
          })
          .join("")}
      </div>
      ${
        cashOnlyCats.length
          ? `<div class="flex-gap mt-2" style="padding:0 4px;">
               <span class="text-xs text-muted">Qo‘shimcha toifalar:</span>
               ${cashOnlyCats
                 .map((c) => `<a href="#catalog?category=${esc(c.slug)}" class="quick-chip-link">${esc(c.name)} (Faqat naqd)</a>`)
                 .join("")}
             </div>`
          : ""
      }
    </section>

    <!-- 3. 3-Column Divided Trust Bar -->
    <section class="trust-bar-3" aria-label="Platforma afzalliklari">
      <div class="trust-item">
        <div class="trust-icon-box" aria-hidden="true">▤</div>
        <div>
          <strong style="font-size:0.95rem;">Bank takliflarini solishtirish</strong>
          <div class="text-xs text-muted">Bir nechta hamkor taklifini ko‘rib chiqing.</div>
        </div>
      </div>
      <div class="trust-item">
        <div class="trust-icon-box" aria-hidden="true">📅</div>
        <div>
          <strong style="font-size:0.95rem;">Shaffof to‘lov jadvali</strong>
          <div class="text-xs text-muted">Barcha to‘lovlar oldindan ko‘rsatiladi.</div>
        </div>
      </div>
      <div class="trust-item">
        <div class="trust-icon-box" aria-hidden="true">🛡</div>
        <div>
          <strong style="font-size:0.95rem;">Himoyalangan xarid</strong>
          <div class="text-xs text-muted">Xavfsiz to‘lov va buyurtma nazorati.</div>
        </div>
      </div>
    </section>

    <!-- 4. Split Section: Ommabop mahsulotlar + Live Nasiya Kalkulyatori -->
    <section class="home-featured-split" aria-label="Ommabop mahsulotlar va kalkulyator">
      <div>
        <div class="flex-between mb-3">
          <div>
            <h2 style="margin:0;">Ommabop mahsulotlar</h2>
            <span class="text-xs text-muted">Naqd va oylik nasiya shartlari ochiq ko‘rsatilgan eng ko‘p tanlangan tovarlar</span>
          </div>
          <a href="#catalog" class="fw-bold text-sm" style="color:var(--navy-700);">Barchasini ko‘rish ›</a>
        </div>
        <div class="featured-4-grid">
          ${popularPool.map(renderProductCard).join("")}
        </div>
      </div>

      <!-- Interactive Live Embedded Calculator Widget -->
      <aside class="calc-widget-card" aria-label="Nasiya kalkulyatori vidjeti">
        <div class="calc-widget-head">
          <div class="calc-widget-head-title">
            <span aria-hidden="true">🧮</span>
            <span>Nasiya kalkulyatori</span>
          </div>
          <span class="calc-badge-pill">Taxminiy hisob</span>
        </div>
        <div class="calc-widget-body">
          <div class="form-group mb-3">
            <label class="form-label text-xs" for="hc-price">Mahsulot narxi</label>
            <div class="calc-price-wrap">
              <input id="hc-price" type="number" class="tabular" value="11990000" min="300000" max="500000000" step="100000">
              <span class="calc-price-unit">so‘m</span>
            </div>
          </div>

          <div class="form-group mb-3">
            <div class="flex-between mb-1">
              <label class="form-label text-xs" for="hc-down-pct" style="margin:0;">Boshlang‘ich to‘lov</label>
              <strong id="hc-down-uzs" class="tabular text-xs" style="color:var(--navy-700);">= ${fmtUzs(initCalc.down)}</strong>
            </div>
            <div class="flex-gap" style="align-items:center;">
              <select id="hc-down-pct" class="form-control" style="max-width:110px;min-height:38px;">
                <option value="0">0%</option>
                <option value="10">10%</option>
                <option value="15">15%</option>
                <option value="20" selected>20%</option>
                <option value="30">30%</option>
                <option value="40">40%</option>
                <option value="50">50%</option>
                <option value="60">60%</option>
              </select>
              <input id="hc-down-slider" type="range" class="zarvon-range" min="0" max="60" step="5" value="20">
            </div>
          </div>

          <div class="form-group mb-2">
            <label class="form-label text-xs">Muddat</label>
            <div class="calc-term-grid" id="hc-term-grid">
              <button type="button" class="calc-term-btn" data-hc-months="3">3 oy</button>
              <button type="button" class="calc-term-btn" data-hc-months="6">6 oy</button>
              <button type="button" class="calc-term-btn" data-hc-months="9">9 oy</button>
              <button type="button" class="calc-term-btn active" data-hc-months="12">12 oy</button>
              <button type="button" class="calc-term-btn" data-hc-months="18">18 oy</button>
              <button type="button" class="calc-term-btn" data-hc-months="24">24 oy</button>
            </div>
          </div>

          <div class="calc-result-banner">
            <div>
              <div class="text-xs fw-bold">📅 Taxminiy oylik to‘lov</div>
              <div id="hc-mode-note" class="text-xs" style="opacity:0.82;">2027 Standarti • Qoldiq: ${fmtUzs(initCalc.principal)}</div>
            </div>
            <strong id="hc-monthly-out" class="tabular">${fmtUzs(initCalc.monthly)}</strong>
          </div>

          <div class="flex-between mt-3">
            <span class="text-xs text-muted">0% jarimasiz erta yopish</span>
            <a href="#calculator" class="fw-bold text-xs" style="color:var(--navy-700);">Batafsil jadval →</a>
          </div>
        </div>
      </aside>
    </section>

    <!-- 5. Multi-Bank Offers Comparison -->
    ${
      bankPartners.length
        ? `<section class="mt-6" aria-label="Hamkor banklar takliflari">
             <div class="flex-between mb-3">
               <div>
                 <h2 style="margin:0;">🏦 Banklarning nasiya takliflarini solishtiring</h2>
                 <p class="text-xs text-muted" style="margin:2px 0 0;">Yuqoridagi kalkulyator summasi (${fmtUzs(initCalc.principal)}) bo‘yicha real vaqtda yangilanadigan taxminiy bank takliflari</p>
               </div>
               <a href="#customer/kyc" class="btn btn-gold btn-sm">⚡ Shaxsiy limitimni tekshirish</a>
             </div>
             <div id="home-bank-offers" class="bank-offer-grid">
               ${renderBankOffersHtml(bankPartners, initCalc.principal, 12)}
             </div>
           </section>`
        : ""
    }

    <!-- 6. Hafta Chegirmalari Horizontal Strip -->
    ${
      data.discounts.length
        ? `<section class="mt-6">
             <div class="flex-between mb-3">
               <div>
                 <h2 style="margin-bottom:2px;">🔥 Maxsus chegirmalar</h2>
                 <span class="text-xs text-muted">Shaffof eski narx tarixi va chegirmali takliflar</span>
               </div>
               <a href="#catalog?sort=popular" class="btn btn-outline btn-sm">Barchasi →</a>
             </div>
             <div class="h-scroll-snap">
               ${data.discounts.map(renderProductCard).join("")}
             </div>
           </section>`
        : ""
    }

    <!-- 7. KATM + MIB Skoring CTA & Payment Gateways -->
    <section class="mt-6 card card-elevated" style="background:linear-gradient(125deg, #0d213f 0%, #193b68 100%);color:#ffffff;border:1px solid rgba(219,182,59,0.45);">
      <div class="flex-between" style="flex-wrap:wrap;gap:14px;">
        <div>
          <div class="psp-trust-strip" style="background:transparent;border:none;padding:0 0 8px;color:#cbd5e1;">
            <span class="psp-chip psp-chip-payme">Payme</span>
            <span class="psp-chip psp-chip-click">Click</span>
            <span class="psp-chip psp-chip-uzum">Uzum Bank</span>
            <span class="psp-chip psp-chip-paynet">Paynet</span>
            <span class="psp-chip">🛡 KATM + MIB Skoring</span>
          </div>
          <h2 style="color:#ffffff;margin:0 0 4px;">INN / PINFL orqali 1 daqiqada shaxsiy nasiya limitini biling</h2>
          <div class="text-sm" style="color:#cbd5e1;">Boshqa banklardagi kredit yuklamasi, MIB ijro qarzlari va Markaziy Bankning 50% DSTI mezoni mijoz roziligi bilan tekshiriladi.</div>
        </div>
        <div class="flex-gap">
          <a href="#customer/kyc" class="btn btn-gold">⚡ Limitni tekshirish →</a>
          <a href="#seller-onboarding" class="btn-hero-ghost">🏪 Sotuvchi bo‘lish</a>
        </div>
      </div>
    </section>

    <!-- 8. 6-Qadamli Nasiya Xarid Jarayoni -->
    <section class="mt-6 card">
      <div class="flex-between mb-3">
        <div>
          <h2 style="margin:0;">Nasiya bilan xarid qilish — 6 oddiy qadamda</h2>
          <span class="text-xs text-muted">To‘lovga yaqin qolganda kabinet va avtomatik xabarnomalar orqali eslatiladi</span>
        </div>
      </div>
      <div class="how-strip-grid" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr));">
        <div class="how-step-card"><span class="how-step-num">1</span><strong>Mahsulot tanlash</strong><div class="text-xs text-secondary">Naqd narx va oylik to‘lovni solishtiring.</div></div>
        <div class="how-step-card"><span class="how-step-num">2</span><strong>Nasiya hisoblash</strong><div class="text-xs text-secondary">Boshlang‘ich to‘lov va qulay muddatni tanlang.</div></div>
        <div class="how-step-card"><span class="how-step-num">3</span><strong>Ariza va rozilik</strong><div class="text-xs text-secondary">PINFL/INN kiritilib KATM + MIB roziligi beriladi.</div></div>
        <div class="how-step-card"><span class="how-step-num">4</span><strong>Bank takliflari</strong><div class="text-xs text-secondary">Hamkor banklarning shartlarini taqqoslang.</div></div>
        <div class="how-step-card"><span class="how-step-num">5</span><strong>Elektron shartnoma</strong><div class="text-xs text-secondary">Tasdiqlangan jadval asosida SMS/OTP imzolash.</div></div>
        <div class="how-step-card"><span class="how-step-num">6</span><strong>Mahsulotni olish</strong><div class="text-xs text-secondary">Kuryer yoki topshirish punktidan tez yetkazish.</div></div>
      </div>
    </section>
  `;

  // Hero Carousel
  if (banners.length > 1) {
    let slideIdx = 0;
    const titleEl = document.getElementById("hero-slide-title");
    const subEl = document.getElementById("hero-slide-sub");
    const badgeEl = document.getElementById("hero-slide-badge");
    const ctaEl = document.getElementById("hero-slide-cta");
    const imgEl = document.getElementById("hero-slide-img");
    const dots = Array.from(document.querySelectorAll("[data-hero-dot]"));

    const goSlide = (n) => {
      slideIdx = ((n % banners.length) + banners.length) % banners.length;
      const b = banners[slideIdx];
      if (titleEl) titleEl.textContent = b.title;
      if (subEl) subEl.textContent = b.subtitle;
      if (badgeEl) badgeEl.textContent = b.badge_text || "ZARVON";
      if (ctaEl) {
        ctaEl.href = b.target_route || "#catalog";
        ctaEl.textContent = `🛒 ${b.cta_label || "Ko‘rish"} ›`;
      }
      if (imgEl) imgEl.src = slideVisuals[slideIdx % slideVisuals.length];
      dots.forEach((d, idx) => d.classList.toggle("active", idx === slideIdx));
    };

    dots.forEach((d) => d.addEventListener("click", () => goSlide(Number(d.dataset.heroDot))));
    let timer = setInterval(() => goSlide(slideIdx + 1), 5500);
    const stopTimer = () => {
      clearInterval(timer);
      window.removeEventListener("hashchange", stopTimer);
    };
    window.addEventListener("hashchange", stopTimer);
  }

  // Live Embedded Home Calculator Widget Wiring
  const hcPriceEl = document.getElementById("hc-price");
  const hcPctSel = document.getElementById("hc-down-pct");
  const hcPctSlider = document.getElementById("hc-down-slider");
  const hcDownUzs = document.getElementById("hc-down-uzs");
  const hcMonthlyOut = document.getElementById("hc-monthly-out");
  const hcModeNote = document.getElementById("hc-mode-note");
  const bankGridEl = document.getElementById("home-bank-offers");
  let activeMonths = 12;
  let calcDebounce = null;

  const updateHomeCalc = (sourcePct) => {
    const price = Math.max(300_000, Number(hcPriceEl?.value || 0));
    const pct = Math.min(60, Math.max(0, Number(sourcePct ?? hcPctSel?.value ?? 20)));
    if (hcPctSel && Number(hcPctSel.value) !== pct) hcPctSel.value = String(pct);
    if (hcPctSlider && Number(hcPctSlider.value) !== pct) hcPctSlider.value = String(pct);

    const est = computeSimpleEstimate(price, pct, activeMonths, activeMonths <= 12 ? 0 : 26);
    if (hcDownUzs) hcDownUzs.textContent = `= ${fmtUzs(est.down)}`;
    if (hcMonthlyOut) hcMonthlyOut.textContent = fmtUzs(est.monthly);
    if (hcModeNote) {
      hcModeNote.textContent =
        activeMonths <= 12
          ? `2027 Standarti • Qoldiq: ${fmtUzs(est.principal)}`
          : `Hamkor bank krediti (indikativ) • Qoldiq: ${fmtUzs(est.principal)}`;
    }
    if (bankGridEl && bankPartners.length) {
      bankGridEl.innerHTML = renderBankOffersHtml(bankPartners, est.principal, activeMonths);
    }

    if (activeMonths <= 12) {
      clearTimeout(calcDebounce);
      calcDebounce = setTimeout(async () => {
        try {
          const q = await apiFetch("/api/v1/finance/calculator/", {
            method: "POST",
            body: JSON.stringify({
              price,
              down_payment: est.down,
              months: activeMonths,
              category_installment_allowed: true,
            }),
          });
          if (hcMonthlyOut) hcMonthlyOut.textContent = fmtUzs(q.monthly_payment);
          if (hcModeNote) {
            hcModeNote.textContent = `✓ Compliance Guard (${q.annualized_extra_pct}%/yil) • Qoldiq: ${fmtUzs(q.principal)}`;
          }
        } catch {
          /* Keep clean indicative estimate if above 250 BHM cap */
        }
      }, 220);
    }
  };

  hcPriceEl?.addEventListener("input", () => updateHomeCalc());
  hcPctSel?.addEventListener("change", () => updateHomeCalc(hcPctSel.value));
  hcPctSlider?.addEventListener("input", () => updateHomeCalc(hcPctSlider.value));
  document.querySelectorAll("[data-hc-months]").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeMonths = Number(btn.dataset.hcMonths);
      document.querySelectorAll("[data-hc-months]").forEach((b) => b.classList.toggle("active", b === btn));
      updateHomeCalc();
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
            ? `<div class="uzum-grid" style="grid-template-columns:repeat(auto-fill,minmax(215px,1fr));">${catalogData.results.map(renderProductCard).join("")}</div>`
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

function buildAmortizationSvg(schedule, principalTotal, extraTotal) {
  if (!schedule || !schedule.length) return "";
  const w = 520;
  const h = 150;
  const padX = 16;
  const maxBarH = 112;
  const barGap = 8;
  const count = schedule.length;
  const barW = Math.max(12, Math.floor((w - padX * 2 - barGap * (count - 1)) / count));
  const perExtra = Math.round(extraTotal / count);
  const perPrincipal = Math.round(principalTotal / count);
  const maxVal = Math.max(1, perPrincipal + perExtra);

  const bars = schedule
    .map((row, i) => {
      const x = padX + i * (barW + barGap);
      const totalH = Math.max(16, Math.round((row.amount / maxVal) * maxBarH));
      const extraH = Math.max(3, Math.round((perExtra / maxVal) * maxBarH));
      const prinH = Math.max(6, totalH - extraH);
      const yPrin = 126 - prinH;
      const yExtra = yPrin - extraH;
      return `
        <g>
          <title>${row.installment_no}-oy: Asosiy ${fmtUzs(perPrincipal)} + Ustama ${fmtUzs(perExtra)}</title>
          <rect x="${x}" y="${yExtra}" width="${barW}" height="${extraH}" rx="3" fill="#C9A227"></rect>
          <rect x="${x}" y="${yPrin}" width="${barW}" height="${prinH}" rx="3" fill="#0D213F"></rect>
          <text x="${x + barW / 2}" y="143" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.7">${row.installment_no}-oy</text>
        </g>`;
    })
    .join("");

  return `
    <div class="chart-box mb-3">
      <div class="flex-between mb-2">
        <strong class="text-sm">📊 Oylik Amortizatsiya Tahlili (Asosiy qarz vs Ustama)</strong>
        <div class="flex-gap text-xs">
          <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#0D213F;"></span> Asosiy</span>
          <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#C9A227;"></span> Ustama</span>
        </div>
      </div>
      <svg viewBox="0 0 ${w} ${h}" class="chart-svg" role="img" aria-label="Amortizatsiya grafigi">${bars}</svg>
    </div>`;
}

export async function renderCalculatorView(container) {
  const [comp, homeData] = await Promise.all([
    apiFetch("/api/v1/governance/compliance/"),
    apiFetch("/api/v1/catalog/home/").catch(() => ({ bank_partners: [] })),
  ]);
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
            <div class="flex-between">
              <label class="form-label" for="sc-price">Mahsulot narxi (so‘m)</label>
              <span class="text-xs text-muted">300 000 – 100 000 000</span>
            </div>
            <input id="sc-price" type="number" class="form-control tabular" value="12000000" min="300000" step="100000">
            <input id="sc-price-range" type="range" class="zarvon-range" min="500000" max="50000000" step="250000" value="12000000">
          </div>
          <div class="form-group">
            <div class="flex-between">
              <label class="form-label" for="sc-down">Boshlang‘ich to‘lov (so‘m)</label>
              <span id="sc-down-pct-lbl" class="badge badge-navy">20%</span>
            </div>
            <input id="sc-down" type="number" class="form-control tabular" value="2400000" min="0" step="100000">
            <input id="sc-down-range" type="range" class="zarvon-range" min="0" max="60" step="5" value="20">
          </div>
          <div class="form-group">
            <label class="form-label" for="sc-months">Muddat (oy)</label>
            <select id="sc-months" class="form-control">
              <option value="3">3 oy</option>
              <option value="6">6 oy</option>
              <option value="9">9 oy</option>
              <option value="12" selected>12 oy (ZARVON Compliance)</option>
              <option value="18">18 oy (Compliance Guard test!)</option>
            </select>
          </div>
          <div class="form-group">
            <label class="flex-gap" style="cursor:pointer;">
              <input id="sc-cat-ok" type="checkbox" checked>
              <span class="text-sm fw-bold">Nasiyaga ruxsat etilgan toifa (ko‘chmas mulk emas)</span>
            </label>
          </div>
          <button type="submit" class="btn btn-primary" style="width:100%;">Hisoblash va Jadvalni Yangilash</button>
        </form>
      </div>

      <div id="sc-result" class="card">
        <h3>Hisob-kitob va to‘lov jadvali</h3>
        <p class="text-muted text-sm">Parametrlarni tanlang.</p>
      </div>
    </div>
  `;

  const scPrice = document.getElementById("sc-price");
  const scPriceRange = document.getElementById("sc-price-range");
  const scDown = document.getElementById("sc-down");
  const scDownRange = document.getElementById("sc-down-range");
  const scPctLbl = document.getElementById("sc-down-pct-lbl");

  const calc = async () => {
    const resEl = document.getElementById("sc-result");
    try {
      const q = await apiFetch("/api/v1/finance/calculator/", {
        method: "POST",
        body: JSON.stringify({
          price: Number(scPrice.value),
          down_payment: Number(scDown.value),
          months: Number(document.getElementById("sc-months").value),
          category_installment_allowed: document.getElementById("sc-cat-ok").checked,
        }),
      });
      resEl.innerHTML = `
        <div class="flex-between mb-3">
          <h3 style="margin:0;">Oylik to‘lov (${q.months} oy)</h3>
          <span class="badge badge-success">✓ Compliance Guard o‘tdi</span>
        </div>
        <div class="calc-result-banner mb-3" style="margin-top:0;">
          <div>
            <div class="text-xs fw-bold">HAR OYLIK TO‘LOV</div>
            <div class="text-xs">Erta yopish jarimasi: 0%</div>
          </div>
          <strong class="tabular">${fmtUzs(q.monthly_payment)}</strong>
        </div>
        <div class="grid-3 tabular mb-3">
          <div class="kpi-card"><div class="kpi-label">Asosiy summa</div><div class="kpi-value" style="font-size:1.15rem;">${fmtUzs(q.principal)}</div></div>
          <div class="kpi-card"><div class="kpi-label">Ustama (${q.annualized_extra_pct}%/yil)</div><div class="kpi-value" style="font-size:1.15rem;">${fmtUzs(q.total_extra)}</div></div>
          <div class="kpi-card"><div class="kpi-label">Jami to‘lov</div><div class="kpi-value" style="font-size:1.15rem;">${fmtUzs(q.total_payable)}</div></div>
        </div>
        ${buildAmortizationSvg(q.preview_schedule, q.principal, q.total_extra)}
        ${
          (homeData.bank_partners || []).length
            ? `<div class="mb-3">
                 <div class="text-xs fw-bold text-muted mb-2">Hamkor banklar taqqoslamasi (${fmtUzs(q.principal)} asosida):</div>
                 <div class="bank-offer-grid">${renderBankOffersHtml(homeData.bank_partners, q.principal, q.months)}</div>
               </div>`
            : ""
        }
        <div class="table-wrap" style="max-height:260px;overflow-y:auto;">
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

  scPriceRange.addEventListener("input", () => {
    scPrice.value = scPriceRange.value;
    const pct = Number(scDownRange.value);
    scDown.value = String(Math.round((Number(scPrice.value) * pct) / 100));
  });
  scDownRange.addEventListener("input", () => {
    const pct = Number(scDownRange.value);
    scPctLbl.textContent = `${pct}%`;
    scDown.value = String(Math.round((Number(scPrice.value) * pct) / 100));
  });
  scPrice.addEventListener("input", () => {
    scPriceRange.value = String(Math.min(50000000, Math.max(500000, Number(scPrice.value || 0))));
  });
  scDown.addEventListener("input", () => {
    const p = Math.max(1, Number(scPrice.value || 1));
    const pct = Math.min(60, Math.round((Number(scDown.value || 0) / p) * 100));
    scPctLbl.textContent = `${pct}%`;
    scDownRange.value = String(pct);
  });

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
