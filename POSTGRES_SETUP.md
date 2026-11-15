# PostgreSQL Setup Guide for Render

## Option 1: Automatic Setup (Recommended - Using render.yaml)

If you have the `render.yaml` file in your project, Render will automatically create and configure PostgreSQL for you. **This is the easiest way.**

### What happens automatically:
- PostgreSQL database is created
- Database name: `tracking`
- User: `postgres`
- Connection string is saved as `DATABASE_URL` environment variable
- Your Flask app automatically connects

### Steps:
1. Push your code to GitHub (with `render.yaml` included)
2. Go to render.com → Deploy from GitHub
3. Done! Render handles everything

---

## Option 2: Manual Setup (If render.yaml doesn't work)

If you need to manually set up PostgreSQL on Render:

### Step 1: Create a PostgreSQL Database

1. Go to **render.com** dashboard
2. Click **New +** → **PostgreSQL**
3. Fill in these settings:

| Field | Value |
|-------|-------|
| **Name** | `ip-tracker-db` |
| **Database** | `tracking` |
| **User** | `postgres` |
| **Region** | Pick closest to you |
| **Plan** | Free (512 MB storage) |
| **PostgreSQL Version** | 15 or later |

4. Click **Create Database**
5. **Wait 2-3 minutes** for it to start

### Step 2: Get Your Connection String

Once the database is created:

1. Open the database details page
2. Look for **Internal Database URL** (for connecting from your Flask app)
3. Copy the full connection string, it looks like:
```
postgresql://user:password@host.render.internal:5432/tracking
```

### Step 3: Create Your Web Service

1. Click **New +** → **Web Service**
2. Select your GitHub repository (`ip-tracker`)
3. Fill in settings:

| Setting | Value |
|---------|-------|
| **Name** | `ip-tracker` |
| **Environment** | Python |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app` |
| **Plan** | Free |

### Step 4: Connect the Database to Your Web Service

1. In your Web Service settings, go to **Environment**
2. Click **Add Environment Variable**
3. Create this variable:
   - **Key**: `DATABASE_URL`
   - **Value**: Paste the connection string from Step 2
4. Click **Add**
5. Click **Deploy**

### Step 5: Verify Connection

1. Check the **Logs** tab
2. Look for `INFO:root:Listening on...` (means app started)
3. If you see errors, check the logs for database connection issues

---

## Troubleshooting

### "OperationalError: could not connect to server"
- **Cause**: Database URL is wrong or database isn't ready yet
- **Fix**:
  1. Wait 2-3 minutes after creating the database
  2. Double-check the connection string in Environment Variables
  3. Make sure you used the **Internal Database URL** (not External)

### "relation 'visits' does not exist"
- **Cause**: Tables weren't created yet
- **Fix**:
  1. Visit your app URL once (e.g., `https://ip-tracker.onrender.com`)
  2. This triggers the `init_db()` function which creates the tables
  3. Check again

### "FATAL: role 'postgres' does not exist"
- **Cause**: Wrong username in connection string
- **Fix**: The default user is `postgres`, verify in your connection string

### App keeps restarting
- **Cause**: Usually a Python import or database error
- **Fix**:
  1. Check **Logs** tab for the error message
  2. Common issues:
     - Missing dependency in `requirements.txt`
     - Typo in `DATABASE_URL`
     - Old syntax (still using `sqlite3` instead of SQLAlchemy)

---

## Your Connection String Explained

```
postgresql://user:password@host.render.internal:5432/tracking
```

| Part | Meaning |
|------|---------|
| `postgresql://` | Database type |
| `user:password` | Login credentials (usually `postgres:XXXXX`) |
| `host.render.internal` | Render's internal network (use this, not external URL) |
| `5432` | Default PostgreSQL port |
| `tracking` | Database name |

---

## Free Tier Limits

- **Storage**: 512 MB (enough for thousands of visitor records)
- **Connections**: 10 concurrent
- **Disk Space**: Shared with your Web Service
- **Auto-pause**: Database doesn't auto-pause on free tier (stays running)

---

## Viewing Your Data

### Via Render Dashboard (Recommended)
1. Go to your PostgreSQL database page
2. Click **Connect** → **Render Data** (if available)
3. Browse tables visually

### Via psql (Terminal)
```bash
# Connect from your computer
psql postgresql://user:password@host.render.external:5432/tracking

# List tables
\dt

# View visits
SELECT * FROM visits;
```

### Via Your Flask API
Visit: `https://your-app.onrender.com/api/visits`
(Returns last 100 visitor records as JSON)

---

## Next Steps

1. ✅ Create PostgreSQL database on Render
2. ✅ Get the Internal Database URL
3. ✅ Add it as `DATABASE_URL` environment variable
4. ✅ Deploy your Web Service
5. ✅ Visit your app to trigger table creation
6. ✅ Check `/api/visits` to see tracked data

**Stuck?** Share the error message from the Logs tab and I'll help debug!
