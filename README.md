# ZARVON — Ko‘p sotuvchili Marketplace va Shaffof Muddatli To‘lov Platformasi

Ushbu loyiha `ZARVON_MASTER_SPECIFICATION_v3` texnik topshirig‘i (barcha 36 ta bo‘lim) asosida **Django 6.1 + Django REST Framework** modular monolith arxitekturasi va universal veb/PWA interfeysi sifatida yaratildi.

> **Muhim eslatma (Sandbox / DEMO):** Tizim test/sandbox rejimida ishlaydi. Barcha nasiya shartnomalari, bank takliflari, MyID/OneID va to‘lov tizimlari sinov ma’lumotlaridir; real kredit ajratilmaydi va mijoz puli qabul qilinmaydi.

---

## Arxitektura (Modular Monolith)

- `config/` — Loyiha sozlamalari, Security Headers & Correlation ID middleware, RBAC + tenant izolyatsiyasi, shifrlash/masking va O‘zbekcha aqlli qidiruv normallashtiruvchisi.
- `apps/accounts/` — Identity, 14 ta foydalanuvchi roli, OTP/MFA, sessiyalar va **Maker-Checker** ikki bosqichli tasdiq tizimi.
- `apps/governance/` — O‘zgarmas `AuditLog`, `SecurityEvent`, bazada versiyalanadigan `BhmValue`, `ComplianceRuleVersion`, `NotificationEvent` va maxfiylik so‘rovlari.
- `apps/sellers/` — Bir martalik taklifnoma (faqat SHA-256 xeshi saqlanadi), onboarding jarayoni (`Invited → Submitted → Approved/...`), tenant-izolyatsiyali do‘kon kabineti va xodimlar.
- `apps/catalog/` — Kategoriyalar (shu jumladan `installment_allowed=False` taqiq bayrog‘i), brendlar, mahsulot versiyalari va moderatsiyasi, faqat xarid qilganlar uchun sharhlar, sevimlilar, CMS bannerlar va promo-kodlar.
- `apps/imports/` — `.xlsx` (`openpyxl`) va `.csv` ommaviy import markazi (formula injection himoyasi, dublikat SKU nazorati, yuklab olinadigan xato hisoboti, idempotency key) hamda SSRF himoyali tashqi katalog API vault.
- `apps/inventory/` — Omborlar, zaxira qoldig‘i, harakatlar jurnali va parallel xaridlarda overselling‘ni to‘suvchi atomik `Reservation`.
- `apps/commerce/` — Savat, 3 qadamli kassa, ko‘p sotuvchili sub-buyurtmalarga ajratish (`Order` → `SellerOrder`), o‘zgarmas narx snapshotlari, topshirish OTP-kodi, to‘liq/qisman qaytarish va refund.
- `apps/finance/` — `InstallmentProvider` abstraksiyasi (`OwnInstallmentProvider` + `PartnerFinanceProvider`), **2027 Compliance Guard** (≤ 12 oy, ≤ 250 BHM, ≤ 50%/yil, 0% erta to‘lov jarimasi), maqsadli roziliklar, Multi-Bank Gateway va kunlik reconciliation.
- `apps/risk_collections/` — Versiyalangan tushunarli skoring va mijoz apellyatsiyasi, Anti-Fraud signallari, DPD bosqichli undirish va Maker-Checker restrukturizatsiya, qo‘llab-quvvatlash chiptalari.

---

## Ishga tushirish

```bash
python manage.py migrate
python manage.py seed_zarvon
python manage.py runserver 127.0.0.1:8000
```

Avtomatik testlarni ishga tushirish:
```bash
python manage.py test apps.governance -v 2
```

### Demo akkauntlar (Parol: `Zarvon2026!`)
Sayt sarlavhasidagi **"Kirish / Rol"** tugmasi orqali barcha rollarga 1 bosishda o‘tish mumkin:
- **Customer (KYC tasdiqlangan):** `+998901110001` (Azizbek Karimov)
- **Seller Owner (TexnoUz):** `+998902220001` (Sardor Alimov)
- **Seller Staff:** `+998902220002` (Dilshod Xasanov)
- **Super Admin:** `+998909990001` (Bobur Mansurov)
- **Marketplace Admin:** `+998909990002` (Nilufar Saidova)
- **Risk Manager:** `+998909990004` (Shohruh Nazarov)
- **Collections Agent:** `+998909990005` (Umidbek Jo‘rayev)
- **Fraud Analyst:** `+998909990006` (Kamola Ergasheva)
- **Auditor (Faqat o‘qish):** `+998909990008` (Rustam Abdullayev)
