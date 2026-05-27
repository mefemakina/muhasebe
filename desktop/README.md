# MEFE Muhasebe - Uyumsoft Cari Takip

Python/Tkinter masaüstü uygulaması. Uyumsoft'tan indirilen örnek **Gelen Fatura** ve **Giden Fatura** CSV başlıklarına göre çalışır, verileri yerel SQLite veritabanında saklar.

> Mevcut versiyon: `uyumsoft_cari/__init__.py` içindeki `__version__` değişkeninden okunur. Yayın yapılırken hem bu değer hem de `MEFE-Muhasebe-Installer.iss` içindeki `MyAppVersion` makrosu güncellenmelidir. `tools/sync_installer_version.py` script'i bu işi otomatik yapar.

## Modern Arayüz

Uygulama [sv-ttk](https://github.com/rdbende/Sun-Valley-ttk-theme) (Sun Valley) teması kullanır. Sağ üstteki **🌙 / ☀** düğmesi ile aydınlık/karanlık tema arasında geçiş yapılabilir.

## Cari matematik

- **Giden Faturalar**: Cari hesaba **BORÇ** işler; müşteri MEFE'ye borçlanır.
- **Gelen Faturalar**: Cari hesaba **ALACAK** işler; MEFE firmaya borçlanır.
- **Yapılan Ödemeler**: Bizim verdiğimiz para olarak cari hesaba **BORÇ** işler.
- **Gelen Havaleler/Tahsilatlar**: Bize gelen para olarak cari hesaba **ALACAK** işler.
- Ana ekrandaki **Piyasadan Toplam Güncel Alacak Tutarı**:
  - `Giden Faturalar Toplamı - Müşteriden Gelen Tahsilatlar Toplamı`
- Ana ekrandaki **Toplam Fazla / Net Finansal Durum**:
  - `(Giden Faturalar + Yapılan Ödemeler) - (Gelen Faturalar + Gelen Tahsilatlar) + Devir/Fazla`
- **Net Finansal Durum aktif dönem değeridir**; dashboard tarih aralığından etkilenmez.

Ana ekranda toplam alacak için başlangıç/bitiş tarih aralığı seçilebilir. Manuel ödeme ekranında cari adı yazıldığında mevcut kayıtlar içinde eşleşen firma bulunursa VKN/TCKN otomatik dolar; örneğin Uyumsoft giden fatura CSV'si içe aktarıldıktan sonra `COCA COLA` yazmak `6110008160` VKN değerini getirir. Otomatik doldurma KeyRelease olayında **250ms debounce** ile çalışır, yazma akıcılığını bozmaz.

CSV içindeki `Para Birimi` ve `Döviz Kuru` alanları kullanılarak tüm tutarlar TL karşılığıyla saklanır. TRY satırlarında Uyumsoft bazı dosyalarda kuru `0,00000000` verebildiği için TRY kur değeri sıfırsa `1` kabul edilir.

### Veri kalitesi iyileştirmeleri (v1.1)

- Otomatik "ödendi" işaretleri artık `transactions.is_auto_paid` ve `auto_paid_invoice_id` kolonlarında **indexed** saklanır. Eski `raw_json LIKE '%auto_paid_invoice_id%'` taramaları kaldırıldı; sorgular ölçeklenebilir.
- Çoklu "Ödendi olarak işaretle" işlemi tek SQL transaction içinde atomik çalışır. Hata olursa hiçbir kayıt eklenmez.
- Tablo satır renkleri yeniden semantikleştirildi: **yeşil = açık/aktif fatura**, **soluk gri = ödenmiş/kapalı** (eskiden ödenmiş kayıtlar kırmızı görünüyordu, yanıltıcıydı).

## Devir / dönem başlatma

`Devir / Dönem` ekranında kapanış tarihi ve muhasebeciden alınan net devir/fazla tutarı girilir.

- Program kapanış tarihine kadar olan işlemleri analiz eder.
- Giden faturalarda gelen tahsilatlar, gelen faturalarda yapılan ödemeler FIFO mantığıyla eşleştirilir.
- Tamamen kapanmamış faturalar `Fatura No`, orijinal tarih ve kalan TL tutarıyla yeni dönemin ilk gününe aktarılır.
- Tamamen kapanmış eski işlemler silinir; bu işlemlerin etkisi girilen devir/fazla tutarı içinde tutulur.

## Geliştirme ortamında çalıştırma

```powershell
cd desktop
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-windows.txt
python tools\create_transparent_logo.py
python main.py
```

Linux/macOS üzerinde hızlı kontrol:

```bash
cd desktop
pip install -r requirements-windows.txt
python3 main.py
```

## Testler

```bash
# Repodaki sentetik fixture'larla çalıştırır
python3 -m unittest tests.desktop.test_uyumsoft_cari

# Kendi örnek CSV'lerinizi kullanmak isterseniz:
export MEFE_TEST_CSV_DIR=/yol/kendi-csv-leriniz/
python3 -m unittest tests.desktop.test_uyumsoft_cari
```

Sentetik fixture'lar `desktop/tests/fixtures/` altında bulunur ve `desktop/tools/generate_test_fixtures.py` ile yeniden üretilebilir. Hiçbir gerçek müşteri verisi içermez.

## Windows tek dosya EXE üretimi

Bu adımlar sadece paketleme yapılan geliştirici makinesinde gereklidir. Son kullanıcı Python kurmadan çıkan EXE'yi çalıştırır.

1. Windows üzerinde Python 3.12+ kurun.
2. Proje kökünden masaüstü klasörüne girin:

   ```powershell
   cd desktop
   ```

3. Sanal ortam ve paketleri kurun:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements-windows.txt
   ```

4. Şeffaf **MEFE** logosunu ve Windows uygulama ikonunu üretin:

   ```powershell
   python tools\create_transparent_logo.py
   ```

5. Versiyon senkronu (installer ile uygulama sürümünü eşitler):

   ```powershell
   python tools\sync_installer_version.py
   ```

6. Tek dosya EXE oluşturun:

   ```powershell
   pyinstaller --clean --noconfirm mefe_muhasebe.spec
   ```

7. Çıktı:

   ```text
   desktop\dist\MEFE-Muhasebe.exe
   ```

## Windows Installer EXE üretimi

Installer oluşturmak için build makinesine Inno Setup kurulu olmalıdır.

1. Önce yukarıdaki PyInstaller adımlarıyla `dist\MEFE-Muhasebe.exe` dosyasını üretin.
2. Inno Setup Compiler ile `desktop\MEFE-Muhasebe-Installer.iss` dosyasını açıp **Compile** edin.
3. Komut satırıyla derlemek isterseniz:

   ```powershell
   & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\MEFE-Muhasebe-Installer.iss
   ```

4. Installer çıktısı (versiyon dosya adına gömülür):

   ```text
   desktop\installer\MEFE-Muhasebe-Setup-1.1.0.exe
   ```

Bu setup dosyası uygulamayı `Program Files\MEFE Muhasebe` altına kurar ve isteğe bağlı masaüstü kısayolu oluşturur.

## Code Signing (Authenticode) — Opsiyonel ama Önerilen

İmzalanmamış EXE'ler Windows SmartScreen tarafından "Bilinmeyen yayıncı" uyarısıyla engellenebilir. Kurumsal dağıtım için kod imzalama önerilir.

### Gerekli olanlar
1. **EV (Extended Validation) Code Signing Certificate** — DigiCert, Sectigo, SSL.com gibi otoritelerden ~~$300–500/yıl. EV sertifika SmartScreen reputation'unu anında verir.
2. **OV (Organization Validation)** ucuz alternatif (~~$100/yıl) ama SmartScreen reputation oluşturmak zaman ister.
3. **signtool.exe** (Windows SDK ile gelir).

### Build sonrası imzalama
```powershell
signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 ^
  /a /n "MEFE Makina" desktop\dist\MEFE-Muhasebe.exe

signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 ^
  /a /n "MEFE Makina" desktop\installer\MEFE-Muhasebe-Setup-1.1.0.exe
```

İmzayı doğrulama:
```powershell
signtool verify /pa /v desktop\dist\MEFE-Muhasebe.exe
```

> İmzalama olmadan da uygulama çalışır; ilk indirme uyarısı dışında kullanım deneyimi aynıdır.
