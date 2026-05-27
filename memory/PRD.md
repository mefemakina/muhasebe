# MEFE Muhasebe - Uyumsoft Cari Takip — PRD

## Orijinal Problem Statement
cursor.com'da yapılmış Uyumsoft fatura CSV'lerinden cari mutabakat, bakiye takip, devir/dönem, manuel tahsilat/ödeme, dashboard ve grafik ekranları içeren MEFE Muhasebe masaüstü programı. Python + Tkinter + SQLite stack, PyInstaller + Inno Setup ile Windows installer üretimi. Kaynak `cursor/uyumsoft-ledger-desktop-ae8c` branch'inde `desktop/` klasöründeydi; iyileştirmeler için "muhasebe" adlı yeni repoya pushlanacak.

## Mimari
- **Tek dosya**: `desktop/main.py` → `uyumsoft_cari.app.main()`
- **UI**: Tkinter ttk, sv-ttk (Sun Valley) Windows 11 Fluent teması, light/dark toggle
- **Veri**: Yerel SQLite (WAL), `LedgerDatabase` (db.py)
- **CSV importer**: Uyumsoft Gelen/Giden başlıklarına bağlı profil tabanlı parser
- **9 Sekme**: Ana Ekran (dashboard) · CSV İçe Aktar · Manuel İşlemler · Cari Mutabakat · Devir/Dönem · Aylık Grafik · Yıllık Grafik · Firma Yıllık Ciro · Yedek/Aktarım

## Çekirdek İş Kuralları
- Giden Fatura → BORÇ (müşteri bize borçlu)
- Gelen Fatura → ALACAK (biz tedarikçiye borçluyuz)
- Manuel Tahsilat → ALACAK; Manuel Ödeme → BORÇ
- Ana ekran cari listesinde **sadece ödenmemiş giden faturalar**
- Net Finansal Durum dashboard tarih aralığından bağımsız (aktif dönem değeri)
- Piyasa alacağı negatif olamaz (`max(..., 0)` çift güvence)
- Leasing/finansal kiralama firmaları blacklist (otomatik engellenir)

## Yapılanlar (v1.1.0 — 27.05.2026)
- ✅ Repo `mefemakina/mefe-malzeme` çekildi, kod incelendi
- ✅ Modern Tema: **sv-ttk (Sun Valley)** entegrasyonu, sağ üst köşede light/dark toggle butonu
- ✅ MEFE marka renkleri (mor #2d237f, turkuaz #0f6f8f) tema üstüne bindirildi
- ✅ Tablo renkleri yeniden semantikleştirildi: yeşil=açık, **soluk gri=ödenmiş** (eskiden kırmızıydı, yanıltıcıydı)
- ✅ `transactions.is_auto_paid` ve `auto_paid_invoice_id` indexed kolonları eklendi; `raw_json LIKE '%auto_paid_invoice_id%'` taramaları kaldırıldı (performans + okunabilirlik). Eski kayıtlar otomatik migrate ediliyor.
- ✅ Çoklu "Ödendi olarak işaretle" tek SQL transaction'da atomik (hata olursa hiçbiri yazılmaz)
- ✅ Manuel İşlemler ekranı: KeyRelease 250ms debounce ile auto-fill (büyük listede UI takılmasını önler)
- ✅ Dashboard arama 200ms debounce
- ✅ Aylık grafik: yıl seçimi Combobox'a dönüştürüldü, veri olan yılları otomatik listeler
- ✅ Para formatı tutarlılığı: `money_try`, `money_input`, `money_original`, `percent_try` ortak helper'ları
- ✅ Test path: `MEFE_TEST_CSV_DIR` env değişkeni veya repo içi `desktop/tests/fixtures/` (eski cursor uploads yolu geriye dönük destek)
- ✅ Sentetik CSV fixture'ları: `desktop/tools/generate_test_fixtures.py` ile üretilen Uyumsoft formatına birebir uyumlu gerçek müşteri verisi olmayan örnekler
- ✅ `__version__ = "1.1.0"` paket sürümü; `tools/sync_installer_version.py` ile installer ile senkronize
- ✅ PyInstaller spec yorum + `collect_data_files("sv_ttk")` ile tema dosyaları otomatik
- ✅ Installer çıktı adı `MEFE-Muhasebe-Setup-{version}.exe` (version embedded)
- ✅ README: code signing (Authenticode) dokümantasyonu, signtool örnekleri

## Test Durumu
```
python3 -m unittest tests.desktop.test_uyumsoft_cari
→ 13 tests, 13 PASSED (önceki sürümde 10 pass + 3 path error idi)
```

## Görsel Doğrulama
- Light mode: ✅ sv-ttk açık tema, koyu metin açık zeminde, modern rounded design
- Dark mode: ✅ sv-ttk koyu tema, açık metin koyu zeminde, kontrast tutarlı, residual light bg yok

## Kullanıcı Personas
- **MEFE muhasebe kullanıcısı**: Uyumsoft'tan günlük CSV indirip içeri aktarır, ana ekrandan piyasa alacağını görür, manuel tahsilat girer
- **Yönetici**: Yıllık ciro raporu, aylık/yıllık trend grafikleri, mutabakat raporu kullanır

## Backlog (P1)
- app.py refactor: 1463 satırlık dosya → sekme başına ayrı modül (`tabs/dashboard.py`, `tabs/manual.py` vb.)
- Tüm metrik kartları için tooltip ekleme
- Mutabakat ekranında PDF export
- Otomatik DB yedekleme (günlük zamanlanmış)
- CSV import sırasında progress bar (büyük dosyalar için)
- Birden çok kullanıcı/şirket profili desteği

## Backlog (P2)
- Çoklu para birimi raporu sekmesi (USD/EUR açık bakiye)
- Dashboard widget'larının drag-and-drop yeniden düzenlenmesi
- Tablo verilerini Excel'e direkt export
- Klavye kısayolları paneli (F1)

## Sonraki Adımlar
1. Kullanıcı "Save to GitHub" özelliğiyle `muhasebe` reposuna pushlayacak
2. Windows makinesinde build doğrulama: `pyinstaller --clean --noconfirm mefe_muhasebe.spec`
3. Inno Setup ile installer üretimi
4. (Opsiyonel) EV Code Signing sertifika ile SmartScreen reputation
