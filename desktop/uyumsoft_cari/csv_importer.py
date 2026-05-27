from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .db import (
    EFFECT_CREDIT,
    EFFECT_DEBIT,
    SOURCE_INCOMING_INVOICE,
    SOURCE_OUTGOING_INVOICE,
    LedgerDatabase,
    is_leasing_company,
)


INCOMING_HEADERS = [
    "Fatura No",
    "Doküman No",
    "Fatura Tarihi",
    "Oluşturulma Tarihi",
    "Gönderici VKN/TCKN",
    "Gönderici",
    "PK(gb)",
    "Ödenecek Tutar",
    "%0 KDV Matrah Tutar",
    "KDV %1 Tutar",
    "%1 KDV Matrah Tutar",
    "KDV %8 Tutar",
    "%8 KDV Matrah Tutar",
    "KDV %10 Tutar",
    "%10 KDV Matrah Tutar",
    "KDV %18 Tutar",
    "%18 KDV Matrah Tutar",
    "KDV %20 Tutar",
    "%20 KDV Matrah Tutar",
    "Toplam KDV",
    "Vergiler Hariç Toplam Tutar",
    "Para Birimi",
    "Döviz Kuru",
    "Senaryo Tipi",
    "Fatura Tipi",
    "Fatura Durumu",
    "Web Servisten Okundu Mu",
    "Sipariş Numarası",
    "Zarf Id",
    "Zarf Durumu Kodu",
    "Hash Kodu",
    "İskonto Tutarı",
    "Ülke",
    "Şehir",
    "",
]

OUTGOING_HEADERS = [
    "Fatura No",
    "Doküman No",
    "Fatura Tarihi",
    "Oluşturulma Tarihi",
    "Alıcı VKN/TCKN",
    "Alıcı",
    "PK(gb)",
    "Ödenecek Tutar",
    "%0 KDV Matrah Tutar",
    "KDV %1 Tutar",
    "%1 KDV Matrah Tutar",
    "KDV %8 Tutar",
    "%8 KDV Matrah Tutar",
    "KDV %10 Tutar",
    "%10 KDV Matrah Tutar",
    "KDV %18 Tutar",
    "%18 KDV Matrah Tutar",
    "KDV %20 Tutar",
    "%20 KDV Matrah Tutar",
    "Toplam KDV",
    "Vergiler Hariç Toplam Tutar",
    "Para Birimi",
    "Döviz Kuru",
    "Senaryo Tipi",
    "Fatura Tipi",
    "Senaryo",
    "Kağıt/Elektronik",
    "Fatura Durumu",
    "Sipariş Numarası",
    "ERP Fatura Numarası",
    "Zarf Id",
    "Zarf Durumu Kodu",
    "Hash Kodu",
    "İskonto Tutarı",
    "Ülke",
    "Şehir",
    "",
]


@dataclass(frozen=True)
class ImportProfile:
    name: str
    headers: list[str]
    source_type: str
    account_effect: str
    party_tax_column: str
    party_name_column: str


INCOMING_PROFILE = ImportProfile(
    name="Gelen Fatura",
    headers=INCOMING_HEADERS,
    source_type=SOURCE_INCOMING_INVOICE,
    account_effect=EFFECT_CREDIT,
    party_tax_column="Gönderici VKN/TCKN",
    party_name_column="Gönderici",
)
OUTGOING_PROFILE = ImportProfile(
    name="Giden Fatura",
    headers=OUTGOING_HEADERS,
    source_type=SOURCE_OUTGOING_INVOICE,
    account_effect=EFFECT_DEBIT,
    party_tax_column="Alıcı VKN/TCKN",
    party_name_column="Alıcı",
)


@dataclass
class ImportResult:
    profile_name: str
    total_rows: int = 0
    imported_rows: int = 0
    skipped_duplicates: int = 0
    skipped_blacklisted_leasing: int = 0
    failed_rows: int = 0
    errors: list[str] = field(default_factory=list)


class CsvImportError(ValueError):
    pass


def clean_cell(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lstrip("'").strip()


def parse_decimal(value: str | None) -> float:
    text = clean_cell(value)
    if not text:
        return 0.0
    text = text.replace(".", "").replace(",", ".")
    return float(text)


def parse_uyumsoft_datetime(value: str | None) -> tuple[str, str]:
    text = clean_cell(value)
    if not text:
        raise ValueError("Tarih boş")
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date().isoformat(), parsed.isoformat(sep=" ", timespec="seconds")
        except ValueError:
            continue
    raise ValueError(f"Tarih formatı okunamadı: {text}")


def parse_user_date(value: str) -> str:
    text = clean_cell(value)
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Tarih gg.aa.yyyy formatında olmalı")


def format_user_date_from_iso(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.strftime("%d.%m.%Y")


def amount_try(amount: float, currency: str, exchange_rate: float) -> float:
    currency = currency.upper().strip() or "TRY"
    if currency == "TRY" and exchange_rate <= 0:
        exchange_rate = 1.0
    if exchange_rate <= 0:
        exchange_rate = 1.0
    return round(amount * exchange_rate, 4)


def detect_profile(headers: list[str], preferred: str | None = None) -> ImportProfile:
    normalized = [h.strip() for h in headers]
    profiles = [INCOMING_PROFILE, OUTGOING_PROFILE]
    if preferred:
        preferred_lower = preferred.lower()
        profiles = sorted(profiles, key=lambda p: p.name.lower() != preferred_lower)

    for profile in profiles:
        if normalized == profile.headers:
            return profile

    # Give a clearer error when the user picked the wrong file type.
    required_sets = {
        INCOMING_PROFILE.name: {"Gönderici VKN/TCKN", "Gönderici", "Ödenecek Tutar", "Döviz Kuru"},
        OUTGOING_PROFILE.name: {"Alıcı VKN/TCKN", "Alıcı", "Ödenecek Tutar", "Döviz Kuru"},
    }
    for profile in profiles:
        if required_sets[profile.name].issubset(set(normalized)):
            return profile

    raise CsvImportError(
        "CSV başlıkları beklenen Uyumsoft Gelen/Giden Fatura yapısıyla eşleşmiyor."
    )


def read_rows(path: Path | str) -> tuple[list[str], list[dict[str, str]]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        if reader.fieldnames is None:
            raise CsvImportError("CSV dosyasında başlık satırı bulunamadı.")
        rows = list(reader)
    return reader.fieldnames, rows


def import_uyumsoft_csv(
    db: LedgerDatabase,
    path: Path | str,
    preferred_profile: str | None = None,
) -> ImportResult:
    headers, rows = read_rows(path)
    profile = detect_profile(headers, preferred_profile)
    result = ImportResult(profile_name=profile.name, total_rows=len(rows))

    for index, row in enumerate(rows, start=2):
        try:
            tax_id = clean_cell(row.get(profile.party_tax_column))
            name = clean_cell(row.get(profile.party_name_column))
            if profile.source_type == SOURCE_INCOMING_INVOICE and is_leasing_company(name):
                result.skipped_blacklisted_leasing += 1
                continue
            company_id = db.upsert_company(
                name=name,
                tax_id=tax_id,
                pk_gb=clean_cell(row.get("PK(gb)")),
                country=clean_cell(row.get("Ülke")),
                city=clean_cell(row.get("Şehir")),
            )
            invoice_no = clean_cell(row.get("Fatura No"))
            document_no = clean_cell(row.get("Doküman No"))
            external_key = document_no or invoice_no
            if not external_key:
                raise ValueError("Fatura No ve Doküman No boş")

            txn_date, txn_datetime = parse_uyumsoft_datetime(row.get("Fatura Tarihi"))
            original_amount = parse_decimal(row.get("Ödenecek Tutar"))
            currency = clean_cell(row.get("Para Birimi")) or "TRY"
            rate = parse_decimal(row.get("Döviz Kuru"))
            try_amount = amount_try(original_amount, currency, rate)
            tax_try = amount_try(parse_decimal(row.get("Toplam KDV")), currency, rate)
            net_try = amount_try(parse_decimal(row.get("Vergiler Hariç Toplam Tutar")), currency, rate)

            raw_payload = {key: clean_cell(value) for key, value in row.items() if key is not None}
            inserted = db.add_transaction(
                company_id=company_id,
                source_type=profile.source_type,
                account_effect=profile.account_effect,
                txn_date=txn_date,
                txn_datetime=txn_datetime,
                invoice_no=invoice_no,
                document_no=document_no,
                external_key=external_key,
                description=f"{profile.name}: {invoice_no}",
                amount_original=original_amount,
                currency=currency,
                exchange_rate=rate if rate > 0 else (1.0 if currency.upper() == "TRY" else 1.0),
                amount_try=try_amount,
                tax_amount_try=tax_try,
                net_amount_try=net_try,
                raw=raw_payload,
            )
            if inserted:
                result.imported_rows += 1
            else:
                result.skipped_duplicates += 1
        except Exception as exc:
            result.failed_rows += 1
            result.errors.append(f"Satır {index}: {exc}")

    return result
