from __future__ import annotations

import json
import tkinter as tk
import shutil
import sqlite3
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

try:
    import sv_ttk  # modern Windows 11 Fluent teması
except ImportError:  # pragma: no cover - PyInstaller paketinde her zaman bulunur
    sv_ttk = None

from . import __version__
from .assets import load_mefe_logo
from .csv_importer import (
    INCOMING_PROFILE,
    OUTGOING_PROFILE,
    amount_try,
    format_user_date_from_iso,
    import_uyumsoft_csv,
    parse_decimal,
    parse_user_date,
)
from .db import (
    EFFECT_CREDIT,
    EFFECT_DEBIT,
    SOURCE_MANUAL_COLLECTION,
    SOURCE_MANUAL_PAYMENT,
    LedgerDatabase,
    today_iso,
)
from .formatting import money_input, money_original, money_try, percent_try, signed_balance_text


APP_TITLE = f"MEFE Muhasebe - Uyumsoft Cari Takip v{__version__}"

# === MEFE Marka Paleti (Sun Valley üzerine bindiriliyor) ===
BRAND_COLOR = "#2d237f"          # logo koyu mor
ACCENT_COLOR = "#0f6f8f"         # turkuaz mavi
ACCENT_DARK = "#0b3f67"          # navy
ACCENT_ACTIVE = "#128aa6"
POSITIVE_COLOR = "#0b5d1e"
NEGATIVE_COLOR = "#8a1f16"

# Light tema
LIGHT_BG = "#fafbfc"
LIGHT_CARD = "#ffffff"
LIGHT_FG = "#1f2937"
LIGHT_MUTED = "#5b6472"

# Dark tema
DARK_BG = "#1c1c1c"
DARK_CARD = "#2b2b2b"
DARK_FG = "#e5e7eb"
DARK_MUTED = "#9ca3af"

# Tablo satır renkleri — semantik: yeşil = aktif/açık, gri = kapalı/ödenmiş
ROW_OPEN_BG = "#e6f7ec"
ROW_OPEN_FG = "#065f1c"
ROW_CLOSED_BG = "#eef0f3"
ROW_CLOSED_FG = "#6b7280"


class MefeAccountingApp(tk.Tk):
    def __init__(self, db_path: str | None = None) -> None:
        super().__init__()
        self.db = LedgerDatabase(db_path)
        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(1080, 700)
        self.logo_image = load_mefe_logo((110, 82))

        # Tema durumu — pencere açıldığında "light" başlar, kullanıcı toggle edebilir
        self.theme_mode = tk.StringVar(value="light")
        self._apply_theme(self.theme_mode.get())

        self.company_lookup: dict[str, int] = {}
        self.selected_company_id: int | None = None
        self.dashboard_start_var = tk.StringVar(value=format_user_date_from_iso(self._default_dashboard_start_iso()))
        self.dashboard_end_var = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        self.period_close_date_var = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        self.period_carryover_amount_var = tk.StringVar(value="0")
        self.company_sort_key = "name"
        self.company_sort_reverse = False
        self.company_search_var = tk.StringVar()
        self.monthly_year_var = tk.StringVar(value=str(date.today().year))
        self.annual_years = [2024, 2025, 2026]
        self.tree_sort_state: dict[tuple[int, str], bool] = {}
        self.manual_outgoing_company_var = tk.StringVar(value="Tüm Firmalar")
        self.turnover_year_var = tk.StringVar(value=str(date.today().year))
        # Debounce için "after" job id'leri
        self._debounce_jobs: dict[str, str] = {}

        self._setup_style()
        self._build_layout()
        self.refresh_all()

    def destroy(self) -> None:
        self.db.close()
        super().destroy()

    def _apply_theme(self, mode: str) -> None:
        """sv-ttk light/dark teması (varsa). Yoksa clam fallback."""
        if sv_ttk is not None:
            sv_ttk.set_theme(mode)
        else:
            try:
                ttk.Style(self).theme_use("clam")
            except tk.TclError:
                pass
        bg = DARK_BG if mode == "dark" else LIGHT_BG
        self.configure(bg=bg)

    def toggle_theme(self) -> None:
        new_mode = "dark" if self.theme_mode.get() == "light" else "light"
        self.theme_mode.set(new_mode)
        self._apply_theme(new_mode)
        self._setup_style()
        if hasattr(self, "theme_toggle_btn"):
            self.theme_toggle_btn.configure(
                text=("🌙 Karanlık Tema" if new_mode == "light" else "☀ Aydınlık Tema")
            )

    def _setup_style(self) -> None:
        """sv-ttk üzerine MEFE marka renklerini bindirir; light/dark moduna göre ayarlar."""
        style = ttk.Style(self)
        is_dark = self.theme_mode.get() == "dark"
        bg = DARK_BG if is_dark else LIGHT_BG
        card_bg = DARK_CARD if is_dark else LIGHT_CARD
        fg = DARK_FG if is_dark else LIGHT_FG
        muted = DARK_MUTED if is_dark else LIGHT_MUTED

        # MEFE özel etiketleri (sv-ttk'nın stilini bozmadan üzerine ekler)
        style.configure("Card.TFrame", background=card_bg, relief="flat")
        style.configure("Card.TLabel", background=card_bg, foreground=fg, font=("Segoe UI", 10))
        style.configure("Brand.TLabel", background=bg, foreground=BRAND_COLOR, font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=("Segoe UI", 10))
        style.configure("MetricTitle.TLabel", background=card_bg, foreground=muted, font=("Segoe UI", 10, "bold"))
        style.configure("MetricValue.TLabel", background=card_bg, foreground=BRAND_COLOR if not is_dark else ACCENT_ACTIVE, font=("Segoe UI", 22, "bold"))
        style.configure("PositiveMetric.TLabel", background=card_bg, foreground=POSITIVE_COLOR, font=("Segoe UI", 23, "bold"))
        style.configure("DangerMetric.TLabel", background=card_bg, foreground=NEGATIVE_COLOR, font=("Segoe UI", 23, "bold"))
        style.configure("Heading.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 12, "bold"))

        # sv-ttk Treeview üzerinde satır yüksekliği ve font
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10, "bold"))

    def _build_layout(self) -> None:
        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.pack(fill="x")
        if self.logo_image:
            ttk.Label(header, image=self.logo_image).pack(side="left", padx=(0, 12))

        title_box = ttk.Frame(header)
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="MEFE MAKINA MUHASEBE", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Uyumsoft Gelen/Giden Fatura CSV, manuel ödeme ve tarihli mutabakat takip ekranı",
            style="Subtitle.TLabel",
        ).pack(anchor="w")

        right_box = ttk.Frame(header)
        right_box.pack(side="right", anchor="n")
        self.theme_toggle_btn = ttk.Button(
            right_box,
            text="🌙 Karanlık Tema",
            command=self.toggle_theme,
            style="Accent.TButton" if sv_ttk is not None else "TButton",
        )
        self.theme_toggle_btn.pack(side="top", anchor="e", pady=(0, 4))
        self.today_label = ttk.Label(right_box, text="", style="Subtitle.TLabel")
        self.today_label.pack(side="top", anchor="e")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(4, 20))

        self.dashboard_tab = ttk.Frame(self.notebook, padding=12)
        self.import_tab = ttk.Frame(self.notebook, padding=12)
        self.manual_tab = ttk.Frame(self.notebook, padding=12)
        self.reconcile_tab = ttk.Frame(self.notebook, padding=12)
        self.period_tab = ttk.Frame(self.notebook, padding=12)
        self.monthly_tab = ttk.Frame(self.notebook, padding=12)
        self.annual_tab = ttk.Frame(self.notebook, padding=12)
        self.backup_tab = ttk.Frame(self.notebook, padding=12)
        self.turnover_tab = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.dashboard_tab, text="Ana Ekran")
        self.notebook.add(self.import_tab, text="CSV İçe Aktar")
        self.notebook.add(self.manual_tab, text="Manuel İşlemler")
        self.notebook.add(self.reconcile_tab, text="Cari Mutabakat")
        self.notebook.add(self.period_tab, text="Devir / Dönem")
        self.notebook.add(self.monthly_tab, text="Aylık Giden Grafik")
        self.notebook.add(self.annual_tab, text="Yıllık Giden Grafik")
        self.notebook.add(self.turnover_tab, text="Firma Yıllık Ciro")
        self.notebook.add(self.backup_tab, text="Yedek / Aktarım")

        self._build_dashboard()
        self._build_import_tab()
        self._build_manual_tab()
        self._build_reconcile_tab()
        self._build_period_tab()
        self._build_monthly_tab()
        self._build_annual_tab()
        self._build_turnover_tab()
        self._build_backup_tab()

    def _build_dashboard(self) -> None:
        date_panel = ttk.Frame(self.dashboard_tab, style="Card.TFrame", padding=12)
        date_panel.pack(fill="x", pady=(0, 12))
        ttk.Label(date_panel, text="Dashboard Tarih Aralığı", style="MetricTitle.TLabel").pack(side="left", padx=(0, 12))
        ttk.Label(date_panel, text="Başlangıç", style="Card.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(date_panel, textvariable=self.dashboard_start_var, width=14).pack(side="left", padx=(0, 12))
        ttk.Label(date_panel, text="Bitiş", style="Card.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(date_panel, textvariable=self.dashboard_end_var, width=14).pack(side="left", padx=(0, 12))
        ttk.Button(date_panel, text="Aralığı Hesapla", command=self.refresh_all).pack(side="left", padx=(0, 8))
        ttk.Button(date_panel, text="Bugüne Kadar", command=self._reset_dashboard_dates).pack(side="left")
        ttk.Label(
            date_panel,
            text="Boş başlangıç = ilk işlemden itibaren. Format: gg.aa.yyyy",
            style="Card.TLabel",
        ).pack(side="right")

        metrics = ttk.Frame(self.dashboard_tab)
        metrics.pack(fill="x")
        self.market_receivable_value = self._metric_card(
            metrics,
            "Piyasadan Toplam Güncel Alacak Tutarı",
            "0,00 TL",
            "Giden faturalar - müşteriden gelen tahsilatlar",
        )
        self.net_position_value = self._metric_card(
            metrics,
            "Toplam Fazla / Net Finansal Durum",
            "0,00 TL",
            "Tüm giden verileri - (tüm gelen verileri + devir)",
        )
        metrics.columnconfigure(0, weight=1)
        metrics.columnconfigure(1, weight=1)

        detail = ttk.Frame(self.dashboard_tab, style="Card.TFrame", padding=16)
        detail.pack(fill="x", pady=(14, 12))
        self.summary_labels: dict[str, ttk.Label] = {}
        for col, key in enumerate(
            [
                "Giden Fatura",
                "Giden KDV'siz",
                "Gelen Fatura",
                "Gelen KDV'siz",
                "Tedarikçi Ödemesi",
                "Müşteri Tahsilatı",
                "Kalan Borç",
                "Devir/Fazla",
                "Cari Sayısı",
                "İşlem Sayısı",
            ]
        ):
            box = ttk.Frame(detail, style="Card.TFrame")
            box.grid(row=0, column=col, sticky="ew", padx=8)
            ttk.Label(box, text=key, style="MetricTitle.TLabel").pack(anchor="w")
            lbl = ttk.Label(box, text="-", style="Card.TLabel", font=("Segoe UI", 12, "bold"))
            lbl.pack(anchor="w", pady=(4, 0))
            self.summary_labels[key] = lbl
            detail.columnconfigure(col, weight=1)

        toolbar = ttk.Frame(self.dashboard_tab)
        toolbar.pack(fill="x", pady=(4, 8))
        ttk.Label(toolbar, text="Cari Hesaplar", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Label(toolbar, text="Firma ara:", style="Subtitle.TLabel").pack(side="left", padx=(18, 6))
        search_entry = ttk.Entry(toolbar, textvariable=self.company_search_var, width=28)
        search_entry.pack(side="left")
        search_entry.bind("<KeyRelease>", lambda _event: self._debounce(
            "dashboard_search", 200, self.refresh_all
        ))
        ttk.Label(toolbar, text="Başlıklara tıklayarak sıralayın", style="Subtitle.TLabel").pack(side="left", padx=(12, 0))
        ttk.Button(toolbar, text="Yenile", command=self.refresh_all).pack(side="right")

        self.company_tree = ttk.Treeview(
            self.dashboard_tab,
            columns=("tax", "date", "receivable", "payable", "fx", "balance", "count"),
            show="tree headings",
            height=13,
        )
        self.company_tree.heading("#0", text="Cari", command=lambda: self._sort_company_tree("name"))
        self.company_tree.heading("tax", text="VKN/TCKN")
        self.company_tree.heading("date", text="Son Tarih", command=lambda: self._sort_company_tree("date"))
        self.company_tree.heading("receivable", text="Alacak", command=lambda: self._sort_company_tree("debit"))
        self.company_tree.heading("payable", text="Borç", command=lambda: self._sort_company_tree("credit"))
        self.company_tree.heading("fx", text="Döviz Özeti")
        self.company_tree.heading("balance", text="Net Bakiye", command=lambda: self._sort_company_tree("balance"))
        self.company_tree.heading("count", text="İşlem")
        self.company_tree.column("#0", width=280)
        self.company_tree.column("tax", width=120, anchor="center")
        self.company_tree.column("date", width=105, anchor="center")
        self.company_tree.column("receivable", width=125, anchor="e")
        self.company_tree.column("payable", width=125, anchor="e")
        self.company_tree.column("fx", width=210, anchor="w")
        self.company_tree.column("balance", width=145, anchor="e")
        self.company_tree.column("count", width=70, anchor="center")
        self.company_tree.pack(fill="both", expand=True)
        self.company_tree.bind("<<TreeviewSelect>>", self._on_dashboard_company_selected)

    def _metric_card(self, parent: ttk.Frame, title: str, value: str, help_text: str) -> ttk.Label:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=0, column=len(parent.grid_slaves()), sticky="ew", padx=7)
        ttk.Label(card, text=title, style="MetricTitle.TLabel").pack(anchor="w")
        value_label = ttk.Label(card, text=value, style="MetricValue.TLabel")
        value_label.pack(anchor="w", pady=(8, 4))
        ttk.Label(card, text=help_text, style="Card.TLabel").pack(anchor="w")
        return value_label

    def _build_import_tab(self) -> None:
        panel = ttk.Frame(self.import_tab, style="Card.TFrame", padding=18)
        panel.pack(fill="x")
        ttk.Label(panel, text="Uyumsoft CSV Dosyaları", style="MetricTitle.TLabel").pack(anchor="w")
        ttk.Label(
            panel,
            text=(
                "Dosyalar ekteki Uyumsoft başlıklarıyla uyumludur. "
                "Giden faturalar BORÇ, gelen faturalar ALACAK olarak işlenir."
            ),
            style="Card.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        buttons = ttk.Frame(panel, style="Card.TFrame")
        buttons.pack(anchor="w")
        ttk.Button(
            buttons,
            text="Giden Fatura CSV Seç (BORÇ)",
            command=lambda: self.import_csv(OUTGOING_PROFILE.name),
        ).pack(side="left", padx=(0, 10))
        ttk.Button(
            buttons,
            text="Gelen Fatura CSV Seç (ALACAK)",
            command=lambda: self.import_csv(INCOMING_PROFILE.name),
        ).pack(side="left", padx=(0, 10))
        ttk.Button(
            buttons,
            text="İçe Aktarılan CSV'leri Sıfırla",
            command=self.reset_imported_csvs,
        ).pack(side="left", padx=(18, 0))

        self.import_result = tk.Text(self.import_tab, height=18, wrap="word", font=("Consolas", 10))
        self.import_result.pack(fill="both", expand=True, pady=(14, 0))
        self.import_result.insert("end", "İçe aktarma sonuçları burada görünecek.\n")
        self.import_result.configure(state="disabled")

    def _build_manual_tab(self) -> None:
        form = ttk.Frame(self.manual_tab, style="Card.TFrame", padding=18)
        form.pack(fill="x")
        self.manual_vars = {
            "date": tk.StringVar(value=date.today().strftime("%d.%m.%Y")),
            "company": tk.StringVar(),
            "tax_id": tk.StringVar(),
            "type": tk.StringVar(value="Giden Fatura Menüsü - Gelen Havale/Tahsilat (Bize gelen para) - ALACAK"),
            "amount": tk.StringVar(),
            "currency": tk.StringVar(value="TRY"),
            "rate": tk.StringVar(value="1"),
            "description": tk.StringVar(),
        }
        fields = [
            ("Tarih (gg.aa.yyyy)", "date"),
            ("Cari/Firma Adı", "company"),
            ("VKN/TCKN", "tax_id"),
            ("Tutar", "amount"),
            ("Para Birimi", "currency"),
            ("Döviz Kuru", "rate"),
            ("Açıklama", "description"),
        ]
        for idx, (label, key) in enumerate(fields):
            row, col = divmod(idx, 2)
            ttk.Label(form, text=label, style="Card.TLabel").grid(row=row, column=col * 2, sticky="w", padx=(0, 8), pady=6)
            if key == "currency":
                entry = ttk.Combobox(
                    form,
                    textvariable=self.manual_vars[key],
                    values=["TRY", "USD", "EUR"],
                    state="readonly",
                    width=32,
                )
                entry.bind("<<ComboboxSelected>>", self._on_currency_selected)
            else:
                entry = ttk.Entry(form, textvariable=self.manual_vars[key], width=34)
                if key == "company":
                    # Hafif debounce — KeyRelease'de her tuşa SQL atmamak için 250ms gecikme
                    entry.bind("<KeyRelease>", lambda _event: self._debounce(
                        "manual_tax_autofill", 250, self._auto_fill_manual_tax_id
                    ))
                    entry.bind("<FocusOut>", self._auto_fill_manual_tax_id)
            entry.grid(row=row, column=col * 2 + 1, sticky="ew", pady=6, padx=(0, 18))
            form.columnconfigure(col * 2 + 1, weight=1)

        ttk.Label(form, text="İşlem Tipi", style="Card.TLabel").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Combobox(
            form,
            textvariable=self.manual_vars["type"],
            values=[
                "Giden Fatura Menüsü - Gelen Havale/Tahsilat (Bize gelen para) - ALACAK",
                "Gelen Fatura Menüsü - Yapılan Ödeme (Bizim verdiğimiz para) - BORÇ",
            ],
            state="readonly",
            width=48,
        ).grid(row=4, column=1, columnspan=3, sticky="ew", pady=6, padx=(0, 18))

        ttk.Button(form, text="Manuel İşlemi Kaydet", command=self.save_manual_transaction).grid(
            row=5, column=1, sticky="w", pady=(12, 0)
        )

        self.manual_result = ttk.Label(self.manual_tab, text="", style="Subtitle.TLabel")
        self.manual_result.pack(anchor="w", pady=12)

        filter_bar = ttk.Frame(self.manual_tab)
        filter_bar.pack(fill="x", pady=(2, 6))
        ttk.Label(filter_bar, text="Giden faturalar firma filtresi:", style="Subtitle.TLabel").pack(side="left", padx=(0, 8))
        self.manual_outgoing_company_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.manual_outgoing_company_var,
            state="readonly",
            width=48,
        )
        self.manual_outgoing_company_combo.pack(side="left")
        self.manual_outgoing_company_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_outgoing_invoice_statuses())

        ttk.Label(
            self.manual_tab,
            text="Giden Faturalar - Tahsilat Durumu",
            style="Heading.TLabel",
        ).pack(anchor="w", pady=(6, 6))
        self.outgoing_status_tree = ttk.Treeview(
            self.manual_tab,
            columns=("company", "date", "invoice", "amount", "collected", "remaining", "status"),
            show="headings",
            height=10,
        )
        for key, text, width, anchor, kind in [
            ("company", "Firma", 260, "w", "text"),
            ("date", "Tarih", 100, "center", "date"),
            ("invoice", "Fatura No", 150, "w", "text"),
            ("amount", "Fatura Tutarı", 125, "e", "money"),
            ("collected", "Gelen Ödeme", 125, "e", "money"),
            ("remaining", "Kalan", 125, "e", "money"),
            ("status", "Durum", 110, "center", "text"),
        ]:
            self.outgoing_status_tree.heading(
                key,
                text=text,
                command=lambda col=key, sort_kind=kind: self._sort_treeview(self.outgoing_status_tree, col, sort_kind),
            )
            self.outgoing_status_tree.column(key, width=width, anchor=anchor)
        self.outgoing_status_tree.tag_configure("paid", background=ROW_CLOSED_BG, foreground=ROW_CLOSED_FG)
        self.outgoing_status_tree.tag_configure("open", background=ROW_OPEN_BG, foreground=ROW_OPEN_FG)
        self.outgoing_status_tree.pack(fill="both", expand=True)
        self.outgoing_status_menu = tk.Menu(self, tearoff=0)
        self.outgoing_status_menu.add_command(label="Ödendi olarak işaretle", command=self.mark_selected_outgoing_paid)
        self.outgoing_status_menu.add_command(label="Ödenmediye çevir", command=self.unmark_selected_outgoing_paid)
        self.outgoing_status_tree.bind("<Button-3>", self._show_outgoing_status_menu)

    def _build_reconcile_tab(self) -> None:
        top = ttk.Frame(self.reconcile_tab, style="Card.TFrame", padding=16)
        top.pack(fill="x")
        ttk.Label(top, text="Cari Seç", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.reconcile_company_var = tk.StringVar()
        self.company_combo = ttk.Combobox(top, textvariable=self.reconcile_company_var, state="readonly", width=54)
        self.company_combo.grid(row=0, column=1, sticky="ew", padx=(0, 18))

        ttk.Label(top, text="Mutabakat Tarihi", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 8))
        self.as_of_var = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        ttk.Entry(top, textvariable=self.as_of_var, width=16).grid(row=0, column=3, sticky="w", padx=(0, 18))
        ttk.Button(top, text="Hesapla", command=self.calculate_reconciliation).grid(row=0, column=4, sticky="w")
        top.columnconfigure(1, weight=1)

        self.reconciliation_result = ttk.Label(
            self.reconcile_tab,
            text="Bir cari ve tarih seçerek mutabakat hesaplayın.",
            style="Brand.TLabel",
        )
        self.reconciliation_result.pack(anchor="w", pady=(16, 8))

        self.txn_tree = ttk.Treeview(
            self.reconcile_tab,
            columns=("company", "date", "source", "effect", "amount", "currency", "try", "desc"),
            show="headings",
            height=17,
        )
        for key, text, width, anchor, kind in [
            ("company", "Cari", 180, "w", "text"),
            ("date", "Tarih", 105, "center", "date"),
            ("source", "Kaynak", 130, "w", "text"),
            ("effect", "Borç/Alacak", 110, "center", "text"),
            ("amount", "Tutar", 115, "e", "money"),
            ("currency", "PB", 55, "center", "text"),
            ("try", "TL Karşılığı", 135, "e", "money"),
            ("desc", "Açıklama / Fatura", 360, "w", "text"),
        ]:
            self.txn_tree.heading(key, text=text, command=lambda col=key, sort_kind=kind: self._sort_treeview(self.txn_tree, col, sort_kind))
            self.txn_tree.column(key, width=width, anchor=anchor)
        self.txn_tree.tag_configure("paid", background=ROW_CLOSED_BG, foreground=ROW_CLOSED_FG)
        self.txn_tree.pack(fill="both", expand=True)
        self.txn_tree_menu = tk.Menu(self, tearoff=0)
        self.txn_tree_menu.add_command(label="Seçili hareketi sil", command=self.delete_selected_reconciliation_transaction)
        self.txn_tree.bind("<Button-3>", self._show_txn_tree_menu)

    def _build_period_tab(self) -> None:
        panel = ttk.Frame(self.period_tab, style="Card.TFrame", padding=18)
        panel.pack(fill="x")
        ttk.Label(panel, text="Devir Yap / Dönem Başlat", style="MetricTitle.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            panel,
            text=(
                "Kapanış tarihinden önceki tamamen ödenmiş işlemler silinir; açık kalan faturalar "
                "fatura no, tarih ve kalan tutarıyla yeni döneme aktarılır."
            ),
            style="Card.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 12))

        ttk.Label(panel, text="Kapanış Tarihi", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(panel, textvariable=self.period_close_date_var, width=16).grid(row=2, column=1, sticky="w", padx=(0, 18), pady=6)
        ttk.Label(panel, text="Muhasebeci Devir/Fazla Tutarı (TL)", style="Card.TLabel").grid(
            row=2, column=2, sticky="w", padx=(0, 8), pady=6
        )
        carryover_entry = ttk.Entry(panel, textvariable=self.period_carryover_amount_var, width=22)
        carryover_entry.grid(
            row=2, column=3, sticky="w", pady=6
        )
        self._bind_money_format(carryover_entry, self.period_carryover_amount_var)

        ttk.Button(panel, text="Açık Faturaları Önizle", command=self.preview_period_close).grid(
            row=3, column=1, sticky="w", pady=(12, 0)
        )
        ttk.Button(panel, text="Devir Yap / Dönem Başlat", command=self.close_period).grid(
            row=3, column=2, sticky="w", pady=(12, 0)
        )
        ttk.Button(panel, text="Devir/Fazla Tutarını Sıfırla", command=self.reset_period_carryover).grid(
            row=3, column=3, sticky="w", pady=(12, 0)
        )

        self.period_result = ttk.Label(self.period_tab, text="", style="Subtitle.TLabel")
        self.period_result.pack(anchor="w", pady=12)

        self.open_invoice_tree = ttk.Treeview(
            self.period_tab,
            columns=("company", "type", "date", "invoice", "remaining"),
            show="headings",
            height=17,
        )
        for key, text, width, anchor, kind in [
            ("company", "Cari", 330, "w", "text"),
            ("type", "Tip", 120, "center", "text"),
            ("date", "Fatura Tarihi", 110, "center", "date"),
            ("invoice", "Fatura No", 180, "w", "text"),
            ("remaining", "Kalan Tutar", 140, "e", "money"),
        ]:
            self.open_invoice_tree.heading(key, text=text, command=lambda col=key, sort_kind=kind: self._sort_treeview(self.open_invoice_tree, col, sort_kind))
            self.open_invoice_tree.column(key, width=width, anchor=anchor)
        self.open_invoice_tree.pack(fill="both", expand=True)

    def _build_monthly_tab(self) -> None:
        panel = ttk.Frame(self.monthly_tab, style="Card.TFrame", padding=14)
        panel.pack(fill="x", pady=(0, 10))
        ttk.Label(panel, text="Aylık Giden Fatura KDV'siz Tutarları", style="MetricTitle.TLabel").pack(side="left", padx=(0, 12))
        ttk.Label(panel, text="Yıl", style="Card.TLabel").pack(side="left", padx=(0, 6))
        # Yıl combobox'ı: veri olan yıllarla dolar
        self.monthly_year_combo = ttk.Combobox(
            panel, textvariable=self.monthly_year_var, width=8, state="readonly",
        )
        self.monthly_year_combo.pack(side="left", padx=(0, 10))
        self.monthly_year_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self.refresh_monthly_outgoing()
        )
        ttk.Button(panel, text="Grafiği Yenile", command=self.refresh_monthly_outgoing).pack(side="left")
        self.monthly_average_label = ttk.Label(panel, text="", style="Card.TLabel")
        self.monthly_average_label.pack(side="left", padx=(18, 0))
        self.monthly_trend_label = ttk.Label(panel, text="", style="Card.TLabel")
        self.monthly_trend_label.pack(side="left", padx=(18, 0))

        body = ttk.Frame(self.monthly_tab)
        body.pack(fill="both", expand=True)
        self.monthly_tree = ttk.Treeview(
            body,
            columns=("month", "amount"),
            show="headings",
            height=14,
        )
        self.monthly_tree.heading("month", text="Ay")
        self.monthly_tree.heading("amount", text="Giden Fatura KDV'siz")
        self.monthly_tree.column("month", width=160, anchor="w")
        self.monthly_tree.column("amount", width=180, anchor="e")
        self.monthly_tree.pack(side="left", fill="y", padx=(0, 14))

        self.monthly_canvas = tk.Canvas(body, height=360, bg="#ffffff", highlightthickness=1, highlightbackground="#cbd5df")
        self.monthly_canvas.pack(side="left", fill="both", expand=True)

    def _build_annual_tab(self) -> None:
        panel = ttk.Frame(self.annual_tab, style="Card.TFrame", padding=14)
        panel.pack(fill="x", pady=(0, 10))
        ttk.Label(panel, text="Yıllık Giden Fatura KDV'siz Tutarları", style="MetricTitle.TLabel").pack(side="left", padx=(0, 12))
        ttk.Label(panel, text="2024 / 2025 / 2026 karşılaştırması", style="Card.TLabel").pack(side="left")
        ttk.Button(panel, text="Grafiği Yenile", command=self.refresh_annual_outgoing).pack(side="right")

        body = ttk.Frame(self.annual_tab)
        body.pack(fill="both", expand=True)
        self.annual_tree = ttk.Treeview(
            body,
            columns=("year", "amount"),
            show="headings",
            height=8,
        )
        self.annual_tree.heading("year", text="Yıl")
        self.annual_tree.heading("amount", text="Giden Fatura KDV'siz")
        self.annual_tree.column("year", width=120, anchor="center")
        self.annual_tree.column("amount", width=220, anchor="e")
        self.annual_tree.pack(side="left", fill="y", padx=(0, 14))

        chart_frame = ttk.Frame(body)
        chart_frame.pack(side="left", fill="both", expand=True)
        self.annual_trend_label = ttk.Label(chart_frame, text="", style="Subtitle.TLabel")
        self.annual_trend_label.pack(anchor="w", pady=(0, 8))
        self.annual_canvas = tk.Canvas(chart_frame, height=360, bg="#ffffff", highlightthickness=1, highlightbackground="#cbd5df")
        self.annual_canvas.pack(fill="both", expand=True)

    def _build_turnover_tab(self) -> None:
        panel = ttk.Frame(self.turnover_tab, style="Card.TFrame", padding=14)
        panel.pack(fill="x", pady=(0, 10))
        ttk.Label(panel, text="Firma Bazında Yıllık Giden Ciro", style="MetricTitle.TLabel").pack(side="left", padx=(0, 12))
        ttk.Label(panel, text="Yıl", style="Card.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(panel, textvariable=self.turnover_year_var, width=8).pack(side="left", padx=(0, 10))
        ttk.Button(panel, text="Ciroyu Göster", command=self.refresh_company_turnover).pack(side="left")
        self.turnover_total_label = ttk.Label(panel, text="", style="Card.TLabel")
        self.turnover_total_label.pack(side="left", padx=(18, 0))

        self.turnover_tree = ttk.Treeview(
            self.turnover_tab,
            columns=("company", "tax", "gross", "net", "share"),
            show="headings",
            height=20,
        )
        for key, text, width, anchor, kind in [
            ("company", "Firma", 340, "w", "text"),
            ("tax", "VKN/TCKN", 120, "center", "text"),
            ("gross", "KDV Dahil Ciro", 160, "e", "money"),
            ("net", "KDV Hariç Ciro", 160, "e", "money"),
            ("share", "Toplam Ciro Oranı", 140, "e", "percent"),
        ]:
            self.turnover_tree.heading(key, text=text, command=lambda col=key, sort_kind=kind: self._sort_treeview(self.turnover_tree, col, sort_kind))
            self.turnover_tree.column(key, width=width, anchor=anchor)
        self.turnover_tree.pack(fill="both", expand=True)

    def _build_backup_tab(self) -> None:
        panel = ttk.Frame(self.backup_tab, style="Card.TFrame", padding=18)
        panel.pack(fill="x")
        ttk.Label(panel, text="Yedek / İçe-Dışa Aktarım", style="MetricTitle.TLabel").pack(anchor="w")
        ttk.Label(
            panel,
            text="CSV kayıtları, manuel işlemler, devirler ve ayarlar yerel SQLite veritabanı olarak dışa/içe aktarılır.",
            style="Card.TLabel",
        ).pack(anchor="w", pady=(6, 12))
        ttk.Button(panel, text="Tüm Verileri Dışa Aktar", command=self.export_database).pack(side="left", padx=(0, 10))
        ttk.Button(panel, text="Yedekten İçe Aktar", command=self.import_database).pack(side="left")
        self.backup_result = ttk.Label(self.backup_tab, text="", style="Subtitle.TLabel")
        self.backup_result.pack(anchor="w", pady=14)

    def import_csv(self, profile_name: str) -> None:
        path = filedialog.askopenfilename(
            title=f"{profile_name} CSV dosyasını seçin",
            filetypes=[("CSV Dosyaları", "*.csv"), ("Tüm Dosyalar", "*.*")],
        )
        if not path:
            return
        try:
            result = import_uyumsoft_csv(self.db, path, profile_name)
            lines = [
                f"Dosya: {path}",
                f"Tip: {result.profile_name}",
                f"Toplam satır: {result.total_rows}",
                f"Yeni eklenen: {result.imported_rows}",
                f"Tekrar olduğu için atlanan: {result.skipped_duplicates}",
                f"Leasing/finansal kiralama olduğu için atlanan: {result.skipped_blacklisted_leasing}",
                f"Hatalı satır: {result.failed_rows}",
            ]
            if result.errors:
                lines.append("")
                lines.append("Hatalar:")
                lines.extend(result.errors[:25])
                if len(result.errors) > 25:
                    lines.append(f"... {len(result.errors) - 25} hata daha")
            self._write_import_result("\n".join(lines) + "\n\n")
            self.refresh_all()
        except Exception as exc:
            messagebox.showerror("CSV içe aktarma hatası", str(exc))

    def reset_imported_csvs(self) -> None:
        count = self.db.csv_transaction_count()
        if count == 0:
            messagebox.showinfo("CSV sıfırlama", "Silinecek içe aktarılmış CSV fatura kaydı bulunmuyor.")
            return
        if not messagebox.askyesno(
            "CSV Sıfırlama Onayı",
            (
                f"{count} adet içe aktarılmış Gelen/Giden fatura kaydı silinecek.\n\n"
                "Manuel ödeme/tahsilat kayıtları korunacak.\n"
                "Bu işlem geri alınamaz. Devam edilsin mi?"
            ),
        ):
            return
        result = self.db.reset_imported_csv_transactions()
        self._write_import_result(
            (
                "CSV sıfırlama tamamlandı.\n"
                f"Silinen fatura hareketi: {result.deleted_transactions}\n"
                f"Temizlenen boş cari: {result.deleted_orphan_companies}\n\n"
            )
        )
        self.refresh_all()
        messagebox.showinfo(
            "CSV sıfırlama tamamlandı",
            f"{result.deleted_transactions} adet içe aktarılmış CSV fatura kaydı silindi.",
        )

    def save_manual_transaction(self) -> None:
        try:
            txn_date = parse_user_date(self.manual_vars["date"].get())
            company_name = self.manual_vars["company"].get().strip()
            if not company_name:
                raise ValueError("Cari/Firma adı zorunlu")
            amount = parse_decimal(self.manual_vars["amount"].get())
            if amount <= 0:
                raise ValueError("Tutar sıfırdan büyük olmalı")
            currency = self.manual_vars["currency"].get().strip().upper() or "TRY"
            rate = parse_decimal(self.manual_vars["rate"].get())
            try_amount = amount_try(amount, currency, rate)
            is_payment = self.manual_vars["type"].get().startswith("Gelen Fatura Menüsü")
            source_type = SOURCE_MANUAL_PAYMENT if is_payment else SOURCE_MANUAL_COLLECTION
            effect = EFFECT_DEBIT if is_payment else EFFECT_CREDIT
            company_id = self.db.upsert_company(
                name=company_name,
                tax_id=self.manual_vars["tax_id"].get(),
            )
            external_key = f"{source_type}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            desc = self.manual_vars["description"].get().strip()
            self.db.add_transaction(
                company_id=company_id,
                source_type=source_type,
                account_effect=effect,
                txn_date=txn_date,
                txn_datetime=f"{txn_date} 00:00:00",
                external_key=external_key,
                description=desc or ("Gelen fatura ödemesi" if is_payment else "Giden fatura tahsilatı"),
                amount_original=amount,
                currency=currency,
                exchange_rate=rate if rate > 0 else 1.0,
                amount_try=try_amount,
                raw={"manual": True},
            )
            self.manual_result.configure(text=f"Kaydedildi: {company_name} - {money_try(try_amount)}")
            for key in ("amount", "description"):
                self.manual_vars[key].set("")
            self.refresh_all()
        except Exception as exc:
            messagebox.showerror("Manuel işlem hatası", str(exc))

    def preview_period_close(self) -> None:
        try:
            closing_date = parse_user_date(self.period_close_date_var.get())
            invoices = self.db.open_invoices_as_of(closing_date)
            self._fill_open_invoice_tree(invoices)
            self.period_result.configure(
                text=(
                    f"{format_user_date_from_iso(closing_date)} itibarıyla "
                    f"{len(invoices)} açık fatura, toplam {money_try(sum(i.remaining_try for i in invoices))}."
                )
            )
        except Exception as exc:
            messagebox.showerror("Devir önizleme hatası", str(exc))

    def close_period(self) -> None:
        try:
            closing_date = parse_user_date(self.period_close_date_var.get())
            carryover_amount = parse_decimal(self.period_carryover_amount_var.get())
            invoices = self.db.open_invoices_as_of(closing_date)
            if not messagebox.askyesno(
                "Devir Onayı",
                (
                    f"{format_user_date_from_iso(closing_date)} ve öncesi kapanacak.\n"
                    f"{len(invoices)} açık fatura yeni döneme aktarılacak.\n"
                    "Tamamen kapanmış eski işlemler silinecek. Devam edilsin mi?"
                ),
            ):
                return
            result = self.db.close_period(closing_date, carryover_amount)
            self.period_result.configure(
                text=(
                    f"Devir tamamlandı. Yeni dönem: {format_user_date_from_iso(result.period_start_date)}. "
                    f"Aktarılan açık fatura: {result.open_invoice_count}, "
                    f"açık toplam: {money_try(result.open_invoice_total_try)}."
                )
            )
            self._fill_open_invoice_tree(self.db.open_invoices_as_of(result.period_start_date))
            self.refresh_all()
        except Exception as exc:
            messagebox.showerror("Devir hatası", str(exc))

    def reset_period_carryover(self) -> None:
        count = self.db.period_carryover_count()
        if count == 0:
            messagebox.showinfo("Devir/Fazla sıfırlama", "Sıfırlanacak devir/fazla tutarı bulunmuyor.")
            return
        if not messagebox.askyesno(
            "Devir/Fazla Sıfırlama Onayı",
            (
                f"{count} adet devir/fazla tutarı kaydı silinecek.\n\n"
                "Açık fatura devirleri ve manuel işlemler korunacak.\n"
                "Bu işlem geri alınamaz. Devam edilsin mi?"
            ),
        ):
            return
        result = self.db.reset_period_carryover_data()
        self.period_result.configure(
            text=(
                "Devir/Fazla sıfırlandı. "
                f"Silinen devir/fazla hareketi: {result.deleted_transactions}, "
                f"silinen kapanış kaydı: {result.deleted_period_closures}."
            )
        )
        self.refresh_all()
        messagebox.showinfo("Devir/Fazla sıfırlama tamamlandı", "Devir/Fazla tutarı kayıtları silindi.")

    def _fill_open_invoice_tree(self, invoices) -> None:
        for item in self.open_invoice_tree.get_children():
            self.open_invoice_tree.delete(item)
        for invoice in invoices:
            self.open_invoice_tree.insert(
                "",
                "end",
                values=(
                    invoice.company_name,
                    "Giden/BORÇ" if invoice.source_type == OUTGOING_PROFILE.source_type else "Gelen/ALACAK",
                    format_user_date_from_iso(invoice.txn_date),
                    invoice.invoice_no or invoice.document_no,
                    money_try(invoice.remaining_try),
                ),
            )

    def calculate_reconciliation(self) -> None:
        try:
            company_label = self.reconcile_company_var.get()
            company_id = self.company_lookup.get(company_label)
            if not company_id:
                raise ValueError("Lütfen bir cari seçin")
            as_of = parse_user_date(self.as_of_var.get())
            balance = self.db.balance_for_company(company_id, as_of)
            self.reconciliation_result.configure(
                text=(
                    f"{format_user_date_from_iso(as_of)} Tarihi İtibariyle Net Bakiye: "
                    f"{signed_balance_text(balance)}"
                )
            )
            self._fill_transactions(company_id, as_of)
        except Exception as exc:
            messagebox.showerror("Mutabakat hatası", str(exc))

    def refresh_all(self) -> None:
        self.db.delete_blacklisted_leasing_records()
        self.today_label.configure(text=f"Bugün: {date.today().strftime('%d.%m.%Y')}")
        try:
            start_date, end_date = self._dashboard_date_range()
        except ValueError as exc:
            messagebox.showerror("Tarih aralığı hatası", str(exc))
            return
        totals = self.db.dashboard_totals(start_date=start_date, end_date=end_date)
        current_totals = self.db.dashboard_totals(
            start_date=self._default_dashboard_start_iso(),
            end_date=today_iso(),
        )
        self.market_receivable_value.configure(text=money_try(max(totals.market_receivable_try, 0.0)))
        net_style = "DangerMetric.TLabel" if current_totals.net_financial_position_try > 0 else "PositiveMetric.TLabel"
        self.net_position_value.configure(
            text=money_try(current_totals.net_financial_position_try),
            style=net_style,
        )
        self.summary_labels["Giden Fatura"].configure(text=money_try(totals.outgoing_invoices_try))
        self.summary_labels["Giden KDV'siz"].configure(text=money_try(totals.outgoing_invoices_net_try))
        self.summary_labels["Gelen Fatura"].configure(text=money_try(totals.incoming_invoices_try))
        self.summary_labels["Gelen KDV'siz"].configure(text=money_try(totals.incoming_invoices_net_try))
        self.summary_labels["Tedarikçi Ödemesi"].configure(text=money_try(totals.manual_payments_try))
        self.summary_labels["Müşteri Tahsilatı"].configure(text=money_try(totals.manual_collections_try))
        self.summary_labels["Kalan Borç"].configure(text=money_try(totals.current_payable_try))
        self.summary_labels["Devir/Fazla"].configure(text=money_try(totals.period_carryover_try))
        self.summary_labels["Cari Sayısı"].configure(text=str(totals.company_count))
        self.summary_labels["İşlem Sayısı"].configure(text=str(totals.transaction_count))
        self._fill_company_tree(start_date, end_date)
        self._refresh_company_combo()
        if hasattr(self, "manual_outgoing_company_combo"):
            self._refresh_manual_outgoing_company_filter()
        if hasattr(self, "outgoing_status_tree"):
            self.refresh_outgoing_invoice_statuses()
        if hasattr(self, "monthly_tree"):
            self.refresh_monthly_outgoing()
        if hasattr(self, "annual_tree"):
            self.refresh_annual_outgoing()
        if hasattr(self, "turnover_tree"):
            self.refresh_company_turnover()

    def _dashboard_date_range(self) -> tuple[str | None, str | None]:
        start_text = self.dashboard_start_var.get().strip()
        end_text = self.dashboard_end_var.get().strip()
        start_date = parse_user_date(start_text) if start_text else None
        end_date = parse_user_date(end_text) if end_text else None
        if start_date and end_date and start_date > end_date:
            raise ValueError("Başlangıç tarihi bitiş tarihinden büyük olamaz")
        return start_date, end_date

    def _reset_dashboard_dates(self) -> None:
        self.dashboard_start_var.set(format_user_date_from_iso(self._default_dashboard_start_iso()))
        self.dashboard_end_var.set(date.today().strftime("%d.%m.%Y"))
        self.refresh_all()

    def _default_dashboard_start_iso(self) -> str:
        month_start = date.today().replace(day=1).isoformat()
        active_period_start = self.db.active_period_start_date()
        if active_period_start and active_period_start > month_start:
            return active_period_start
        return month_start

    def _fill_company_tree(self, start_date: str | None = None, end_date: str | None = None) -> None:
        for item in self.company_tree.get_children():
            self.company_tree.delete(item)
        grouped: dict[int, dict] = {}
        for invoice in self.db.outgoing_invoice_statuses():
            if invoice.remaining_try <= 0.005:
                continue
            if start_date and invoice.txn_date < start_date:
                continue
            if end_date and invoice.txn_date > end_date:
                continue
            row = grouped.setdefault(
                invoice.company_id,
                {
                    "id": invoice.company_id,
                    "name": invoice.company_name,
                    "tax_id": invoice.tax_id,
                    "last_txn_date": invoice.txn_date,
                    "debit_try": 0.0,
                    "credit_try": 0.0,
                    "balance_try": 0.0,
                    "transaction_count": 0,
                    "fx": {},
                },
            )
            row["last_txn_date"] = max(row["last_txn_date"], invoice.txn_date)
            row["debit_try"] += invoice.remaining_try
            row["balance_try"] += invoice.remaining_try
            row["transaction_count"] += 1
            if invoice.currency in {"USD", "EUR"} and invoice.remaining_original > 0.005:
                row["fx"][invoice.currency] = row["fx"].get(invoice.currency, 0.0) + invoice.remaining_original
        rows = list(grouped.values())
        search_text = self.company_search_var.get().strip().casefold()
        if search_text:
            rows = [row for row in rows if search_text in row["name"].casefold()]
        if self.company_sort_key == "date":
            rows.sort(key=lambda row: row["last_txn_date"] or "", reverse=self.company_sort_reverse)
        elif self.company_sort_key == "debit":
            rows.sort(key=lambda row: float(row["debit_try"] or 0), reverse=self.company_sort_reverse)
        elif self.company_sort_key == "credit":
            rows.sort(key=lambda row: float(row["credit_try"] or 0), reverse=self.company_sort_reverse)
        elif self.company_sort_key == "balance":
            rows.sort(key=lambda row: float(row["balance_try"] or 0), reverse=self.company_sort_reverse)
        else:
            rows.sort(key=lambda row: row["name"].casefold(), reverse=self.company_sort_reverse)
        for row in rows:
            self.company_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                text=row["name"],
                values=(
                    row["tax_id"],
                    format_user_date_from_iso(row["last_txn_date"]) if row["last_txn_date"] else "-",
                    money_try(row["debit_try"]),
                    money_try(row["credit_try"]),
                    self._format_open_fx_summary(row["fx"]),
                    money_try(row["balance_try"]),
                    row["transaction_count"],
                ),
            )

    def _format_open_fx_summary(self, fx: dict[str, float]) -> str:
        parts = []
        for currency in ("USD", "EUR"):
            amount = fx.get(currency, 0.0)
            if amount > 0.005:
                parts.append(f"Alacak {money_original(amount, currency)}")
        return "; ".join(parts)

    def _format_currency_summary(self, summaries) -> str:
        parts = []
        for item in summaries:
            currency_parts = []
            if abs(item.debit_original) > 0.005:
                currency_parts.append(f"Alacak {money_original(item.debit_original, item.currency)}")
            if abs(item.credit_original) > 0.005:
                currency_parts.append(f"Borç {money_original(item.credit_original, item.currency)}")
            if currency_parts:
                parts.append(" / ".join(currency_parts))
        return "; ".join(parts)

    def _sort_company_tree(self, key: str) -> None:
        if self.company_sort_key == key:
            self.company_sort_reverse = not self.company_sort_reverse
        else:
            self.company_sort_key = key
            self.company_sort_reverse = key in {"date", "debit", "credit", "balance"}
        try:
            start_date, end_date = self._dashboard_date_range()
        except ValueError:
            start_date, end_date = None, today_iso()
        self._fill_company_tree(start_date, end_date)

    def refresh_outgoing_invoice_statuses(self) -> None:
        for item in self.outgoing_status_tree.get_children():
            self.outgoing_status_tree.delete(item)
        selected_company = self.manual_outgoing_company_var.get()
        for invoice in self.db.outgoing_invoice_statuses():
            label = self._manual_outgoing_company_label(invoice.company_name, invoice.tax_id)
            if selected_company and selected_company != "Tüm Firmalar" and selected_company != label:
                continue
            tag = "paid" if invoice.is_paid else "open"
            self.outgoing_status_tree.insert(
                "",
                "end",
                iid=str(invoice.transaction_id),
                values=(
                    invoice.company_name,
                    format_user_date_from_iso(invoice.txn_date),
                    invoice.invoice_no,
                    money_try(invoice.amount_try),
                    money_try(invoice.collected_try),
                    money_try(invoice.remaining_try),
                    "Ödeme geldi" if invoice.is_paid else "Ödeme yok/açık",
                ),
                tags=(tag,),
            )

    def _manual_outgoing_company_label(self, company_name: str, tax_id: str) -> str:
        return f"{company_name} ({tax_id})" if tax_id else company_name

    def _refresh_manual_outgoing_company_filter(self) -> None:
        current = self.manual_outgoing_company_var.get()
        labels = ["Tüm Firmalar"]
        seen = set(labels)
        for invoice in self.db.outgoing_invoice_statuses():
            label = self._manual_outgoing_company_label(invoice.company_name, invoice.tax_id)
            if label not in seen:
                labels.append(label)
                seen.add(label)
        self.manual_outgoing_company_combo.configure(values=labels)
        if current not in labels:
            self.manual_outgoing_company_var.set("Tüm Firmalar")

    def _show_outgoing_status_menu(self, event: tk.Event) -> None:
        item_id = self.outgoing_status_tree.identify_row(event.y)
        if not item_id:
            return
        self._select_context_item(self.outgoing_status_tree, item_id, event)
        self.outgoing_status_menu.tk_popup(event.x_root, event.y_root)

    def mark_selected_outgoing_paid(self) -> None:
        selected = self.outgoing_status_tree.selection()
        if not selected:
            return
        if not messagebox.askyesno(
            "Ödendi Onayı",
            f"{len(selected)} giden faturanın kalan tutarı tahsil edildi olarak kaydedilsin mi?",
        ):
            return
        try:
            ids = [int(item_id) for item_id in selected]
            total_paid, errors = self.db.mark_outgoing_invoices_paid_bulk(ids)
            if errors:
                detail = "\n".join(f"- Fatura #{tid}: {msg}" for tid, msg in errors[:8])
                messagebox.showerror(
                    "Ödendi hatası",
                    f"İşlem atomik olarak geri alındı, hiçbir değişiklik yapılmadı.\n\n{detail}",
                )
                return
            messagebox.showinfo("Ödendi", f"Tahsilat kaydı oluşturuldu: {money_try(total_paid)}")
            self.refresh_all()
        except Exception as exc:
            messagebox.showerror("Ödendi hatası", str(exc))

    def unmark_selected_outgoing_paid(self) -> None:
        selected = self.outgoing_status_tree.selection()
        if not selected:
            return
        if not messagebox.askyesno("Ödenmedi Onayı", f"{len(selected)} fatura için otomatik ödendi kayıtları kaldırılsın mı?"):
            return
        deleted = 0
        for item_id in selected:
            deleted += self.db.unmark_outgoing_invoice_paid(int(item_id))
        self.refresh_all()
        messagebox.showinfo("Ödenmedi", f"Kaldırılan otomatik tahsilat kaydı: {deleted}")

    def _select_context_item(self, tree: ttk.Treeview, item_id: str, event: tk.Event) -> None:
        ctrl_pressed = bool(event.state & 0x0004)
        current = set(tree.selection())
        if ctrl_pressed:
            current.add(item_id)
            tree.selection_set(tuple(current))
        elif item_id not in current:
            tree.selection_set(item_id)

    def _show_txn_tree_menu(self, event: tk.Event) -> None:
        item_id = self.txn_tree.identify_row(event.y)
        if not item_id:
            return
        self._select_context_item(self.txn_tree, item_id, event)
        self.txn_tree_menu.tk_popup(event.x_root, event.y_root)

    def mark_selected_reconciliation_paid(self) -> None:
        messagebox.showinfo("Cari Mutabakat", "Ödendi işlemi Manuel İşlemler ekranından yapılmalıdır.")

    def unmark_selected_reconciliation_paid(self) -> None:
        messagebox.showinfo("Cari Mutabakat", "Ödenmedi işlemi Manuel İşlemler ekranından yapılmalıdır.")

    def delete_selected_reconciliation_transaction(self) -> None:
        selected = self.txn_tree.selection()
        if not selected:
            return
        if not messagebox.askyesno("Silme Onayı", f"{len(selected)} hareket silinsin mi?"):
            return
        for item_id in selected:
            self.db.delete_transaction(int(item_id))
        self.calculate_reconciliation()
        self.refresh_all()

    def _tree_sort_value(self, value: str, kind: str):
        if kind == "money":
            text = value.replace("TL", "").strip().replace(".", "").replace(",", ".")
            try:
                return float(text)
            except ValueError:
                return 0.0
        if kind == "date":
            try:
                return datetime.strptime(value, "%d.%m.%Y")
            except ValueError:
                return datetime.min
        if kind == "percent":
            text = value.replace("%", "").strip().replace(".", "").replace(",", ".")
            try:
                return float(text)
            except ValueError:
                return 0.0
        return value.casefold()

    def _sort_treeview(self, tree: ttk.Treeview, column: str, kind: str = "text") -> None:
        key = (id(tree), column)
        reverse = not self.tree_sort_state.get(key, False)
        self.tree_sort_state[key] = reverse
        items = list(tree.get_children(""))
        items.sort(key=lambda item: self._tree_sort_value(str(tree.set(item, column)), kind), reverse=reverse)
        for index, item in enumerate(items):
            tree.move(item, "", index)

    def export_database(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Veritabanı yedeğini kaydet",
            defaultextension=".sqlite3",
            filetypes=[("SQLite Veritabanı", "*.sqlite3"), ("Tüm Dosyalar", "*.*")],
        )
        if not path:
            return
        try:
            destination = sqlite3.connect(path)
            with destination:
                self.db.conn.backup(destination)
            destination.close()
            self.backup_result.configure(text=f"Yedek dışa aktarıldı: {path}")
            messagebox.showinfo("Yedek", "Tüm veriler dışa aktarıldı.")
        except Exception as exc:
            messagebox.showerror("Yedek dışa aktarma hatası", str(exc))

    def import_database(self) -> None:
        path = filedialog.askopenfilename(
            title="İçe aktarılacak veritabanı yedeğini seç",
            filetypes=[("SQLite Veritabanı", "*.sqlite3"), ("Tüm Dosyalar", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Yedekten İçe Aktar",
            "Mevcut tüm veriler seçilen yedekle değiştirilecek. Devam edilsin mi?",
        ):
            return
        current_db_path = self.db.db_path
        try:
            self.db.close()
            shutil.copy2(path, current_db_path)
            self.db = LedgerDatabase(current_db_path)
            self.backup_result.configure(text=f"Yedek içe aktarıldı: {path}")
            self.refresh_all()
            messagebox.showinfo("Yedek", "Yedek içe aktarıldı.")
        except Exception as exc:
            self.db = LedgerDatabase(current_db_path)
            messagebox.showerror("Yedek içe aktarma hatası", str(exc))

    def refresh_company_turnover(self) -> None:
        try:
            year = int(self.turnover_year_var.get().strip())
        except ValueError:
            messagebox.showerror("Firma ciro", "Yıl sayısal olmalı.")
            return
        for item in self.turnover_tree.get_children():
            self.turnover_tree.delete(item)
        rows = self.db.company_yearly_outgoing_turnover(year)
        total_gross = sum(row.gross_try for row in rows)
        total_net = sum(row.net_try for row in rows)
        self.turnover_total_label.configure(
            text=f"Toplam: {money_try(total_gross)} KDV dahil / {money_try(total_net)} KDV hariç"
        )
        for row in rows:
            self.turnover_tree.insert(
                "",
                "end",
                values=(
                    row.company_name,
                    row.tax_id,
                    money_try(row.gross_try),
                    money_try(row.net_try),
                    percent_try(row.share_percent),
                ),
            )

    def refresh_monthly_outgoing(self) -> None:
        # Combobox'ı veri olan yıllarla doldur (geçerli yıl + bulunanların birleşimi)
        available_years = self.db.outgoing_invoice_years()
        current_year = date.today().year
        all_years = sorted(set(available_years + [current_year]), reverse=True)
        if hasattr(self, "monthly_year_combo"):
            self.monthly_year_combo.configure(values=[str(y) for y in all_years])
            if self.monthly_year_var.get() not in {str(y) for y in all_years}:
                self.monthly_year_var.set(str(all_years[0]) if all_years else str(current_year))
        try:
            year = int(self.monthly_year_var.get().strip())
        except ValueError:
            messagebox.showerror("Aylık grafik", "Yıl sayısal olmalı.")
            return
        month_names = [
            "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
        ]
        totals = self.db.monthly_outgoing_net_totals(year)
        for item in self.monthly_tree.get_children():
            self.monthly_tree.delete(item)
        for month_no, total in totals:
            self.monthly_tree.insert("", "end", values=(month_names[month_no - 1], money_try(total)))
        average = sum(total for _month, total in totals) / 12
        self.monthly_average_label.configure(text=f"12 Aylık Ortalama: {money_try(average)}")
        non_zero = [total for _month, total in totals if total > 0]
        if len(non_zero) >= 2:
            trend = "Yukarı yönlü" if non_zero[-1] > non_zero[0] else "Aşağı yönlü" if non_zero[-1] < non_zero[0] else "Yatay"
            self.monthly_trend_label.configure(text=f"Eğilim: {trend}")
        else:
            self.monthly_trend_label.configure(text="Eğilim: veri bekleniyor")
        self._draw_monthly_chart(totals, month_names)

    def _draw_monthly_chart(self, totals: list[tuple[int, float]], month_names: list[str]) -> None:
        canvas = self.monthly_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 720)
        height = max(canvas.winfo_height(), 340)
        left, right, top, bottom = 54, 24, 24, 54
        chart_width = width - left - right
        chart_height = height - top - bottom
        canvas.create_line(left, top, left, top + chart_height, fill="#6b7280", width=2)
        canvas.create_line(left, top + chart_height, left + chart_width, top + chart_height, fill="#6b7280", width=2)
        max_total = max((total for _month, total in totals), default=0)
        if max_total <= 0:
            canvas.create_text(width / 2, height / 2, text="Bu yıl için giden fatura verisi yok", fill="#5b6472", font=("Segoe UI", 13, "bold"))
            return
        points = []
        for index, (month_no, total) in enumerate(totals):
            x = left + (chart_width * index / 11)
            y = top + chart_height - (total / max_total * chart_height)
            points.append((x, y, month_no, total))
        for step in range(5):
            y = top + chart_height - (chart_height * step / 4)
            canvas.create_line(left, y, left + chart_width, y, fill="#edf2f7")
        for idx in range(len(points) - 1):
            x1, y1, _m1, _t1 = points[idx]
            x2, y2, _m2, _t2 = points[idx + 1]
            color = POSITIVE_COLOR if y2 < y1 else NEGATIVE_COLOR if y2 > y1 else ACCENT_COLOR
            canvas.create_line(x1, y1, x2, y2, fill=color, width=3)
        for x, y, month_no, total in points:
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=ACCENT_DARK, outline="#ffffff", width=2)
            canvas.create_text(x, top + chart_height + 18, text=month_names[month_no - 1][:3], fill="#374151", font=("Segoe UI", 8, "bold"))
            if total > 0:
                canvas.create_text(x, y - 14, text=f"{total/1000:.0f}K", fill=ACCENT_DARK, font=("Segoe UI", 8, "bold"))

    def refresh_annual_outgoing(self) -> None:
        totals = self.db.yearly_outgoing_net_totals(self.annual_years)
        for item in self.annual_tree.get_children():
            self.annual_tree.delete(item)
        for year, total in totals:
            self.annual_tree.insert("", "end", values=(year, money_try(total)))
        non_zero = [(year, total) for year, total in totals if total > 0]
        if len(non_zero) >= 2:
            first_year, first_total = non_zero[0]
            last_year, last_total = non_zero[-1]
            trend = "Yukarı yönlü" if last_total > first_total else "Aşağı yönlü" if last_total < first_total else "Yatay"
            self.annual_trend_label.configure(text=f"Eğilim: {first_year} -> {last_year} {trend}")
        else:
            self.annual_trend_label.configure(text="Eğilim: karşılaştırma için veri bekleniyor")
        self._draw_annual_chart(totals)

    def _draw_annual_chart(self, totals: list[tuple[int, float]]) -> None:
        canvas = self.annual_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 520)
        height = max(canvas.winfo_height(), 340)
        left, right, top, bottom = 60, 30, 30, 58
        chart_width = width - left - right
        chart_height = height - top - bottom
        canvas.create_line(left, top, left, top + chart_height, fill="#6b7280", width=2)
        canvas.create_line(left, top + chart_height, left + chart_width, top + chart_height, fill="#6b7280", width=2)
        max_total = max((total for _year, total in totals), default=0)
        if max_total <= 0:
            canvas.create_text(width / 2, height / 2, text="2024/2025/2026 için giden fatura verisi yok", fill="#5b6472", font=("Segoe UI", 13, "bold"))
            return
        gap = chart_width / max(len(totals), 1)
        bar_width = min(90, gap * 0.55)
        for index, (year, total) in enumerate(totals):
            x_center = left + gap * index + gap / 2
            bar_height = total / max_total * chart_height
            x1 = x_center - bar_width / 2
            y1 = top + chart_height - bar_height
            x2 = x_center + bar_width / 2
            y2 = top + chart_height
            canvas.create_rectangle(x1, y1, x2, y2, fill=ACCENT_COLOR, outline=ACCENT_DARK, width=2)
            canvas.create_text(x_center, y1 - 14, text=f"{total/1000:.0f}K", fill=ACCENT_DARK, font=("Segoe UI", 9, "bold"))
            canvas.create_text(x_center, top + chart_height + 20, text=str(year), fill="#374151", font=("Segoe UI", 10, "bold"))
        points = []
        for index, (year, total) in enumerate(totals):
            x_center = left + gap * index + gap / 2
            y = top + chart_height - (total / max_total * chart_height)
            points.append((x_center, y, year, total))
        for index in range(len(points) - 1):
            x1, y1, _year1, _total1 = points[index]
            x2, y2, _year2, _total2 = points[index + 1]
            color = POSITIVE_COLOR if y2 < y1 else NEGATIVE_COLOR if y2 > y1 else ACCENT_DARK
            canvas.create_line(x1, y1, x2, y2, fill=color, width=3)
            canvas.create_oval(x1 - 4, y1 - 4, x1 + 4, y1 + 4, fill=color, outline="#ffffff", width=2)
        if points:
            x, y, _year, _total = points[-1]
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=ACCENT_DARK, outline="#ffffff", width=2)

    def _bind_money_format(self, entry: ttk.Entry, variable: tk.StringVar) -> None:
        def format_var(_event: tk.Event | None = None) -> None:
            text = variable.get().strip()
            if not text:
                return
            try:
                variable.set(money_input(parse_decimal(text)))
            except ValueError:
                return

        entry.bind("<FocusOut>", format_var)
        entry.bind("<Return>", format_var)

    def _debounce(self, key: str, delay_ms: int, callback) -> None:
        """Hızlı tekrar eden olayları (KeyRelease vb.) belirli bir gecikmeyle teklenmiş tek çağrıya indirir."""
        prev_job = self._debounce_jobs.get(key)
        if prev_job:
            try:
                self.after_cancel(prev_job)
            except tk.TclError:
                pass
        self._debounce_jobs[key] = self.after(delay_ms, callback)

    def _on_currency_selected(self, _event: tk.Event) -> None:
        if self.manual_vars["currency"].get().upper() == "TRY":
            self.manual_vars["rate"].set("1")

    def _auto_fill_manual_tax_id(self, _event: tk.Event | None = None) -> None:
        company = self.db.find_company_by_name(self.manual_vars["company"].get())
        if company and company.tax_id:
            self.manual_vars["tax_id"].set(company.tax_id)

    def _refresh_company_combo(self) -> None:
        labels: list[str] = []
        self.company_lookup.clear()
        for company in self.db.list_companies():
            label = f"{company.name} ({company.tax_id})" if company.tax_id else company.name
            labels.append(label)
            self.company_lookup[label] = company.id
        self.company_combo.configure(values=labels)
        if labels and self.reconcile_company_var.get() not in labels:
            self.reconcile_company_var.set(labels[0])

    def _fill_transactions(self, company_id: int, as_of: str | None) -> None:
        for item in self.txn_tree.get_children():
            self.txn_tree.delete(item)
        company_label = self.reconcile_company_var.get()
        company_name = company_label.rsplit(" (", 1)[0] if company_label else ""
        paid_statuses = {
            status.transaction_id: status.is_paid
            for status in self.db.outgoing_invoice_statuses()
            if status.company_id == company_id
        }
        source_names = {
            "outgoing_invoice": "Giden Fatura",
            "incoming_invoice": "Gelen Fatura",
            "manual_payment": "Tedarikçi Ödemesi",
            "manual_collection": "Müşteri Tahsilatı",
        }
        effect_names = {
            "outgoing_invoice": "BORÇ",
            "manual_payment": "BORÇ",
            "incoming_invoice": "ALACAK",
            "manual_collection": "ALACAK",
            "period_carryover": "DEVİR",
        }
        for row in self.db.transactions_for_company(company_id, as_of):
            # is_auto_paid kolonu indexed; bu auto-paid markerlarını UI'da gösterme
            try:
                auto_paid_marker = bool(row["is_auto_paid"])
            except (IndexError, KeyError):
                auto_paid_marker = False
            if auto_paid_marker:
                continue
            amount_text = money_input(float(row["amount_original"]))
            description = row["description"] or row["invoice_no"]
            is_paid_invoice = row["source_type"] == "outgoing_invoice" and paid_statuses.get(int(row["id"]), False)
            if is_paid_invoice:
                description = f"{description} - ÖDENDİ"
            self.txn_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    company_name,
                    format_user_date_from_iso(row["txn_date"]),
                    source_names.get(row["source_type"], row["source_type"]),
                    effect_names.get(row["source_type"], "BORÇ" if row["account_effect"] == EFFECT_DEBIT else "ALACAK"),
                    amount_text,
                    row["currency"],
                    money_try(row["amount_try"]),
                    description,
                ),
                tags=("paid",) if is_paid_invoice else (),
            )

    def _write_import_result(self, text: str) -> None:
        self.import_result.configure(state="normal")
        self.import_result.insert("end", text)
        self.import_result.see("end")
        self.import_result.configure(state="disabled")

    def _on_dashboard_company_selected(self, _event: tk.Event) -> None:
        selected = self.company_tree.selection()
        if not selected:
            return
        company_id = int(selected[0])
        for label, item_id in self.company_lookup.items():
            if item_id == company_id:
                self.reconcile_company_var.set(label)
                self.notebook.select(self.reconcile_tab)
                self.calculate_reconciliation()
                break


def main() -> None:
    app = MefeAccountingApp()
    app.mainloop()
