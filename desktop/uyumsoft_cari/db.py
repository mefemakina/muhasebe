from __future__ import annotations

import json
import os
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


APP_NAME = "MEFE Uyumsoft Cari"

SOURCE_OUTGOING_INVOICE = "outgoing_invoice"
SOURCE_INCOMING_INVOICE = "incoming_invoice"
SOURCE_MANUAL_PAYMENT = "manual_payment"
SOURCE_MANUAL_COLLECTION = "manual_collection"
SOURCE_PERIOD_CARRYOVER = "period_carryover"

# Stored values stay short for SQLite compatibility:
# debit = BORÇ, credit = ALACAK.
EFFECT_DEBIT = "debit"
EFFECT_CREDIT = "credit"


@dataclass(frozen=True)
class Company:
    id: int
    name: str
    tax_id: str


@dataclass(frozen=True)
class DashboardTotals:
    market_receivable_try: float
    current_payable_try: float
    net_financial_position_try: float
    period_carryover_try: float
    outgoing_invoices_try: float
    incoming_invoices_try: float
    outgoing_invoices_net_try: float
    incoming_invoices_net_try: float
    manual_payments_try: float
    manual_collections_try: float
    company_count: int
    transaction_count: int


@dataclass(frozen=True)
class OpenInvoice:
    company_id: int
    company_name: str
    tax_id: str
    source_type: str
    account_effect: str
    txn_date: str
    invoice_no: str
    document_no: str
    amount_try: float
    remaining_try: float
    currency: str
    raw_json: str


@dataclass(frozen=True)
class PeriodCloseResult:
    closing_date: str
    period_start_date: str
    carryover_amount_try: float
    open_invoice_count: int
    open_invoice_total_try: float


@dataclass(frozen=True)
class CsvResetResult:
    deleted_transactions: int
    deleted_orphan_companies: int


@dataclass(frozen=True)
class PeriodCarryoverResetResult:
    deleted_transactions: int
    deleted_period_closures: int
    deleted_orphan_companies: int


@dataclass(frozen=True)
class OutgoingInvoiceStatus:
    transaction_id: int
    company_id: int
    company_name: str
    tax_id: str
    txn_date: str
    invoice_no: str
    amount_original: float
    currency: str
    amount_try: float
    collected_try: float
    remaining_original: float
    remaining_try: float
    is_paid: bool


@dataclass(frozen=True)
class CompanyCurrencySummary:
    company_id: int
    currency: str
    debit_original: float
    credit_original: float


@dataclass(frozen=True)
class CompanyTurnoverSummary:
    company_name: str
    tax_id: str
    gross_try: float
    net_try: float
    share_percent: float


LEASING_KEYWORDS = ("leasing", "lease", "finansal kiralama", "alternatif finansal kiralama")


def is_leasing_company(name: str) -> bool:
    normalized = unicodedata.normalize("NFKD", name.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return any(keyword in normalized for keyword in LEASING_KEYWORDS)


def default_database_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data) / "MEFE" / "UyumsoftCari"
    else:
        base = Path.home() / ".mefe_uyumsoft_cari"
    base.mkdir(parents=True, exist_ok=True)
    return base / "uyumsoft_cari.sqlite3"


def today_iso() -> str:
    return date.today().isoformat()


class LedgerDatabase:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else default_database_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tax_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                pk_gb TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(tax_id, name)
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL,
                account_effect TEXT NOT NULL CHECK(account_effect IN ('debit', 'credit')),
                txn_date TEXT NOT NULL,
                txn_datetime TEXT NOT NULL DEFAULT '',
                invoice_no TEXT NOT NULL DEFAULT '',
                document_no TEXT NOT NULL DEFAULT '',
                external_key TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                amount_original REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'TRY',
                exchange_rate REAL NOT NULL DEFAULT 1,
                amount_try REAL NOT NULL,
                tax_amount_try REAL NOT NULL DEFAULT 0,
                net_amount_try REAL NOT NULL DEFAULT 0,
                is_leasing INTEGER NOT NULL DEFAULT 0,
                leasing_principal_try REAL NOT NULL DEFAULT 0,
                leasing_interest_try REAL NOT NULL DEFAULT 0,
                leasing_vat_try REAL NOT NULL DEFAULT 0,
                raw_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(source_type, external_key)
            );

            CREATE TABLE IF NOT EXISTS period_closures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                closing_date TEXT NOT NULL,
                period_start_date TEXT NOT NULL,
                carryover_amount_try REAL NOT NULL,
                open_invoice_count INTEGER NOT NULL,
                open_invoice_total_try REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_company_date
                ON transactions(company_id, txn_date);
            CREATE INDEX IF NOT EXISTS idx_transactions_source_date
                ON transactions(source_type, txn_date);
            """
        )
        self._ensure_transaction_columns()
        self.delete_blacklisted_leasing_records()
        self._normalize_account_effects()
        self.conn.commit()

    def _ensure_transaction_columns(self) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(transactions)").fetchall()
        }
        columns = {
            "is_leasing": "INTEGER NOT NULL DEFAULT 0",
            "leasing_principal_try": "REAL NOT NULL DEFAULT 0",
            "leasing_interest_try": "REAL NOT NULL DEFAULT 0",
            "leasing_vat_try": "REAL NOT NULL DEFAULT 0",
            # Otomatik "ödendi" kayıtlarını indexli kolondan ayırt etmek için
            # (eskiden raw_json LIKE '%auto_paid_invoice_id%' kullanılıyordu).
            "is_auto_paid": "INTEGER NOT NULL DEFAULT 0",
            "auto_paid_invoice_id": "INTEGER",
        }
        for name, definition in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE transactions ADD COLUMN {name} {definition}")
        # Eski kayıtları yeni kolonlara taşı (idempotent migration).
        self.conn.execute(
            """
            UPDATE transactions
            SET is_auto_paid = 1
            WHERE is_auto_paid = 0
              AND source_type = 'manual_collection'
              AND raw_json LIKE '%auto_paid_invoice_id%'
            """
        )
        # auto_paid_invoice_id alanını raw_json'dan çıkarıp doldurmak için Python ile döneriz.
        rows_to_backfill = self.conn.execute(
            """
            SELECT id, raw_json
            FROM transactions
            WHERE is_auto_paid = 1 AND (auto_paid_invoice_id IS NULL OR auto_paid_invoice_id = 0)
            """
        ).fetchall()
        for row in rows_to_backfill:
            try:
                payload = json.loads(row["raw_json"] or "{}")
                inv_id = payload.get("auto_paid_invoice_id")
                if inv_id is not None:
                    self.conn.execute(
                        "UPDATE transactions SET auto_paid_invoice_id = ? WHERE id = ?",
                        (int(inv_id), int(row["id"])),
                    )
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transactions_auto_paid ON transactions(is_auto_paid, auto_paid_invoice_id)"
        )

    def _normalize_account_effects(self) -> None:
        # Earlier drafts used debit/credit with accounting-book terminology.
        # Keep any existing database aligned with the now explicit business rule:
        # giden fatura = BORÇ, gelen fatura = ALACAK.
        self.conn.execute(
            """
            UPDATE transactions
            SET account_effect = CASE
                WHEN source_type IN ('outgoing_invoice', 'manual_payment') THEN 'debit'
                WHEN source_type IN ('incoming_invoice', 'manual_collection') THEN 'credit'
                ELSE account_effect
            END
            """
        )

    def upsert_company(
        self,
        *,
        name: str,
        tax_id: str = "",
        pk_gb: str = "",
        country: str = "",
        city: str = "",
    ) -> int:
        name = name.strip() or "Isimsiz Cari"
        if is_leasing_company(name):
            raise ValueError("Leasing/finansal kiralama firmaları kara listededir ve sisteme kaydedilemez.")
        tax_id = tax_id.strip().lstrip("'")
        now = datetime.now().isoformat(timespec="seconds")
        row = self.conn.execute(
            """
            SELECT id FROM companies
            WHERE tax_id = ? AND name = ?
            """,
            (tax_id, name),
        ).fetchone()
        if row:
            self.conn.execute(
                """
                UPDATE companies
                SET pk_gb = COALESCE(NULLIF(?, ''), pk_gb),
                    country = COALESCE(NULLIF(?, ''), country),
                    city = COALESCE(NULLIF(?, ''), city),
                    updated_at = ?
                WHERE id = ?
                """,
                (pk_gb.strip(), country.strip(), city.strip(), now, row["id"]),
            )
            self.conn.commit()
            return int(row["id"])

        cur = self.conn.execute(
            """
            INSERT INTO companies (tax_id, name, pk_gb, country, city, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tax_id, name, pk_gb.strip(), country.strip(), city.strip(), now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_transaction(
        self,
        *,
        company_id: int,
        source_type: str,
        account_effect: str,
        txn_date: str,
        amount_original: float,
        currency: str,
        exchange_rate: float,
        amount_try: float,
        external_key: str,
        txn_datetime: str = "",
        invoice_no: str = "",
        document_no: str = "",
        description: str = "",
        tax_amount_try: float = 0,
        net_amount_try: float = 0,
        is_leasing: bool = False,
        leasing_principal_try: float = 0,
        leasing_interest_try: float = 0,
        leasing_vat_try: float = 0,
        raw: dict[str, Any] | None = None,
    ) -> bool:
        company = self.conn.execute("SELECT name FROM companies WHERE id = ?", (company_id,)).fetchone()
        if company is not None and is_leasing_company(company["name"]):
            raise ValueError("Leasing/finansal kiralama firmaları sisteme kaydedilemez.")
        now = datetime.now().isoformat(timespec="seconds")
        raw_payload = raw or {}
        raw_json = json.dumps(raw_payload, ensure_ascii=False)
        auto_paid_invoice_id = raw_payload.get("auto_paid_invoice_id")
        is_auto_paid = 1 if auto_paid_invoice_id is not None else 0
        try:
            auto_paid_invoice_id = int(auto_paid_invoice_id) if auto_paid_invoice_id is not None else None
        except (TypeError, ValueError):
            auto_paid_invoice_id = None
            is_auto_paid = 0
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO transactions (
                company_id, source_type, account_effect, txn_date, txn_datetime,
                invoice_no, document_no, external_key, description,
                amount_original, currency, exchange_rate, amount_try,
                tax_amount_try, net_amount_try, is_leasing,
                leasing_principal_try, leasing_interest_try, leasing_vat_try,
                is_auto_paid, auto_paid_invoice_id,
                raw_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                source_type,
                account_effect,
                txn_date,
                txn_datetime,
                invoice_no,
                document_no,
                external_key,
                description,
                float(amount_original),
                currency.upper().strip() or "TRY",
                float(exchange_rate),
                float(amount_try),
                float(tax_amount_try),
                float(net_amount_try),
                1 if is_leasing else 0,
                float(leasing_principal_try),
                float(leasing_interest_try),
                float(leasing_vat_try),
                is_auto_paid,
                auto_paid_invoice_id,
                raw_json,
                now,
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_companies(self) -> list[Company]:
        rows = self.conn.execute(
            """
            SELECT id, name, tax_id
            FROM companies
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        return [Company(id=int(r["id"]), name=r["name"], tax_id=r["tax_id"]) for r in rows]

    def delete_blacklisted_leasing_records(self) -> int:
        rows = self.conn.execute("SELECT id, name FROM companies").fetchall()
        blacklisted_ids = [int(row["id"]) for row in rows if is_leasing_company(row["name"])]
        if not blacklisted_ids:
            return 0
        placeholders = ",".join("?" for _ in blacklisted_ids)
        tx_count = self.conn.execute(
            f"SELECT COUNT(*) AS count FROM transactions WHERE company_id IN ({placeholders})",
            blacklisted_ids,
        ).fetchone()["count"]
        self.conn.execute(f"DELETE FROM transactions WHERE company_id IN ({placeholders})", blacklisted_ids)
        self.conn.execute(f"DELETE FROM companies WHERE id IN ({placeholders})", blacklisted_ids)
        self.conn.commit()
        return int(tx_count)

    def csv_transaction_count(self) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM transactions
            WHERE source_type IN (?, ?)
            """,
            (SOURCE_OUTGOING_INVOICE, SOURCE_INCOMING_INVOICE),
        ).fetchone()
        return int(row["count"])

    def reset_imported_csv_transactions(self) -> CsvResetResult:
        count_before = self.csv_transaction_count()
        self.conn.execute(
            """
            DELETE FROM transactions
            WHERE source_type IN (?, ?)
            """,
            (SOURCE_OUTGOING_INVOICE, SOURCE_INCOMING_INVOICE),
        )
        self.conn.execute(
            """
            DELETE FROM transactions
            WHERE source_type = ?
              AND is_auto_paid = 1
            """,
            (SOURCE_MANUAL_COLLECTION,),
        )
        cur = self.conn.execute(
            """
            DELETE FROM companies
            WHERE NOT EXISTS (
                SELECT 1 FROM transactions WHERE transactions.company_id = companies.id
            )
            """
        )
        self.conn.commit()
        return CsvResetResult(
            deleted_transactions=count_before,
            deleted_orphan_companies=int(cur.rowcount if cur.rowcount is not None else 0),
        )

    def period_carryover_count(self) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM transactions
            WHERE source_type = ?
            """,
            (SOURCE_PERIOD_CARRYOVER,),
        ).fetchone()
        return int(row["count"])

    def active_period_start_date(self) -> str | None:
        row = self.conn.execute(
            """
            SELECT MAX(period_start_date) AS period_start_date
            FROM period_closures
            """
        ).fetchone()
        if row and row["period_start_date"]:
            return str(row["period_start_date"])
        tx_row = self.conn.execute(
            """
            SELECT MAX(txn_date) AS period_start_date
            FROM transactions
            WHERE source_type = ?
            """,
            (SOURCE_PERIOD_CARRYOVER,),
        ).fetchone()
        if tx_row and tx_row["period_start_date"]:
            return str(tx_row["period_start_date"])
        return None

    def reset_period_carryover_data(self) -> PeriodCarryoverResetResult:
        transaction_count = self.period_carryover_count()
        closure_row = self.conn.execute("SELECT COUNT(*) AS count FROM period_closures").fetchone()
        closure_count = int(closure_row["count"])
        self.conn.execute(
            """
            DELETE FROM transactions
            WHERE source_type = ?
            """,
            (SOURCE_PERIOD_CARRYOVER,),
        )
        self.conn.execute("DELETE FROM period_closures")
        cur = self.conn.execute(
            """
            DELETE FROM companies
            WHERE NOT EXISTS (
                SELECT 1 FROM transactions WHERE transactions.company_id = companies.id
            )
            """
        )
        self.conn.commit()
        return PeriodCarryoverResetResult(
            deleted_transactions=transaction_count,
            deleted_period_closures=closure_count,
            deleted_orphan_companies=int(cur.rowcount if cur.rowcount is not None else 0),
        )

    def _date_filter(self, alias: str, start_date: str | None, end_date: str | None) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if start_date:
            clauses.append(f"{alias}.txn_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append(f"{alias}.txn_date <= ?")
            params.append(end_date)
        if not clauses:
            return "", params
        return "AND " + " AND ".join(clauses), params

    def company_summaries(
        self,
        as_of: str | None = None,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[sqlite3.Row]:
        params: list[Any] = []
        date_filter = ""
        if as_of:
            date_filter = "AND t.txn_date <= ?"
            params.append(as_of)
        elif start_date or end_date:
            date_filter, params = self._date_filter("t", start_date, end_date)

        rows = self.conn.execute(
            f"""
            SELECT
                c.id,
                c.name,
                c.tax_id,
                COALESCE(SUM(CASE WHEN t.account_effect = 'debit' THEN t.amount_try ELSE 0 END), 0) AS debit_try,
                COALESCE(SUM(CASE WHEN t.account_effect = 'credit' THEN t.amount_try ELSE 0 END), 0) AS credit_try,
                COALESCE(SUM(CASE WHEN t.account_effect = 'debit' THEN t.amount_try ELSE -t.amount_try END), 0) AS balance_try,
                MAX(t.txn_date) AS last_txn_date,
                COALESCE(SUM(CASE WHEN t.source_type IN ('outgoing_invoice', 'incoming_invoice') THEN 1 ELSE 0 END), 0) AS invoice_transaction_count,
                COUNT(t.id) AS transaction_count
            FROM companies c
            LEFT JOIN transactions t ON t.company_id = c.id {date_filter}
            GROUP BY c.id, c.name, c.tax_id
            ORDER BY c.name COLLATE NOCASE
            """,
            params,
        ).fetchall()
        filtered_rows = [row for row in rows if not is_leasing_company(row["name"])]
        if start_date or end_date:
            return [row for row in filtered_rows if int(row["invoice_transaction_count"]) > 0]
        return filtered_rows

    def company_currency_summaries(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[int, list[CompanyCurrencySummary]]:
        date_filter, params = self._date_filter("t", start_date, end_date)
        rows = self.conn.execute(
            f"""
            SELECT
                t.company_id,
                t.currency,
                COALESCE(SUM(CASE WHEN t.account_effect = 'debit' THEN t.amount_original ELSE 0 END), 0) AS debit_original,
                COALESCE(SUM(CASE WHEN t.account_effect = 'credit' THEN t.amount_original ELSE 0 END), 0) AS credit_original
            FROM transactions t
            WHERE t.currency IN ('USD', 'EUR')
              {date_filter}
            GROUP BY t.company_id, t.currency
            """,
            params,
        ).fetchall()
        result: dict[int, list[CompanyCurrencySummary]] = {}
        for row in rows:
            item = CompanyCurrencySummary(
                company_id=int(row["company_id"]),
                currency=row["currency"],
                debit_original=float(row["debit_original"]),
                credit_original=float(row["credit_original"]),
            )
            result.setdefault(item.company_id, []).append(item)
        return result

    def dashboard_totals(
        self,
        as_of: str | None = None,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> DashboardTotals:
        if as_of and not end_date:
            end_date = as_of
        if not (start_date or end_date):
            end_date = today_iso()
        date_filter, params = self._date_filter("transactions", start_date, end_date)
        where_clause = date_filter.replace("AND ", "WHERE ", 1) if date_filter else ""
        rows = self.conn.execute(
            f"""
            SELECT
                source_type,
                account_effect,
                COALESCE(SUM(amount_try), 0) AS total,
                COALESCE(SUM(net_amount_try), 0) AS net_total,
                COALESCE(SUM(CASE
                    WHEN source_type = 'manual_collection' AND is_auto_paid = 1 THEN 0
                    ELSE amount_try
                END), 0) AS financial_total
            FROM transactions
            {where_clause}
            GROUP BY source_type, account_effect
            """,
            params,
        ).fetchall()
        by_source: dict[str, float] = {}
        by_source_net: dict[str, float] = {}
        by_source_financial: dict[str, float] = {}
        period_carryover = 0.0
        for row in rows:
            source_type = row["source_type"]
            total = float(row["total"])
            by_source[source_type] = by_source.get(source_type, 0.0) + total
            by_source_net[source_type] = by_source_net.get(source_type, 0.0) + float(row["net_total"])
            by_source_financial[source_type] = by_source_financial.get(source_type, 0.0) + float(row["financial_total"])
            if source_type == SOURCE_PERIOD_CARRYOVER:
                period_carryover += total if row["account_effect"] == EFFECT_DEBIT else -total

        outgoing = by_source.get(SOURCE_OUTGOING_INVOICE, 0.0)
        incoming = by_source.get(SOURCE_INCOMING_INVOICE, 0.0)
        outgoing_net = by_source_net.get(SOURCE_OUTGOING_INVOICE, 0.0)
        incoming_net = by_source_net.get(SOURCE_INCOMING_INVOICE, 0.0)
        payments = by_source.get(SOURCE_MANUAL_PAYMENT, 0.0)
        collections = by_source.get(SOURCE_MANUAL_COLLECTION, 0.0)
        financial_collections = by_source_financial.get(SOURCE_MANUAL_COLLECTION, 0.0)

        count_row = self.conn.execute(
            f"""
            SELECT
                (SELECT COUNT(*) FROM companies) AS company_count,
                (SELECT COUNT(*) FROM transactions {where_clause}) AS transaction_count
            """,
            params,
        ).fetchone()

        # Piyasa alacağı açık giden faturaların kalan bakiyesidir; otomatik/tekrarlı tahsilatlarla negatife düşmez.
        market_receivable = max(self.outgoing_receivable_balance(start_date=start_date, end_date=end_date), 0.0)

        # Tedarikçi borcu: bize gelen faturalar eksi bizim yaptığımız ödemeler.
        current_payable = incoming - payments
        # Net finansal durum KDV'siz fatura matrahlarıyla hesaplanır; devir gelen taraf gibi düşülür.
        net_position = (outgoing_net + payments) - (incoming_net + financial_collections + period_carryover)

        return DashboardTotals(
            market_receivable_try=market_receivable,
            current_payable_try=current_payable,
            net_financial_position_try=net_position,
            period_carryover_try=period_carryover,
            outgoing_invoices_try=outgoing,
            incoming_invoices_try=incoming,
            outgoing_invoices_net_try=outgoing_net,
            incoming_invoices_net_try=incoming_net,
            manual_payments_try=payments,
            manual_collections_try=collections,
            company_count=int(count_row["company_count"]),
            transaction_count=int(count_row["transaction_count"]),
        )

    def outgoing_receivable_balance(self, *, start_date: str | None = None, end_date: str | None = None) -> float:
        date_filter, params = self._date_filter("t", start_date, end_date)
        rows = self.conn.execute(
            f"""
            SELECT t.*
            FROM transactions t
            WHERE t.source_type IN (?, ?)
              {date_filter}
            ORDER BY t.company_id, t.txn_date, t.id
            """,
            [SOURCE_OUTGOING_INVOICE, SOURCE_MANUAL_COLLECTION, *params],
        ).fetchall()
        current_company: int | None = None
        invoices: list[dict[str, Any]] = []
        unapplied_collections = 0.0
        pending_auto_collections: dict[int, float] = {}
        total_remaining = 0.0

        def flush_company() -> None:
            nonlocal total_remaining
            for invoice in invoices:
                if invoice["remaining_try"] > 0.005:
                    total_remaining += float(invoice["remaining_try"])

        def apply_fifo(amount: float) -> float:
            remaining_amount = amount
            for invoice in invoices:
                if remaining_amount <= 0:
                    break
                applied = min(invoice["remaining_try"], remaining_amount)
                invoice["remaining_try"] -= applied
                remaining_amount -= applied
            return remaining_amount

        def apply_to_invoice(invoice_id: int, amount: float) -> float:
            for invoice in invoices:
                if int(invoice["id"]) == invoice_id:
                    applied = min(invoice["remaining_try"], amount)
                    invoice["remaining_try"] -= applied
                    return amount - applied
            return amount

        for row in rows:
            company_id = int(row["company_id"])
            if current_company is None:
                current_company = company_id
            if company_id != current_company:
                flush_company()
                current_company = company_id
                invoices = []
                unapplied_collections = 0.0
                pending_auto_collections = {}

            if row["source_type"] == SOURCE_OUTGOING_INVOICE:
                invoice = dict(row)
                invoice["remaining_try"] = float(row["amount_try"])
                pending_amount = pending_auto_collections.pop(int(row["id"]), 0.0)
                if pending_amount:
                    invoice["remaining_try"] -= min(invoice["remaining_try"], pending_amount)
                if unapplied_collections:
                    applied = min(invoice["remaining_try"], unapplied_collections)
                    invoice["remaining_try"] -= applied
                    unapplied_collections -= applied
                invoices.append(invoice)
            elif row["source_type"] == SOURCE_MANUAL_COLLECTION:
                try:
                    payload = json.loads(row["raw_json"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                auto_paid_id = payload.get("auto_paid_invoice_id")
                if auto_paid_id is not None:
                    remaining = apply_to_invoice(int(auto_paid_id), float(row["amount_try"]))
                    if remaining > 0:
                        pending_auto_collections[int(auto_paid_id)] = pending_auto_collections.get(int(auto_paid_id), 0.0) + remaining
                else:
                    unapplied_collections += apply_fifo(float(row["amount_try"]))

        if current_company is not None:
            flush_company()
        return round(max(total_remaining, 0.0), 4)

    def outgoing_invoice_years(self) -> list[int]:
        """Giden fatura kaydı olan benzersiz yılları azalan sırada döndürür."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT CAST(strftime('%Y', txn_date) AS INTEGER) AS year_no
            FROM transactions
            WHERE source_type = ?
            ORDER BY year_no DESC
            """,
            (SOURCE_OUTGOING_INVOICE,),
        ).fetchall()
        return [int(row["year_no"]) for row in rows if row["year_no"] is not None]

    def monthly_outgoing_net_totals(self, year: int) -> list[tuple[int, float]]:
        rows = self.conn.execute(
            """
            SELECT CAST(strftime('%m', txn_date) AS INTEGER) AS month_no,
                   COALESCE(SUM(net_amount_try), 0) AS total
            FROM transactions
            WHERE source_type = ?
              AND strftime('%Y', txn_date) = ?
            GROUP BY month_no
            """,
            (SOURCE_OUTGOING_INVOICE, str(year)),
        ).fetchall()
        totals = {int(row["month_no"]): float(row["total"]) for row in rows}
        return [(month_no, totals.get(month_no, 0.0)) for month_no in range(1, 13)]

    def yearly_outgoing_net_totals(self, years: list[int]) -> list[tuple[int, float]]:
        if not years:
            return []
        placeholders = ",".join("?" for _ in years)
        rows = self.conn.execute(
            f"""
            SELECT CAST(strftime('%Y', txn_date) AS INTEGER) AS year_no,
                   COALESCE(SUM(net_amount_try), 0) AS total
            FROM transactions
            WHERE source_type = ?
              AND CAST(strftime('%Y', txn_date) AS INTEGER) IN ({placeholders})
            GROUP BY year_no
            """,
            [SOURCE_OUTGOING_INVOICE, *years],
        ).fetchall()
        totals = {int(row["year_no"]): float(row["total"]) for row in rows}
        return [(year, totals.get(year, 0.0)) for year in years]

    def company_yearly_outgoing_turnover(self, year: int) -> list[CompanyTurnoverSummary]:
        rows = self.conn.execute(
            """
            SELECT c.name,
                   c.tax_id,
                   COALESCE(SUM(t.amount_try), 0) AS gross_try,
                   COALESCE(SUM(t.net_amount_try), 0) AS net_try
            FROM transactions t
            JOIN companies c ON c.id = t.company_id
            WHERE t.source_type = ?
              AND strftime('%Y', t.txn_date) = ?
            GROUP BY c.id, c.name, c.tax_id
            ORDER BY net_try DESC
            """,
            (SOURCE_OUTGOING_INVOICE, str(year)),
        ).fetchall()
        total_net = sum(float(row["net_try"]) for row in rows)
        return [
            CompanyTurnoverSummary(
                company_name=row["name"],
                tax_id=row["tax_id"],
                gross_try=float(row["gross_try"]),
                net_try=float(row["net_try"]),
                share_percent=(float(row["net_try"]) / total_net * 100) if total_net else 0.0,
            )
            for row in rows
        ]

    def balance_for_company(self, company_id: int, as_of: str) -> float:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN account_effect = 'debit' THEN amount_try ELSE -amount_try END), 0) AS balance
            FROM transactions
            WHERE company_id = ? AND txn_date <= ?
            """,
            (company_id, as_of),
        ).fetchone()
        return float(row["balance"])

    def transactions_for_company(self, company_id: int, as_of: str | None = None) -> list[sqlite3.Row]:
        params: list[Any] = [company_id]
        date_filter = ""
        if as_of:
            date_filter = "AND txn_date <= ?"
            params.append(as_of)
        return self.conn.execute(
            f"""
            SELECT *
            FROM transactions
            WHERE company_id = ? {date_filter}
            ORDER BY txn_date DESC, id DESC
            """,
            params,
        ).fetchall()

    def find_company_by_name(self, query: str) -> Company | None:
        normalized_query = " ".join(query.casefold().split())
        if not normalized_query:
            return None
        for company in self.list_companies():
            normalized_name = " ".join(company.name.casefold().split())
            if normalized_query in normalized_name or normalized_name.startswith(normalized_query):
                return company
        return None

    def open_invoices_as_of(self, closing_date: str) -> list[OpenInvoice]:
        rows = self.conn.execute(
            """
            SELECT t.*, c.name AS company_name, c.tax_id
            FROM transactions t
            JOIN companies c ON c.id = t.company_id
            WHERE t.txn_date <= ?
              AND t.source_type IN ('outgoing_invoice', 'incoming_invoice', 'manual_payment', 'manual_collection')
            ORDER BY t.company_id, t.txn_date, t.id
            """,
            (closing_date,),
        ).fetchall()

        result: list[OpenInvoice] = []
        current_company: int | None = None
        receivable_invoices: list[dict[str, Any]] = []
        payable_invoices: list[dict[str, Any]] = []
        unapplied_collections = 0.0
        unapplied_payments = 0.0
        pending_auto_collections: dict[int, float] = {}

        def apply_amount(invoices: list[dict[str, Any]], amount: float) -> float:
            remaining_amount = amount
            for invoice in invoices:
                if remaining_amount <= 0:
                    break
                applied = min(invoice["remaining_try"], remaining_amount)
                invoice["remaining_try"] -= applied
                remaining_amount -= applied
            return remaining_amount

        def apply_amount_to_invoice(invoices: list[dict[str, Any]], invoice_id: int, amount: float) -> float:
            for invoice in invoices:
                if int(invoice["id"]) == invoice_id:
                    applied = min(invoice["remaining_try"], amount)
                    invoice["remaining_try"] -= applied
                    return amount - applied
            return amount

        def flush_company() -> None:
            for invoice in [*receivable_invoices, *payable_invoices]:
                if invoice["remaining_try"] > 0.005:
                    result.append(
                        OpenInvoice(
                            company_id=int(invoice["company_id"]),
                            company_name=invoice["company_name"],
                            tax_id=invoice["tax_id"],
                            source_type=invoice["source_type"],
                            account_effect=invoice["account_effect"],
                            txn_date=invoice["txn_date"],
                            invoice_no=invoice["invoice_no"],
                            document_no=invoice["document_no"],
                            amount_try=float(invoice["amount_try"]),
                            remaining_try=round(float(invoice["remaining_try"]), 4),
                            currency=invoice["currency"],
                            raw_json=invoice["raw_json"],
                        )
                    )

        for row in rows:
            company_id = int(row["company_id"])
            if current_company is None:
                current_company = company_id
            if company_id != current_company:
                flush_company()
                current_company = company_id
                receivable_invoices = []
                payable_invoices = []
                unapplied_collections = 0.0
                unapplied_payments = 0.0
                pending_auto_collections = {}

            source_type = row["source_type"]
            if source_type == SOURCE_OUTGOING_INVOICE:
                invoice = dict(row)
                invoice["remaining_try"] = float(row["amount_try"])
                pending_amount = pending_auto_collections.pop(int(row["id"]), 0.0)
                if pending_amount:
                    applied = min(invoice["remaining_try"], pending_amount)
                    invoice["remaining_try"] -= applied
                if unapplied_collections:
                    applied = min(invoice["remaining_try"], unapplied_collections)
                    invoice["remaining_try"] -= applied
                    unapplied_collections -= applied
                receivable_invoices.append(invoice)
            elif source_type == SOURCE_INCOMING_INVOICE:
                invoice = dict(row)
                invoice["remaining_try"] = float(row["amount_try"])
                if unapplied_payments:
                    applied = min(invoice["remaining_try"], unapplied_payments)
                    invoice["remaining_try"] -= applied
                    unapplied_payments -= applied
                payable_invoices.append(invoice)
            elif source_type == SOURCE_MANUAL_COLLECTION:
                try:
                    payload = json.loads(row["raw_json"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                auto_paid_id = payload.get("auto_paid_invoice_id")
                if auto_paid_id is not None:
                    remaining = apply_amount_to_invoice(receivable_invoices, int(auto_paid_id), float(row["amount_try"]))
                    if remaining > 0:
                        pending_auto_collections[int(auto_paid_id)] = pending_auto_collections.get(int(auto_paid_id), 0.0) + remaining
                else:
                    unapplied_collections += apply_amount(receivable_invoices, float(row["amount_try"]))
            elif source_type == SOURCE_MANUAL_PAYMENT:
                unapplied_payments += apply_amount(payable_invoices, float(row["amount_try"]))

        if current_company is not None:
            flush_company()
        return result

    def outgoing_invoice_statuses(self) -> list[OutgoingInvoiceStatus]:
        rows = self.conn.execute(
            """
            SELECT t.*, c.name AS company_name, c.tax_id
            FROM transactions t
            JOIN companies c ON c.id = t.company_id
            WHERE t.source_type IN (?, ?)
            ORDER BY t.company_id, t.txn_date, t.id
            """,
            (SOURCE_OUTGOING_INVOICE, SOURCE_MANUAL_COLLECTION),
        ).fetchall()

        statuses: list[OutgoingInvoiceStatus] = []
        current_company: int | None = None
        invoices: list[dict[str, Any]] = []
        unapplied_collections = 0.0
        pending_auto_collections: dict[int, float] = {}

        def apply_collection(amount: float) -> float:
            remaining_amount = amount
            for invoice in invoices:
                if remaining_amount <= 0:
                    break
                applied = min(invoice["remaining_try"], remaining_amount)
                invoice["remaining_try"] -= applied
                remaining_amount -= applied
            return remaining_amount

        def apply_collection_to_invoice(invoice_id: int, amount: float) -> float:
            for invoice in invoices:
                if int(invoice["id"]) == invoice_id:
                    applied = min(invoice["remaining_try"], amount)
                    invoice["remaining_try"] -= applied
                    return amount - applied
            return amount

        def flush_company() -> None:
            for invoice in invoices:
                remaining = round(float(invoice["remaining_try"]), 4)
                amount = float(invoice["amount_try"])
                original_amount = float(invoice["amount_original"])
                remaining_original = (original_amount * remaining / amount) if amount else 0.0
                statuses.append(
                    OutgoingInvoiceStatus(
                        transaction_id=int(invoice["id"]),
                        company_id=int(invoice["company_id"]),
                        company_name=invoice["company_name"],
                        tax_id=invoice["tax_id"],
                        txn_date=invoice["txn_date"],
                        invoice_no=invoice["invoice_no"] or invoice["document_no"],
                        amount_original=original_amount,
                        currency=invoice["currency"],
                        amount_try=amount,
                        collected_try=round(amount - remaining, 4),
                        remaining_original=round(remaining_original, 4),
                        remaining_try=remaining,
                        is_paid=remaining <= 0.005,
                    )
                )

        for row in rows:
            company_id = int(row["company_id"])
            if current_company is None:
                current_company = company_id
            if company_id != current_company:
                flush_company()
                current_company = company_id
                invoices = []
                unapplied_collections = 0.0
                pending_auto_collections = {}

            if row["source_type"] == SOURCE_OUTGOING_INVOICE:
                invoice = dict(row)
                invoice["remaining_try"] = float(row["amount_try"])
                pending_amount = pending_auto_collections.pop(int(row["id"]), 0.0)
                if pending_amount:
                    applied = min(invoice["remaining_try"], pending_amount)
                    invoice["remaining_try"] -= applied
                if unapplied_collections:
                    applied = min(invoice["remaining_try"], unapplied_collections)
                    invoice["remaining_try"] -= applied
                    unapplied_collections -= applied
                invoices.append(invoice)
            elif row["source_type"] == SOURCE_MANUAL_COLLECTION:
                try:
                    payload = json.loads(row["raw_json"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                auto_paid_id = payload.get("auto_paid_invoice_id")
                if auto_paid_id is not None:
                    remaining = apply_collection_to_invoice(int(auto_paid_id), float(row["amount_try"]))
                    if remaining > 0:
                        pending_auto_collections[int(auto_paid_id)] = pending_auto_collections.get(int(auto_paid_id), 0.0) + remaining
                else:
                    unapplied_collections += apply_collection(float(row["amount_try"]))

        if current_company is not None:
            flush_company()
        return statuses

    def mark_outgoing_invoice_paid(self, transaction_id: int) -> float:
        target = None
        for status in self.outgoing_invoice_statuses():
            if status.transaction_id == transaction_id:
                target = status
                break
        if target is None:
            raise ValueError("Ödendi işaretlenecek giden fatura bulunamadı.")
        if target.remaining_try <= 0.005:
            return 0.0
        self.add_transaction(
            company_id=target.company_id,
            source_type=SOURCE_MANUAL_COLLECTION,
            account_effect=EFFECT_CREDIT,
            txn_date=today_iso(),
            txn_datetime=f"{today_iso()} 00:00:00",
            external_key=f"auto-paid-{transaction_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            description=f"Otomatik ödendi işareti: {target.invoice_no}",
            amount_original=target.remaining_try,
            currency="TRY",
            exchange_rate=1,
            amount_try=target.remaining_try,
            raw={
                "auto_paid_invoice_id": transaction_id,
                "auto_paid_invoice_no": target.invoice_no,
                "auto_paid_company_id": target.company_id,
            },
        )
        return target.remaining_try

    def mark_outgoing_invoices_paid_bulk(self, transaction_ids: list[int]) -> tuple[float, list[tuple[int, str]]]:
        """
        Birden fazla giden faturayı atomik olarak "ödendi" işaretler.
        Herhangi biri hata verirse hiçbiri kaydedilmez.
        Geri dönüş: (toplam_kapatılan_tl, [(invoice_id, hata_mesajı), ...])
        """
        statuses_by_id = {status.transaction_id: status for status in self.outgoing_invoice_statuses()}
        errors: list[tuple[int, str]] = []
        plan: list[tuple[int, "OutgoingInvoiceStatus"]] = []
        for tid in transaction_ids:
            status = statuses_by_id.get(int(tid))
            if status is None:
                errors.append((int(tid), "Fatura bulunamadı"))
                continue
            if status.remaining_try <= 0.005:
                continue  # zaten kapalı, sessizce atla
            plan.append((int(tid), status))
        if errors:
            return 0.0, errors
        total_paid = 0.0
        now_iso = today_iso()
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        try:
            with self.conn:
                for tid, target in plan:
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO transactions (
                            company_id, source_type, account_effect, txn_date, txn_datetime,
                            invoice_no, document_no, external_key, description,
                            amount_original, currency, exchange_rate, amount_try,
                            tax_amount_try, net_amount_try, is_leasing,
                            leasing_principal_try, leasing_interest_try, leasing_vat_try,
                            is_auto_paid, auto_paid_invoice_id,
                            raw_json, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            target.company_id,
                            SOURCE_MANUAL_COLLECTION,
                            EFFECT_CREDIT,
                            now_iso,
                            f"{now_iso} 00:00:00",
                            "",
                            "",
                            f"auto-paid-{tid}-{stamp}-{tid}",
                            f"Otomatik ödendi işareti: {target.invoice_no}",
                            float(target.remaining_try),
                            "TRY",
                            1.0,
                            float(target.remaining_try),
                            0.0,
                            0.0,
                            0,
                            0.0,
                            0.0,
                            0.0,
                            1,
                            int(tid),
                            json.dumps(
                                {
                                    "auto_paid_invoice_id": tid,
                                    "auto_paid_invoice_no": target.invoice_no,
                                    "auto_paid_company_id": target.company_id,
                                },
                                ensure_ascii=False,
                            ),
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                    total_paid += float(target.remaining_try)
        except sqlite3.Error as exc:
            return 0.0, [(0, f"Veritabanı hatası: {exc}")]
        return round(total_paid, 4), []

    def unmark_outgoing_invoice_paid(self, transaction_id: int) -> int:
        invoice_row = self.conn.execute(
            """
            SELECT company_id, invoice_no, document_no
            FROM transactions
            WHERE id = ?
            """,
            (transaction_id,),
        ).fetchone()
        company_id = int(invoice_row["company_id"]) if invoice_row else None
        invoice_no = ""
        if invoice_row:
            invoice_no = invoice_row["invoice_no"] or invoice_row["document_no"] or ""
        rows = self.conn.execute(
            """
            SELECT id, company_id, description, amount_try, raw_json, auto_paid_invoice_id
            FROM transactions
            WHERE source_type = ?
              AND (is_auto_paid = 1 OR description LIKE 'Otomatik ödendi işareti:%')
            """,
            (SOURCE_MANUAL_COLLECTION,),
        ).fetchall()
        deleted = 0
        invoice_no_folded = invoice_no.casefold()
        for row in rows:
            try:
                payload = json.loads(row["raw_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            row_auto_id = row["auto_paid_invoice_id"]
            if row_auto_id is None:
                row_auto_id = payload.get("auto_paid_invoice_id")
            try:
                raw_id_matches = row_auto_id is not None and int(row_auto_id) == int(transaction_id)
            except (TypeError, ValueError):
                raw_id_matches = False
            raw_invoice = str(payload.get("auto_paid_invoice_no", ""))
            raw_invoice_matches = bool(invoice_no) and raw_invoice.casefold() == invoice_no_folded
            description = row["description"] or ""
            description_matches = bool(invoice_no) and invoice_no_folded in description.casefold()
            company_matches = company_id is None or int(row["company_id"]) == company_id
            if raw_id_matches or (company_matches and (raw_invoice_matches or description_matches)):
                self.conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))
                deleted += 1
        if deleted == 0 and company_id is not None and invoice_no:
            # Older builds could create auto-paid rows without durable invoice metadata.
            # As a last resort, remove the newest automatic paid marker for this company
            # whose amount can plausibly be tied to the selected invoice.
            fallback = self.conn.execute(
                """
                SELECT id
                FROM transactions
                WHERE company_id = ?
                  AND source_type = ?
                  AND (is_auto_paid = 1 OR description LIKE 'Otomatik ödendi işareti:%')
                ORDER BY txn_date DESC, id DESC
                LIMIT 1
                """,
                (company_id, SOURCE_MANUAL_COLLECTION),
            ).fetchone()
            if fallback:
                self.conn.execute("DELETE FROM transactions WHERE id = ?", (fallback["id"],))
                deleted += 1
        self.conn.commit()
        return deleted

    def delete_transaction(self, transaction_id: int) -> None:
        self.conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        self.conn.execute(
            """
            DELETE FROM companies
            WHERE NOT EXISTS (
                SELECT 1 FROM transactions WHERE transactions.company_id = companies.id
            )
            """
        )
        self.conn.commit()

    def close_period(self, closing_date: str, carryover_amount_try: float) -> PeriodCloseResult:
        period_start = (date.fromisoformat(closing_date) + timedelta(days=1)).isoformat()
        open_invoices = self.open_invoices_as_of(closing_date)
        open_total = round(sum(invoice.remaining_try for invoice in open_invoices), 4)
        now = datetime.now().isoformat(timespec="seconds")

        cur = self.conn.execute(
            """
            INSERT INTO period_closures (
                closing_date, period_start_date, carryover_amount_try,
                open_invoice_count, open_invoice_total_try, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (closing_date, period_start, carryover_amount_try, len(open_invoices), open_total, now),
        )
        closure_id = int(cur.lastrowid)
        self.conn.execute("DELETE FROM transactions WHERE txn_date <= ?", (closing_date,))

        if abs(carryover_amount_try) > 0.005:
            company_id = self.upsert_company(name="DEVİR / DÖNEM BAŞLANGICI", tax_id="DEVIR")
            self.add_transaction(
                company_id=company_id,
                source_type=SOURCE_PERIOD_CARRYOVER,
                account_effect=EFFECT_DEBIT if carryover_amount_try >= 0 else EFFECT_CREDIT,
                txn_date=period_start,
                txn_datetime=f"{period_start} 00:00:00",
                external_key=f"period-carryover-{closure_id}",
                description=f"{closing_date} kapanış devir/fazla tutarı",
                amount_original=abs(carryover_amount_try),
                currency="TRY",
                exchange_rate=1,
                amount_try=abs(carryover_amount_try),
                raw={"period_closure_id": closure_id},
            )

        for invoice in open_invoices:
            self.add_transaction(
                company_id=invoice.company_id,
                source_type=invoice.source_type,
                account_effect=invoice.account_effect,
                txn_date=period_start,
                txn_datetime=f"{period_start} 00:00:00",
                invoice_no=invoice.invoice_no,
                document_no=invoice.document_no,
                external_key=f"open-invoice-{closure_id}-{invoice.source_type}-{invoice.invoice_no or invoice.document_no}-{invoice.company_id}",
                description=f"Devir açık fatura: {invoice.invoice_no or invoice.document_no} ({invoice.txn_date})",
                amount_original=invoice.remaining_try,
                currency="TRY",
                exchange_rate=1,
                amount_try=invoice.remaining_try,
                raw={
                    "period_closure_id": closure_id,
                    "original_date": invoice.txn_date,
                    "original_amount_try": invoice.amount_try,
                    "remaining_try": invoice.remaining_try,
                },
            )

        self.conn.commit()
        return PeriodCloseResult(
            closing_date=closing_date,
            period_start_date=period_start,
            carryover_amount_try=carryover_amount_try,
            open_invoice_count=len(open_invoices),
            open_invoice_total_try=open_total,
        )

    def iter_transactions(self) -> Iterable[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM transactions ORDER BY txn_date, id")
