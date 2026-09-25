import os
import sqlite3
from flask import Flask, redirect, render_template, request, session, url_for, g
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import apology, login_required, lookup, usd
from datetime import datetime

# Configure application
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = "0"
    response.headers["Pragma"] = "no-cache"
    return response


# Configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Database path
DATABASE = os.path.join(os.path.dirname(__file__), "finance.db")

# Jinja filter
app.jinja_env.filters["usd"] = usd


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.route("/")
@login_required
def index():
    db = get_db()
    user_id = session["user_id"]

    rows = db.execute("""
        SELECT symbol, SUM(shares) AS shares
        FROM transactions
        WHERE user_id = ?
        GROUP BY symbol
        HAVING SUM(shares) > 0
    """, (user_id,)).fetchall()

    portfolio = []
    total_value = 0
    for r in rows:
        quote = lookup(r["symbol"])
        if quote:
            total = r["shares"] * quote["price"]
            total_value += total
            portfolio.append({
                "symbol": r["symbol"],
                "name": quote["name"],
                "shares": r["shares"],
                "price": quote["price"],
                "total": total
            })

    cash = db.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()["cash"]
    grand_total = cash + total_value

    return render_template("index.html", portfolio=portfolio, cash=cash, grand_total=grand_total)


@app.route("/register", methods=["GET", "POST"])
def register():
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username:
            return apology("must provide username", 400)
        if not password:
            return apology("must provide password", 400)
        if password != confirmation:
            return apology("passwords do not match", 400)

        hash_pw = generate_password_hash(password)
        try:
            db.execute("INSERT INTO users (username, hash, cash) VALUES (?, ?, ?)",
                       (username, hash_pw, 10000.0))
            db.commit()
        except sqlite3.IntegrityError:
            return apology("username already exists", 400)

        user_id = db.execute("SELECT id FROM users WHERE username = ?",
                             (username,)).fetchone()["id"]
        session["user_id"] = user_id
        return redirect("/")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            return apology("must provide username and password", 400)

        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row or not check_password_hash(row["hash"], password):
            return apology("invalid username and/or password", 400)

        session["user_id"] = row["id"]
        return redirect("/")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    if request.method == "POST":
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("must provide symbol", 400)
        quote = lookup(symbol)
        if not quote:
            return apology("invalid symbol", 400)
        return render_template("quoted.html", quote=quote)
    return render_template("quote.html")


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    db = get_db()
    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares_input = request.form.get("shares")

        if not symbol:
            return apology("must provide symbol", 400)
        if not shares_input:
            return apology("must provide shares", 400)

        try:
            shares = int(shares_input)
            if shares <= 0:
                raise ValueError
        except ValueError:
            return apology("shares must be positive integer", 400)

        quote = lookup(symbol)
        if not quote:
            return apology("invalid symbol", 400)

        user_id = session["user_id"]
        cash = db.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()["cash"]
        total_cost = shares * quote["price"]

        if cash < total_cost:
            return apology("can't afford", 400)

        db.execute("UPDATE users SET cash = ? WHERE id = ?", (cash - total_cost, user_id))
        db.execute("INSERT INTO transactions (user_id, symbol, shares, price, transacted) VALUES (?, ?, ?, ?, ?)",
                   (user_id, symbol.upper(), shares, quote["price"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()

        return redirect("/")
    return render_template("buy.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    db = get_db()
    user_id = session["user_id"]

    symbols = [r["symbol"] for r in db.execute("""
        SELECT symbol FROM transactions
        WHERE user_id = ?
        GROUP BY symbol
        HAVING SUM(shares) > 0
    """, (user_id,)).fetchall()]

    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares_input = request.form.get("shares")

        if not symbol:
            return apology("must select symbol", 400)
        if not shares_input:
            return apology("must provide shares", 400)
        try:
            shares = int(shares_input)
            if shares <= 0:
                raise ValueError
        except ValueError:
            return apology("shares must be positive integer", 400)

        owned = db.execute("SELECT SUM(shares) AS total FROM transactions WHERE user_id = ? AND symbol = ?",
                           (user_id, symbol)).fetchone()["total"]
        if shares > owned:
            return apology("not enough shares", 400)

        quote = lookup(symbol)
        if not quote:
            return apology("invalid symbol", 400)

        proceeds = shares * quote["price"]
        cash = db.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()["cash"]

        db.execute("UPDATE users SET cash = ? WHERE id = ?", (cash + proceeds, user_id))
        db.execute("INSERT INTO transactions (user_id, symbol, shares, price, transacted) VALUES (?, ?, ?, ?, ?)",
                   (user_id, symbol.upper(), -shares, quote["price"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()

        return redirect("/")
    return render_template("sell.html", symbols=symbols)


@app.route("/history")
@login_required
def history():
    db = get_db()
    user_id = session["user_id"]
    rows = db.execute("SELECT symbol, shares, price, transacted FROM transactions WHERE user_id = ? ORDER BY transacted DESC",
                      (user_id,)).fetchall()
    return render_template("history.html", rows=rows)
