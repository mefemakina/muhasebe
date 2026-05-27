"""
Test için Uyumsoft Gelen/Giden Fatura CSV'sine birebir uyumlu sentetik fixture üretir.
Çalıştırma:
    python3 desktop/tools/generate_test_fixtures.py
Çıktı:
    desktop/tests/fixtures/GELEN-FATURA-Fatura_Listesi-27.05.2026_00_04_25_6afe.csv
    desktop/tests/fixtures/G_DEN-FATURA-Fatura_Listesi-27.05.2026_00_15_54_6840.csv

Veri tamamen senteziktir; hiçbir gerçek müşteri/firma bilgisi içermez.
"""
from __future__ import annotations

import csv
from pathlib import Path


def tr_amount(value: float) -> str:
    """TR formatı: 1.234,56"""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


OUTGOING_HEADERS = [
    "Fatura No", "Doküman No", "Fatura Tarihi", "Oluşturulma Tarihi",
    "Alıcı VKN/TCKN", "Alıcı", "PK(gb)", "Ödenecek Tutar",
    "%0 KDV Matrah Tutar", "KDV %1 Tutar", "%1 KDV Matrah Tutar",
    "KDV %8 Tutar", "%8 KDV Matrah Tutar", "KDV %10 Tutar", "%10 KDV Matrah Tutar",
    "KDV %18 Tutar", "%18 KDV Matrah Tutar", "KDV %20 Tutar", "%20 KDV Matrah Tutar",
    "Toplam KDV", "Vergiler Hariç Toplam Tutar", "Para Birimi", "Döviz Kuru",
    "Senaryo Tipi", "Fatura Tipi", "Senaryo", "Kağıt/Elektronik", "Fatura Durumu",
    "Sipariş Numarası", "ERP Fatura Numarası", "Zarf Id", "Zarf Durumu Kodu",
    "Hash Kodu", "İskonto Tutarı", "Ülke", "Şehir", "",
]

INCOMING_HEADERS = [
    "Fatura No", "Doküman No", "Fatura Tarihi", "Oluşturulma Tarihi",
    "Gönderici VKN/TCKN", "Gönderici", "PK(gb)", "Ödenecek Tutar",
    "%0 KDV Matrah Tutar", "KDV %1 Tutar", "%1 KDV Matrah Tutar",
    "KDV %8 Tutar", "%8 KDV Matrah Tutar", "KDV %10 Tutar", "%10 KDV Matrah Tutar",
    "KDV %18 Tutar", "%18 KDV Matrah Tutar", "KDV %20 Tutar", "%20 KDV Matrah Tutar",
    "Toplam KDV", "Vergiler Hariç Toplam Tutar", "Para Birimi", "Döviz Kuru",
    "Senaryo Tipi", "Fatura Tipi", "Fatura Durumu", "Web Servisten Okundu Mu",
    "Sipariş Numarası", "Zarf Id", "Zarf Durumu Kodu",
    "Hash Kodu", "İskonto Tutarı", "Ülke", "Şehir", "",
]


def outgoing_row(*, no, date, vkn, name, gross, currency="TRY", rate="0,00000000"):
    """KDV %20 senaryosu: net = gross / 1.20, kdv = gross - net."""
    net = round(gross / 1.20, 2)
    kdv20 = round(gross - net, 2)
    return [
        no, no, date, date, vkn, name, "", tr_amount(gross),
        "0,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00",
        "0,00", "0,00", tr_amount(kdv20), tr_amount(net),
        tr_amount(kdv20), tr_amount(net), currency, rate,
        "TEMELFATURA", "SATIS", "TEMELFATURA", "Elektronik", "Onaylandi",
        "", "", "", "00", "", "0,00", "Türkiye", "İSTANBUL", "",
    ]


def incoming_row(*, no, date, vkn, name, gross, currency="TRY", rate="0,00000000"):
    net = round(gross / 1.20, 2)
    kdv20 = round(gross - net, 2)
    return [
        no, no, date, date, vkn, name, "", tr_amount(gross),
        "0,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00",
        "0,00", "0,00", tr_amount(kdv20), tr_amount(net),
        tr_amount(kdv20), tr_amount(net), currency, rate,
        "TEMELFATURA", "SATIS", "Onaylandi", "Evet",
        "", "", "00", "", "0,00", "Türkiye", "ANKARA", "",
    ]


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


def main() -> None:
    fixtures_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

    # GIDEN FATURALAR - tutarlar test kontrolleriyle uyumlu
    # COCA COLA VKN 6110008160 zorunlu (test_imports_sample_csv_files_and_dashboard_math)
    outgoing_rows = [
        # 2026-05-18: range dışı (kontrol)
        outgoing_row(no="GF2026001", date="18.05.2026 09:00:00",
                     vkn="6110008160", name="COCA COLA SATIS VE DAGITIM A.S.",
                     gross=12000.00),
        # 2026-05-22: range içi (2026-05-20 - 2026-05-23)
        outgoing_row(no="GF2026002", date="22.05.2026 10:00:00",
                     vkn="1234567890", name="ABC MAKINA SAN. TIC. LTD.",
                     gross=24000.00),
        # 2026-05-23: range içi sınır
        outgoing_row(no="GF2026003", date="23.05.2026 14:00:00",
                     vkn="2345678901", name="XYZ ENDUSTRI A.S.",
                     gross=36000.00),
        # 2026-05-26: range dışı
        outgoing_row(no="GF2026004", date="26.05.2026 11:00:00",
                     vkn="3456789012", name="DEMIR CELIK SANAYI",
                     gross=48000.00),
        # USD fatura: kur 30
        outgoing_row(no="GF2026005", date="20.05.2026 15:30:00",
                     vkn="4567890123", name="GLOBAL TRADE EXPORT",
                     gross=1000.00, currency="USD", rate="30,00000000"),
        # 2025 yıl karşılaştırma için
        outgoing_row(no="GF2025001", date="15.11.2025 09:00:00",
                     vkn="5678901234", name="ESKI MUSTERI A.S.",
                     gross=18000.00),
        # 2024
        outgoing_row(no="GF2024001", date="20.06.2024 09:00:00",
                     vkn="6789012345", name="DAHA ESKI MUSTERI",
                     gross=9000.00),
    ]

    # GELEN FATURALAR - leasing dahil
    incoming_rows = [
        # Normal tedarikçi
        incoming_row(no="IF2026001", date="19.05.2026 10:00:00",
                     vkn="7890123456", name="ELEKTRIK TEDARIKCISI A.S.",
                     gross=6000.00),
        incoming_row(no="IF2026002", date="21.05.2026 11:30:00",
                     vkn="8901234567", name="MALZEME TEDARIKCISI LTD.",
                     gross=12000.00),
        # LEASING - blacklist test
        incoming_row(no="LE2026001", date="20.05.2026 09:00:00",
                     vkn="0600047109", name="ALTERNATİF FİNANSAL KİRALAMA ANONİM ŞİRKETİ",
                     gross=8400.00),
        incoming_row(no="LE2026002", date="22.05.2026 09:00:00",
                     vkn="0700057209", name="GLOBAL LEASING A.S.",
                     gross=5500.00),
        # EUR tedarikçi
        incoming_row(no="IF2026003", date="23.05.2026 16:00:00",
                     vkn="9012345678", name="EU SUPPLIER GMBH",
                     gross=500.00, currency="EUR", rate="35,00000000"),
    ]

    write_csv(
        fixtures_dir / "G_DEN-FATURA-Fatura_Listesi-27.05.2026_00_15_54_6840.csv",
        OUTGOING_HEADERS, outgoing_rows,
    )
    write_csv(
        fixtures_dir / "GELEN-FATURA-Fatura_Listesi-27.05.2026_00_04_25_6afe.csv",
        INCOMING_HEADERS, incoming_rows,
    )
    print(f"Fixture'lar yazıldı: {fixtures_dir}")
    print(f"  Giden: {len(outgoing_rows)} satır")
    print(f"  Gelen: {len(incoming_rows)} satır (içinde 2 leasing)")


if __name__ == "__main__":
    main()
