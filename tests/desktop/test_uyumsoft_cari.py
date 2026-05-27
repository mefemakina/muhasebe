from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from desktop.uyumsoft_cari.csv_importer import (
    INCOMING_PROFILE,
    OUTGOING_PROFILE,
    import_uyumsoft_csv,
    parse_user_date,
)
from desktop.uyumsoft_cari.db import LedgerDatabase
from desktop.uyumsoft_cari.db import (
    EFFECT_CREDIT,
    EFFECT_DEBIT,
    SOURCE_INCOMING_INVOICE,
    SOURCE_MANUAL_COLLECTION,
    SOURCE_MANUAL_PAYMENT,
    SOURCE_OUTGOING_INVOICE,
    SOURCE_PERIOD_CARRYOVER,
)


import os


def _resolve_fixture_dir() -> Path:
    """
    Test CSV'lerinin yolu sırayla:
      1) MEFE_TEST_CSV_DIR env değişkeni
      2) Repo içindeki desktop/tests/fixtures dizini
      3) Eski Cursor uploads dizini (geriye dönük uyumluluk)
    """
    env_override = os.environ.get("MEFE_TEST_CSV_DIR")
    if env_override:
        return Path(env_override)
    repo_fixtures = Path(__file__).resolve().parents[2] / "desktop" / "tests" / "fixtures"
    if repo_fixtures.exists():
        return repo_fixtures
    return Path("/home/ubuntu/.cursor/projects/workspace/uploads")


UPLOADS = _resolve_fixture_dir()
INCOMING = UPLOADS / "GELEN-FATURA-Fatura_Listesi-27.05.2026_00_04_25_6afe.csv"
OUTGOING = UPLOADS / "G_DEN-FATURA-Fatura_Listesi-27.05.2026_00_15_54_6840.csv"


class UyumsoftCariTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LedgerDatabase(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_imports_sample_csv_files_and_dashboard_math(self) -> None:
        incoming_result = import_uyumsoft_csv(self.db, INCOMING, INCOMING_PROFILE.name)
        outgoing_result = import_uyumsoft_csv(self.db, OUTGOING, OUTGOING_PROFILE.name)

        self.assertEqual(incoming_result.failed_rows, 0, incoming_result.errors[:3])
        self.assertEqual(outgoing_result.failed_rows, 0, outgoing_result.errors[:3])
        self.assertGreater(incoming_result.skipped_blacklisted_leasing, 0)
        self.assertEqual(
            incoming_result.imported_rows + incoming_result.skipped_blacklisted_leasing,
            incoming_result.total_rows,
        )
        self.assertEqual(outgoing_result.imported_rows, outgoing_result.total_rows)

        totals = self.db.dashboard_totals("2026-05-27")
        self.assertGreater(totals.outgoing_invoices_try, 0)
        self.assertGreater(totals.incoming_invoices_try, 0)
        self.assertEqual(OUTGOING_PROFILE.account_effect, EFFECT_DEBIT)
        self.assertEqual(INCOMING_PROFILE.account_effect, EFFECT_CREDIT)
        self.assertGreater(totals.outgoing_invoices_net_try, 0)
        self.assertGreater(totals.incoming_invoices_net_try, 0)
        self.assertLess(totals.outgoing_invoices_net_try, totals.outgoing_invoices_try)
        self.assertAlmostEqual(
            totals.market_receivable_try,
            totals.outgoing_invoices_try - totals.manual_collections_try,
            places=2,
        )
        self.assertAlmostEqual(
            totals.net_financial_position_try,
            (
                self.db.conn.execute(
                    "SELECT COALESCE(SUM(net_amount_try), 0) AS total FROM transactions WHERE source_type = ?",
                    (SOURCE_OUTGOING_INVOICE,),
                ).fetchone()["total"]
                + totals.manual_payments_try
            )
            - (
                self.db.conn.execute(
                    "SELECT COALESCE(SUM(net_amount_try), 0) AS total FROM transactions WHERE source_type = ?",
                    (SOURCE_INCOMING_INVOICE,),
                ).fetchone()["total"]
                + totals.manual_collections_try
                + totals.period_carryover_try
            ),
            places=2,
        )
        self.assertNotEqual(totals.net_financial_position_try, totals.outgoing_invoices_try - totals.incoming_invoices_try)

        coca_cola = self.db.find_company_by_name("COCA COLA")
        self.assertIsNotNone(coca_cola)
        assert coca_cola is not None
        self.assertEqual(coca_cola.tax_id, "6110008160")

        range_totals = self.db.dashboard_totals(start_date="2026-05-20", end_date="2026-05-23")
        self.assertLess(range_totals.outgoing_invoices_try, totals.outgoing_invoices_try)

        company_rows = self.db.company_summaries()
        self.assertTrue(any(row["last_txn_date"] for row in company_rows))
        self.assertFalse(any("FİNANSAL KİRALAMA" in row["name"] for row in company_rows))

        monthly = self.db.monthly_outgoing_net_totals(2026)
        self.assertEqual(len(monthly), 12)
        self.assertGreater(sum(total for _month, total in monthly), 0)
        yearly = self.db.yearly_outgoing_net_totals([2024, 2025, 2026])
        self.assertEqual([year for year, _total in yearly], [2024, 2025, 2026])
        self.assertGreater(dict(yearly)[2026], 0)
        turnover = self.db.company_yearly_outgoing_turnover(2026)
        self.assertTrue(turnover)
        self.assertGreater(sum(row.share_percent for row in turnover), 99.9)

    def test_duplicate_imports_are_skipped(self) -> None:
        first = import_uyumsoft_csv(self.db, OUTGOING, OUTGOING_PROFILE.name)
        second = import_uyumsoft_csv(self.db, OUTGOING, OUTGOING_PROFILE.name)

        self.assertEqual(first.imported_rows, first.total_rows)
        self.assertEqual(second.imported_rows, 0)
        self.assertEqual(second.skipped_duplicates, second.total_rows)

    def test_reset_imported_csv_transactions_keeps_manual_entries(self) -> None:
        import_uyumsoft_csv(self.db, OUTGOING, OUTGOING_PROFILE.name)
        first_status = self.db.outgoing_invoice_statuses()[0]
        self.db.mark_outgoing_invoice_paid(first_status.transaction_id)
        company_id = self.db.upsert_company(name="Manuel Cari", tax_id="333")
        self.db.add_transaction(
            company_id=company_id,
            source_type=SOURCE_MANUAL_COLLECTION,
            account_effect=EFFECT_CREDIT,
            txn_date="2026-05-20",
            amount_original=500,
            currency="TRY",
            exchange_rate=1,
            amount_try=500,
            external_key="manual-collection-reset-test",
        )

        self.assertGreater(self.db.csv_transaction_count(), 0)
        result = self.db.reset_imported_csv_transactions()
        self.assertGreater(result.deleted_transactions, 0)
        self.assertEqual(self.db.csv_transaction_count(), 0)
        auto_paid_count = self.db.conn.execute(
            "SELECT COUNT(*) AS count FROM transactions WHERE raw_json LIKE '%auto_paid_invoice_id%'"
        ).fetchone()["count"]
        self.assertEqual(auto_paid_count, 0)

        totals = self.db.dashboard_totals("2026-05-27")
        self.assertEqual(totals.outgoing_invoices_try, 0)
        self.assertEqual(totals.manual_collections_try, 500)

    def test_date_range_company_list_requires_invoice_activity(self) -> None:
        manual_id = self.db.upsert_company(name="Sadece Manuel Cari", tax_id="555")
        invoice_id = self.db.upsert_company(name="Faturali Cari", tax_id="556")
        self.db.add_transaction(
            company_id=manual_id,
            source_type=SOURCE_MANUAL_COLLECTION,
            account_effect=EFFECT_CREDIT,
            txn_date="2026-04-01",
            amount_original=100,
            currency="TRY",
            exchange_rate=1,
            amount_try=100,
            external_key="manual-only-range",
        )
        self.db.add_transaction(
            company_id=invoice_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-04-02",
            amount_original=120,
            currency="USD",
            exchange_rate=40,
            amount_try=4800,
            net_amount_try=4000,
            external_key="invoice-range",
        )

        rows = self.db.company_summaries(start_date="2026-04-01", end_date="2026-04-30")
        self.assertEqual([row["name"] for row in rows], ["Faturali Cari"])
        currency = self.db.company_currency_summaries(start_date="2026-04-01", end_date="2026-04-30")
        self.assertEqual(currency[invoice_id][0].currency, "USD")
        self.assertAlmostEqual(currency[invoice_id][0].debit_original, 120)

    def test_dashboard_company_rows_only_show_receivables(self) -> None:
        customer_id = self.db.upsert_company(name="Alacak Musteri", tax_id="901")
        supplier_id = self.db.upsert_company(name="Borclu Tedarikci", tax_id="902")
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-09-01",
            amount_original=1000,
            currency="TRY",
            exchange_rate=1,
            amount_try=1000,
            external_key="dashboard-receivable",
        )
        self.db.add_transaction(
            company_id=supplier_id,
            source_type=SOURCE_INCOMING_INVOICE,
            account_effect=EFFECT_CREDIT,
            txn_date="2026-09-01",
            amount_original=500,
            currency="TRY",
            exchange_rate=1,
            amount_try=500,
            external_key="dashboard-payable",
        )
        rows = self.db.company_summaries(start_date="2026-09-01", end_date="2026-09-30")
        visible = [row["name"] for row in rows if float(row["debit_try"] or 0) > 0.005]
        self.assertEqual(visible, ["Alacak Musteri"])

    def test_period_carryover_is_subtracted_from_net_financial_position(self) -> None:
        customer_id = self.db.upsert_company(name="Devir Musteri", tax_id="777")
        carry_id = self.db.upsert_company(name="DEVİR / DÖNEM BAŞLANGICI", tax_id="DEVIR")
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-05-01",
            amount_original=1200,
            currency="TRY",
            exchange_rate=1,
            amount_try=1200,
            net_amount_try=1000,
            external_key="devir-outgoing",
        )
        self.db.add_transaction(
            company_id=carry_id,
            source_type=SOURCE_PERIOD_CARRYOVER,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-05-01",
            amount_original=3000,
            currency="TRY",
            exchange_rate=1,
            amount_try=3000,
            external_key="devir-carry",
        )

        totals = self.db.dashboard_totals("2026-05-31")
        self.assertAlmostEqual(totals.net_financial_position_try, -2000)

    def test_manual_date_parser_accepts_turkish_format(self) -> None:
        self.assertEqual(parse_user_date("31.03.2026"), "2026-03-31")

    def test_outgoing_invoice_statuses_mark_paid_and_open(self) -> None:
        customer_id = self.db.upsert_company(name="Status Musteri", tax_id="444")
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-03-01",
            amount_original=100,
            currency="TRY",
            exchange_rate=1,
            amount_try=100,
            external_key="status-out-1",
            invoice_no="S-1",
        )
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-03-02",
            amount_original=200,
            currency="TRY",
            exchange_rate=1,
            amount_try=200,
            external_key="status-out-2",
            invoice_no="S-2",
        )
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_MANUAL_COLLECTION,
            account_effect=EFFECT_CREDIT,
            txn_date="2026-03-03",
            amount_original=150,
            currency="TRY",
            exchange_rate=1,
            amount_try=150,
            external_key="status-collection",
        )

        statuses = self.db.outgoing_invoice_statuses()
        self.assertEqual([status.invoice_no for status in statuses], ["S-1", "S-2"])
        self.assertTrue(statuses[0].is_paid)
        self.assertAlmostEqual(statuses[0].remaining_try, 0)
        self.assertFalse(statuses[1].is_paid)
        self.assertAlmostEqual(statuses[1].remaining_try, 150)

        paid_amount = self.db.mark_outgoing_invoice_paid(statuses[1].transaction_id)
        self.assertAlmostEqual(paid_amount, 150)
        after_statuses = self.db.outgoing_invoice_statuses()
        self.assertTrue(after_statuses[1].is_paid)
        self.assertAlmostEqual(after_statuses[1].remaining_try, 0)
        balance = self.db.balance_for_company(customer_id, "2099-01-01")
        self.assertAlmostEqual(balance, 0)
        removed = self.db.unmark_outgoing_invoice_paid(statuses[1].transaction_id)
        self.assertEqual(removed, 1)
        reopened = self.db.outgoing_invoice_statuses()
        self.assertFalse(reopened[1].is_paid)
        self.assertAlmostEqual(reopened[1].remaining_try, 150)

        self.db.mark_outgoing_invoice_paid(statuses[1].transaction_id)
        auto_row = self.db.conn.execute(
            "SELECT id FROM transactions WHERE raw_json LIKE '%auto_paid_invoice_id%'"
        ).fetchone()
        self.assertIsNotNone(auto_row)
        self.db.conn.execute(
            "UPDATE transactions SET raw_json = ? WHERE id = ?",
            ('{"auto_paid_invoice_id": 999999, "auto_paid_invoice_no": "S-2", "auto_paid_company_id": 1}', auto_row["id"]),
        )
        self.db.conn.commit()
        removed_by_invoice_no = self.db.unmark_outgoing_invoice_paid(statuses[1].transaction_id)
        self.assertEqual(removed_by_invoice_no, 1)

    def test_auto_paid_applies_to_selected_invoice_not_fifo(self) -> None:
        customer_id = self.db.upsert_company(name="Secili Fatura Musteri", tax_id="889")
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-07-01",
            amount_original=100,
            currency="TRY",
            exchange_rate=1,
            amount_try=100,
            external_key="selected-out-1",
            invoice_no="SEL-1",
        )
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-07-02",
            amount_original=200,
            currency="TRY",
            exchange_rate=1,
            amount_try=200,
            external_key="selected-out-2",
            invoice_no="SEL-2",
        )

        statuses = self.db.outgoing_invoice_statuses()
        paid_amount = self.db.mark_outgoing_invoice_paid(statuses[1].transaction_id)
        self.assertAlmostEqual(paid_amount, 200)

        after = self.db.outgoing_invoice_statuses()
        self.assertFalse(after[0].is_paid)
        self.assertAlmostEqual(after[0].remaining_try, 100)
        self.assertTrue(after[1].is_paid)
        self.assertAlmostEqual(after[1].remaining_try, 0)

        removed = self.db.unmark_outgoing_invoice_paid(statuses[1].transaction_id)
        self.assertEqual(removed, 1)
        reopened = self.db.outgoing_invoice_statuses()
        self.assertFalse(reopened[1].is_paid)
        self.assertAlmostEqual(reopened[1].remaining_try, 200)

    def test_auto_paid_collections_do_not_reduce_net_financial_position(self) -> None:
        customer_id = self.db.upsert_company(name="Net Musteri", tax_id="888")
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-06-01",
            amount_original=1200,
            currency="TRY",
            exchange_rate=1,
            amount_try=1200,
            net_amount_try=1000,
            external_key="net-out-1",
            invoice_no="NET-1",
        )
        before = self.db.dashboard_totals("2026-06-30")
        self.assertAlmostEqual(before.net_financial_position_try, 1000)
        status = self.db.outgoing_invoice_statuses()[0]
        self.db.mark_outgoing_invoice_paid(status.transaction_id)
        after = self.db.dashboard_totals("2026-06-30")
        self.assertAlmostEqual(after.market_receivable_try, 0)
        self.assertAlmostEqual(after.net_financial_position_try, 1000)
        # Repeated/extra automatic paid records must not make market receivable negative.
        self.db.mark_outgoing_invoice_paid(status.transaction_id)
        repeated = self.db.dashboard_totals("2026-06-30")
        self.assertAlmostEqual(repeated.market_receivable_try, 0)

    def test_manual_collections_cannot_make_market_receivable_negative(self) -> None:
        customer_id = self.db.upsert_company(name="Fazla Tahsilat Musteri", tax_id="890")
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-08-01",
            amount_original=1000,
            currency="TRY",
            exchange_rate=1,
            amount_try=1000,
            net_amount_try=900,
            external_key="over-out-1",
            invoice_no="OVER-1",
        )
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_MANUAL_COLLECTION,
            account_effect=EFFECT_CREDIT,
            txn_date="2026-08-02",
            amount_original=5000,
            currency="TRY",
            exchange_rate=1,
            amount_try=5000,
            external_key="over-collection",
        )

        totals = self.db.dashboard_totals("2026-08-31")
        self.assertAlmostEqual(totals.market_receivable_try, 0)

    def test_leasing_companies_are_blacklisted_and_removed(self) -> None:
        with self.assertRaises(ValueError):
            self.db.upsert_company(name="ALTERNATİF FİNANSAL KİRALAMA ANONİM ŞİRKETİ", tax_id="0600047109")

        # Simulate an older database that already had a leasing company before the blacklist existed.
        self.db.conn.execute(
            """
            INSERT INTO companies (tax_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("0600047109", "ALTERNATİF FİNANSAL KİRALAMA ANONİM ŞİRKETİ", "2026-01-01", "2026-01-01"),
        )
        company_id = int(self.db.conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        self.db.conn.execute(
            """
            INSERT INTO transactions (
                company_id, source_type, account_effect, txn_date, external_key,
                amount_original, currency, exchange_rate, amount_try, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (company_id, SOURCE_INCOMING_INVOICE, EFFECT_CREDIT, "2026-05-18", "old-leasing", 100, "TRY", 1, 100, "2026-01-01"),
        )
        self.db.conn.commit()

        deleted = self.db.delete_blacklisted_leasing_records()
        self.assertEqual(deleted, 1)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) AS count FROM companies WHERE id = ?", (company_id,)).fetchone()["count"], 0)

    def test_period_close_carries_only_open_old_invoices(self) -> None:
        customer_id = self.db.upsert_company(name="Test Musteri", tax_id="111")
        supplier_id = self.db.upsert_company(name="Test Tedarikci", tax_id="222")
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_OUTGOING_INVOICE,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-01-10",
            amount_original=100,
            currency="TRY",
            exchange_rate=1,
            amount_try=100,
            external_key="out-1",
            invoice_no="OUT-1",
        )
        self.db.add_transaction(
            company_id=customer_id,
            source_type=SOURCE_MANUAL_COLLECTION,
            account_effect=EFFECT_CREDIT,
            txn_date="2026-01-15",
            amount_original=40,
            currency="TRY",
            exchange_rate=1,
            amount_try=40,
            external_key="collection-1",
        )
        self.db.add_transaction(
            company_id=supplier_id,
            source_type=SOURCE_INCOMING_INVOICE,
            account_effect=EFFECT_CREDIT,
            txn_date="2026-01-11",
            amount_original=80,
            currency="TRY",
            exchange_rate=1,
            amount_try=80,
            external_key="in-1",
            invoice_no="IN-1",
        )
        self.db.add_transaction(
            company_id=supplier_id,
            source_type=SOURCE_MANUAL_PAYMENT,
            account_effect=EFFECT_DEBIT,
            txn_date="2026-01-12",
            amount_original=80,
            currency="TRY",
            exchange_rate=1,
            amount_try=80,
            external_key="payment-1",
        )

        preview = self.db.open_invoices_as_of("2026-01-31")
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0].invoice_no, "OUT-1")
        self.assertAlmostEqual(preview[0].remaining_try, 60)

        result = self.db.close_period("2026-01-31", 3000)
        self.assertEqual(result.period_start_date, "2026-02-01")
        self.assertEqual(self.db.active_period_start_date(), "2026-02-01")
        self.assertEqual(result.open_invoice_count, 1)
        self.assertAlmostEqual(result.open_invoice_total_try, 60)

        rows = list(self.db.iter_transactions())
        self.assertTrue(all(row["txn_date"] > "2026-01-31" for row in rows))
        carried = [row for row in rows if row["source_type"] == SOURCE_OUTGOING_INVOICE]
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["invoice_no"], "OUT-1")
        self.assertAlmostEqual(carried[0]["amount_try"], 60)

        self.assertEqual(self.db.period_carryover_count(), 1)
        reset = self.db.reset_period_carryover_data()
        self.assertEqual(reset.deleted_transactions, 1)
        self.assertEqual(reset.deleted_period_closures, 1)
        self.assertEqual(self.db.period_carryover_count(), 0)
        rows_after_reset = list(self.db.iter_transactions())
        self.assertFalse(any(row["source_type"] == SOURCE_PERIOD_CARRYOVER for row in rows_after_reset))
        self.assertTrue(any(row["source_type"] == SOURCE_OUTGOING_INVOICE for row in rows_after_reset))


if __name__ == "__main__":
    unittest.main()
