import os
import secrets
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template_string, request
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import create_engine, text

import vpn_lists

# Get database URL from environment variable (Render provides this)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    # Fallback for local testing
    DATABASE_URL = "sqlite:///visits.db"

app = Flask(__name__)

# Set up database engine
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL)
else:
    # PostgreSQL connection pooling
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,  # Check connection health
    )

# Only enable this if your app is behind a reverse proxy / CDN.
# Set PROXY_COUNT to the number of proxies in front of Flask (e.g. 1).
proxy_count = int(os.environ.get("PROXY_COUNT", "0"))
if proxy_count > 0:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count)

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>My Site</title>
  <style>
    body { display: grid; place-items: center; height: 100vh; margin: 0; font-family: sans-serif; }
    button { font-size: 1.2rem; padding: .8rem 1.6rem; cursor: pointer; }
  </style>
</head>
<body>
  <button id="btn">Click me</button>
  <script>
    document.getElementById("btn").addEventListener("click", () => alert("Hello!"));

    // Send the browser's timezone to the server
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      fetch("/log-tz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: "{{ token }}", tz: tz })
      });
    } catch (e) { /* timezone stays NULL */ }
  </script>
</body>
</html>"""


# ---------- database ----------

def init_db():
    """Create tables if they don't exist"""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS visits (
                id SERIAL PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                timestamp_utc TEXT NOT NULL,
                ip TEXT,
                timezone TEXT,
                user_agent TEXT,
                vpn_flag INTEGER,
                vpn_reason TEXT
            )
        """))
        conn.commit()


# ---------- routes ----------

@app.route("/")
def home():
    token = secrets.token_urlsafe(16)
    ip = request.remote_addr
    result = vpn_lists.lookup(ip)  # local lookup, takes microseconds

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO visits (token, timestamp_utc, ip, user_agent, vpn_flag, vpn_reason)
            VALUES (:token, :timestamp_utc, :ip, :user_agent, :vpn_flag, :vpn_reason)
        """), {
            "token": token,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ip": ip,
            "user_agent": request.headers.get("User-Agent", "")[:300],
            "vpn_flag": result["flag"],
            "vpn_reason": result["reason"],
        })
        conn.commit()

    return render_template_string(PAGE, token=token)


@app.route("/log-tz", methods=["POST"])
def log_tz():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token", ""))
    tz = str(data.get("tz", ""))[:64]  # cap length, never trust client input
    if not token or not tz:
        return jsonify(ok=False), 400

    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE visits SET timezone = :tz WHERE token = :token AND timezone IS NULL"
        ), {"tz": tz, "token": token})
        conn.commit()

    return jsonify(ok=True)


@app.route("/api/visits")
def get_visits():
    """View all tracked IPs (add authentication for production!)"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM visits ORDER BY timestamp_utc DESC LIMIT 100"))
        visits = [dict(row._mapping) for row in result]
    return jsonify(visits)


init_db()
vpn_lists.refresh()  # Load IP lists once at startup (no background refresh)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
