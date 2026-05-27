from __future__ import annotations


def money_try(value: float) -> str:
    """Tüm uygulamada kullanılan tek TL formatlama fonksiyonu (suffix dahil)."""
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} TL"


def money_input(value: float) -> str:
    """Input alanlarında kullanılan TL formatı (suffix yok)."""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def money_original(value: float, currency: str) -> str:
    """Para birimi ile birlikte orijinal tutar formatı (USD/EUR vb.)."""
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} {currency.upper()}"


def percent_try(value: float) -> str:
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"%{formatted}"


def signed_balance_text(value: float) -> str:
    if value > 0:
        return f"{money_try(value)} BORÇ (cari bize borçlu)"
    if value < 0:
        return f"{money_try(abs(value))} ALACAK (biz firmaya borçluyuz)"
    return "0,00 TL (kapalı)"
