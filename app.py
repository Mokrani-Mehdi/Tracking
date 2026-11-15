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
proxy_count = int(os.environ.get("PROXY_COUNT", "1"))  # Default to 1 for Render
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
  </style>
</head>
<body>
  <p>Redirecting...</p>
  <script>
    const token = "{{ token }}";

    // Send the browser's timezone to the server
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      fetch("/log-tz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token, tz: tz })
      });
    } catch (e) { /* timezone stays NULL */ }

    // Redirect immediately
    fetch("/redirect/{{ redirect_to }}")
      .then(r => r.json())
      .then(data => {
        if (data.redirect_url) {
          window.location.href = data.redirect_url;
        }
      })
      .catch(e => console.error(e));
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

    # Get real IP from Cloudflare header (if available), otherwise from X-Forwarded-For
    ip = request.headers.get("CF-Connecting-IP") or request.remote_addr

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

    return render_template_string(PAGE, token=token, redirect_to="tiktok")


@app.route("/redirect/<path:destination>")
def redirect_page(destination):
    """Redirect to a specified URL after tracking"""
    # Whitelist safe URLs to prevent open redirect attacks
    allowed_urls = {
        "tiktok": "https://www.tiktok.com",
        "instagram": "https://www.instagram.com",
        "youtube": "https://www.youtube.com",
        "twitter": "https://www.twitter.com",
        "facebook": "https://www.facebook.com",
        "github": "https://www.github.com",
    }

    url = allowed_urls.get(destination.lower())
    if not url:
        return jsonify(error="Invalid redirect destination"), 400

    return jsonify(redirect_url=url)


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


@app.route("/debug/headers")
def debug_headers():
    """Debug endpoint to see what headers Render is sending"""
    return jsonify(
        remote_addr=request.remote_addr,
        x_forwarded_for=request.headers.get("X-Forwarded-For"),
        x_forwarded_proto=request.headers.get("X-Forwarded-Proto"),
        x_forwarded_host=request.headers.get("X-Forwarded-Host"),
        x_real_ip=request.headers.get("X-Real-IP"),
        cf_connecting_ip=request.headers.get("CF-Connecting-IP"),
        all_headers={k: v for k, v in request.headers}
    )


@app.route("/dashboard")
def dashboard():
    """Beautiful dashboard to view and filter tracked IPs"""
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IP Tracker Dashboard</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      min-height: 100vh;
      padding: 2rem;
    }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { color: white; margin-bottom: 2rem; text-align: center; }
    .controls {
      background: white;
      padding: 1.5rem;
      border-radius: 8px;
      margin-bottom: 2rem;
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
      box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    input, select {
      padding: 0.75rem 1rem;
      border: 1px solid #ddd;
      border-radius: 6px;
      font-size: 1rem;
    }
    input { flex: 1; min-width: 200px; }
    button {
      padding: 0.75rem 1.5rem;
      background: #667eea;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 600;
      transition: background 0.2s;
    }
    button:hover { background: #764ba2; }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }
    .stat-box {
      background: white;
      padding: 1.5rem;
      border-radius: 8px;
      text-align: center;
      box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .stat-number { font-size: 2rem; font-weight: bold; color: #667eea; }
    .stat-label { color: #666; margin-top: 0.5rem; }
    table {
      width: 100%;
      background: white;
      border-collapse: collapse;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    th {
      background: #f8f9fa;
      padding: 1rem;
      text-align: left;
      font-weight: 600;
      color: #333;
      border-bottom: 2px solid #ddd;
    }
    td {
      padding: 1rem;
      border-bottom: 1px solid #eee;
    }
    tr:hover { background: #f9f9f9; }
    .vpn-yes { color: #dc3545; font-weight: bold; }
    .vpn-no { color: #28a745; font-weight: bold; }
    .ip { font-family: monospace; background: #f5f5f5; padding: 0.25rem 0.5rem; border-radius: 3px; }
    .time { color: #666; font-size: 0.9rem; }
    .no-data {
      text-align: center;
      padding: 2rem;
      color: #999;
    }
    .loading { text-align: center; color: #667eea; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🔍 IP Tracker Dashboard</h1>

    <div class="controls">
      <input type="text" id="search" placeholder="Search by IP, timezone, or user agent...">
      <select id="vpnFilter">
        <option value="">All Records</option>
        <option value="vpn">VPN/Datacenter Only</option>
        <option value="clean">Clean IPs Only</option>
      </select>
      <button onclick="refreshData()">🔄 Refresh</button>
    </div>

    <div class="stats">
      <div class="stat-box">
        <div class="stat-number" id="totalCount">0</div>
        <div class="stat-label">Total Visits</div>
      </div>
      <div class="stat-box">
        <div class="stat-number" id="vpnCount">0</div>
        <div class="stat-label">VPN/Datacenter</div>
      </div>
      <div class="stat-box">
        <div class="stat-number" id="cleanCount">0</div>
        <div class="stat-label">Clean IPs</div>
      </div>
    </div>

    <div id="tableContainer">
      <table>
        <thead>
          <tr>
            <th>IP Address</th>
            <th>Timezone</th>
            <th>VPN/DC</th>
            <th>Timestamp</th>
            <th>User Agent</th>
          </tr>
        </thead>
        <tbody id="tableBody">
          <tr><td colspan="5" class="loading">Loading data...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    let allData = [];

    async function loadData() {
      try {
        const res = await fetch('/api/visits');
        allData = await res.json();
        filterData();
        updateStats();
      } catch (e) {
        document.getElementById('tableBody').innerHTML = '<tr><td colspan="5" class="no-data">Error loading data</td></tr>';
      }
    }

    function filterData() {
      const searchTerm = document.getElementById('search').value.toLowerCase();
      const vpnFilter = document.getElementById('vpnFilter').value;

      let filtered = allData.filter(row => {
        const matchesSearch = !searchTerm ||
          (row.ip && row.ip.includes(searchTerm)) ||
          (row.timezone && row.timezone.toLowerCase().includes(searchTerm)) ||
          (row.user_agent && row.user_agent.toLowerCase().includes(searchTerm));

        const matchesVPN = !vpnFilter ||
          (vpnFilter === 'vpn' && row.vpn_flag === 1) ||
          (vpnFilter === 'clean' && row.vpn_flag === 0);

        return matchesSearch && matchesVPN;
      });

      renderTable(filtered);
    }

    function renderTable(data) {
      const tbody = document.getElementById('tableBody');
      if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="no-data">No records found</td></tr>';
        return;
      }

      tbody.innerHTML = data.map(row => {
        const date = new Date(row.timestamp_utc);
        const time = date.toLocaleString();
        const vpnStatus = row.vpn_flag === 1 ? `<span class="vpn-yes">✓ ${row.vpn_reason}</span>` :
                          row.vpn_flag === 0 ? '<span class="vpn-no">✓ Clean</span>' : 'Unknown';
        const ua = row.user_agent ? row.user_agent.substring(0, 50) + '...' : 'N/A';

        return \`
          <tr>
            <td><span class="ip">\${row.ip}</span></td>
            <td>\${row.timezone || '—'}</td>
            <td>\${vpnStatus}</td>
            <td><span class="time">\${time}</span></td>
            <td><span title="\${row.user_agent}">\${ua}</span></td>
          </tr>
        \`;
      }).join('');
    }

    function updateStats() {
      document.getElementById('totalCount').textContent = allData.length;
      document.getElementById('vpnCount').textContent = allData.filter(r => r.vpn_flag === 1).length;
      document.getElementById('cleanCount').textContent = allData.filter(r => r.vpn_flag === 0).length;
    }

    function refreshData() {
      loadData();
    }

    document.getElementById('search').addEventListener('input', filterData);
    document.getElementById('vpnFilter').addEventListener('change', filterData);

    loadData();
  </script>
</body>
</html>"""
    return html


init_db()
vpn_lists.refresh()  # Load IP lists once at startup (no background refresh)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
