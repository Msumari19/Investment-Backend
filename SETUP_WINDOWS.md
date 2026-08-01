# 🚀 Setup for Windows — Step by Step

## Step 1: Download All Files

You have 9 files ready to download:
- app.py
- auth.py
- config.py
- extensions.py
- logic.py
- models.py
- plans.py
- requirements.txt
- transactions.py

**Download all of them to a single folder.** For example:
```
C:\Users\HomePC\Downloads\investment-backend\
```

---

## Step 2: Verify All Files Are There

Open PowerShell and navigate to your folder:

```powershell
cd C:\Users\HomePC\Downloads\investment-backend
ls
```

You should see exactly 9 files:
```
Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a---           8/1/2026  12:34 PM          1.4K app.py
-a---           8/1/2026  12:34 PM          1.8K auth.py
-a---           8/1/2026  12:34 PM          572B config.py
-a---           8/1/2026  12:34 PM          120B extensions.py
-a---           8/1/2026  12:34 PM           26K logic.py
-a---           8/1/2026  12:34 PM          4.1K models.py
-a---           8/1/2026  12:34 PM          4.0K plans.py
-a---           8/1/2026  12:34 PM           97B requirements.txt
-a---           8/1/2026  12:34 PM          4.9K transactions.py
```

✅ When you see all 9 files, move to Step 3.

---

## Step 3: Install Dependencies

Still in PowerShell, in your folder:

```powershell
pip install --break-system-packages -r requirements.txt
```

⏳ This will install:
- Flask 3.0.0
- SQLAlchemy 3.1.1
- JWT support
- CORS support

**Wait for it to complete.** You should see:
```
Successfully installed ...
```

---

## Step 4: Start the Server

```powershell
python app.py
```

**Expected output:**
```
Backend running:
  Health:  GET  http://localhost:5000/api/health
  Auth:    POST http://localhost:5000/api/auth/register  {email, password}
           POST http://localhost:5000/api/auth/login     {email, password}
  Tx:      GET/POST http://localhost:5000/api/transactions
  Plan:    POST http://localhost:5000/api/plans/generate
```

If you see this, **your backend is running!** 🎉

---

## Step 5: Test It (in another PowerShell window)

Open a **new PowerShell** window and test:

```powershell
# Test health
curl http://localhost:5000/api/health

# Should return:
# {"status":"ok"}
```

Try registering a user:

```powershell
curl -X POST http://localhost:5000/api/auth/register `
  -H "Content-Type: application/json" `
  -d '{\"email\":\"test@example.com\",\"password\":\"testpass123\"}'
```

Should return something like:
```json
{
  "token": "eyJ0eXAi...",
  "user": {
    "id": 1,
    "email": "test@example.com",
    "created_at": "2026-08-01T12:34:56"
  }
}
```

✅ **STAGE 1 COMPLETE** when you see this!

---

## Next: Stage 2 (Cloud Deployment)

Once Stage 1 works locally, I'll give you Stage 2 commands.

**Report back with the token and user info from the registration test!**
