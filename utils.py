from calendar import monthrange
from babel.numbers import format_currency as babel_format_currency
from babel.dates import format_date as babel_format_date

def money_br(v: float) -> str:
    try:
        return babel_format_currency(float(v), 'BRL', locale='pt_BR')
    except Exception:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def date_br(d) -> str:
    try:
        return babel_format_date(d, format='short', locale='pt_BR')
    except Exception:
        return d.strftime('%d/%m/%y') if hasattr(d, "strftime") else str(d)

def dias_do_mes(d) -> int:
    return monthrange(d.year, d.month)[1]
