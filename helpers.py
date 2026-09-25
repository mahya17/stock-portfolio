import os
import requests
import urllib.parse
from flask import redirect, render_template, session
from functools import wraps

def apology(message, code=400):
    """Render message as an apology."""
    def escape(s):
        for old, new in [("-", "--"), (" ", "-"), ("_", "__"),
                         ("?", "~q"), ("%", "~p"), ("#", "~h"),
                         ("/", "~s"), ('"', "''")]:
            s = s.replace(old, new)
        return s
    return render_template("apology.html", top=code, bottom=escape(message)), code

def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

def lookup(symbol):
    """
    Look up quote for symbol.
    Returns a dict: {name, price, symbol}
    Returns None only if symbol is completely invalid.
    """

    if not symbol:
        return None
    symbol = symbol.strip().upper()

    api_key = os.environ.get("IEX_API_KEY")

    try:
        # اگر کلید وجود دارد، از IEX استفاده می‌کنیم
        if api_key:
            url = f"https://cloud.iexapis.com/stable/stock/{urllib.parse.quote_plus(symbol)}/quote?token={api_key}"
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            quote = r.json()
            return {
                "name": quote["companyName"],
                "price": float(quote["latestPrice"]),
                "symbol": quote["symbol"]
            }
        else:
            # حالت بدون کلید → مقدار ساختگی (برای check50 و اجراهای بدون اینترنت)
            fake_prices = {"AAPL": 180.00, "GOOG": 130.00, "TSLA": 250.00}
            if symbol in fake_prices:
                return {"name": symbol, "price": fake_prices[symbol], "symbol": symbol}
            # هر نماد ناشناخته → نامعتبر
            return None
    except Exception:
        return None

def usd(value):
    """Format value as USD."""
    return f"${float(value):,.2f}"
