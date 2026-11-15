# Deploy to Render with PostgreSQL

## Step 1: Prepare Your Project

### 1.1 Update `requirements.txt`
Replace the contents with:
```
flask
requests
gunicorn
psycopg2-binary
sqlalchemy
```

### 1.2 Create `render.yaml` config file
In your project root (`c:\Users\mehdi\repo\Tracking\`), create a new file called `render.yaml`:

```yaml
services:
  - type: web
    name: ip-tracker
    env: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: ip-tracker-db
          property: connectionString
      - key: PROXY_COUNT
        value: "1"

databases:
  - name: ip-tracker-db
    plan: free
    databaseName: tracking
    user: postgres
    postgresDatabaseVersion: "15"
```

### 1.3 Update your `app.py`
Replace your current database code with this PostgreSQL version:

```python
import os
import secrets
from datetime import datetime, timezone
from flask import Flask, g, jsonify, render_template_string, request
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

@app.route("/")
def home():
    token = secrets.token_urlsafe(16)
    ip = request.remote_addr
    result = vpn_lists.lookup(ip)

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
    tz = str(data.get("tz", ""))[:64]
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

# Initialize database
init_db()
vpn_lists.refresh()  # Load IP lists once at startup (no background refresh)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
```

---

## Step 2: Push to GitHub

### 2.1 Initialize Git (if not already done)
```powershell
cd c:\Users\mehdi\repo\Tracking
git init
git add .
git commit -m "Initial commit: IP tracker with PostgreSQL"
```

### 2.2 Create a GitHub repo
1. Go to **github.com** → Sign in
2. Click **New** → Create new repository
3. Name it `ip-tracker` (or anything)
4. **Don't** initialize with README
5. Copy the commands they show you

### 2.3 Push your code
```powershell
git remote add origin https://github.com/YOUR_USERNAME/ip-tracker.git
git branch -M main
git push -u origin main
```

---

## Step 3: Deploy on Render

### 3.1 Sign up for Render
1. Go to **render.com**
2. Click **Sign Up** (use GitHub for easiest auth)
3. Connect your GitHub account

### 3.2 Create a new Web Service
1. Click **New +** → **Web Service**
2. Select your `ip-tracker` repository
3. Fill in these settings:
   - **Name:** `ip-tracker`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Plan:** `Free`

### 3.3 Render will auto-create PostgreSQL
If you used `render.yaml`:
- ✅ PostgreSQL database is created automatically
- ✅ Connection string set in `DATABASE_URL` environment variable
- ✅ Your app connects automatically

**If render.yaml didn't work**, create the database manually:
1. In Render dashboard → **PostgreSQL**
2. Click **New +** → **PostgreSQL**
3. Fill in:
   - **Name:** `ip-tracker-db`
   - **Database Name:** `tracking`
   - **Region:** Pick closest to you
   - **Plan:** `Free`
4. Copy the **Internal Database URL**
5. Go back to your Web Service → **Environment**
6. Add new environment variable:
   - **Key:** `DATABASE_URL`
   - **Value:** Paste the connection URL

### 3.4 Deploy
1. Render will deploy automatically once you push to GitHub
2. Check the **Logs** tab to see if it works
3. Your app URL will be: `https://ip-tracker.onrender.com`

---

## Step 4: Test It

1. Visit `https://ip-tracker.onrender.com`
2. Click the button
3. Check the data:
   - Visit `https://ip-tracker.onrender.com/api/visits`
   - You should see your IP logged!

---

## Common Issues

### "ModuleNotFoundError: No module named 'flask'"
- Make sure `requirements.txt` is updated
- Push changes: `git add . && git commit -m "update" && git push`
- Render will redeploy automatically

### "OperationalError: could not connect to server"
- Wait 2-3 minutes for PostgreSQL to start
- Check `DATABASE_URL` is set in Environment Variables
- Check the database name matches in `render.yaml`

### "No such table: visits"
- Tables are created on first request to `/`
- Visit the homepage to trigger `init_db()`

### App crashes on deploy
- Check **Logs** tab in Render dashboard
- Most common: `requirements.txt` missing a dependency
- Push a fix and Render redeploys automatically

---

## Local Testing Before Deploy

Test locally with PostgreSQL (optional, but safer):

```powershell
# Install PostgreSQL locally (or use Docker)
# Create a database called "tracking"
# Set environment variable:
$env:DATABASE_URL = "postgresql://postgres:password@localhost:5432/tracking"

# Run locally
python app.py
```

Visit `http://localhost:5000` and verify it works.

---

## Summary

1. ✅ Update `requirements.txt` (add psycopg2-binary, sqlalchemy)
2. ✅ Update `app.py` (use SQLAlchemy + PostgreSQL)
3. ✅ Create `render.yaml` (tells Render how to deploy)
4. ✅ Push to GitHub
5. ✅ Deploy on Render (one click, auto-connects PostgreSQL)
6. ✅ Done! Your app is live with a real database

**Total time: ~15 minutes**
