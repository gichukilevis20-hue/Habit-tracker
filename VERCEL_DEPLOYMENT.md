# Vercel Deployment Guide - Habit Tracker

Your Habit Tracker application is experiencing 500 errors on Vercel. This guide explains the issues and how to fix them.

## Issues Found

1. ❌ **Missing vercel.json** - Vercel didn't know how to run your Django app
2. ❌ **No Database Configuration** - SQLite doesn't work on serverless (Vercel)
3. ❌ **Missing Environment Variables** - Vercel needs proper configuration
4. ❌ **Missing dj-database-url** - Required for production databases

## What We Fixed

✅ Created `vercel.json` with proper Django configuration
✅ Created `api/index.py` as Vercel serverless entry point  
✅ Updated `settings.py` to support PostgreSQL via DATABASE_URL
✅ Added `dj-database-url` to requirements.txt
✅ Created `.env.example` template

## Steps to Deploy Successfully

### 1. **Push Changes to GitHub**

```bash
git add -A
git commit -m "Fix Vercel deployment configuration"
git push
```

### 2. **Configure Environment Variables on Vercel**

Go to your Vercel project settings and add these environment variables:

**Required:**
```
DEBUG=False
ALLOWED_HOSTS=habit-tracker-xxxxx.vercel.app,yourdomain.com
SECRET_KEY=<generate-a-new-strong-key>
```

**Database (Choose ONE option):**

**Option A: Use Vercel Postgres (Recommended)**
```
DATABASE_URL=<Vercel will provide this after adding Postgres>
```

**Option B: Use external PostgreSQL (e.g., Railway, Supabase)**
```
DATABASE_URL=postgresql://user:password@host:port/dbname
```

**Option C: Use SQLite (Not recommended - data will be lost)**
- Leave DATABASE_URL empty
- SQLite limitations apply

**Email Configuration:**
```
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL="Habit Tracker <your-email@gmail.com>"
```

**Payment Methods (if needed):**
```
MPESA_CONSUMER_KEY=your-key
MPESA_CONSUMER_SECRET=your-secret
MPESA_SHORTCODE=174379
MPESA_PASSKEY=your-passkey
MPESA_ENVIRONMENT=production (or sandbox)
MPESA_CALLBACK_URL=https://your-domain.com/callback/
```

### 3. **Add Vercel Postgres (Optional but Recommended)**

In your Vercel project dashboard:
1. Go to Storage tab
2. Click "Create Database" → Select "Postgres"
3. Name it "habit-tracker"
4. Vercel will automatically add `DATABASE_URL` to your environment variables

### 4. **Redeploy**

After setting environment variables:
1. Push a new commit (or manually redeploy from Vercel dashboard)
2. Vercel will run the build command: `pip install -r requirements.txt`
3. Your Django app should start successfully

### 5. **Run Migrations on Deployment**

Add a post-deployment script to Vercel (or run manually):

```bash
# You can add this as a custom build step in vercel.json or
# run it from Vercel CLI:

# Pull your production database credentials from Vercel
# Then run:
python manage.py migrate
python manage.py collectstatic --noinput
```

Or SSH into Vercel and run:
```bash
vercel env pull .env.local
python manage.py migrate --noinput
```

## Troubleshooting

### Still getting 500 errors?

1. **Check Vercel Logs:**
   - Go to Vercel Dashboard → Your Project → Deployments
   - Click the failed deployment
   - View the "Runtime Logs" tab

2. **Missing Database:**
   ```
   If you see "no such table" errors:
   - Set DATABASE_URL environment variable
   - Run: python manage.py migrate
   ```

3. **Import Errors:**
   ```
   If requirements aren't installing:
   - Check that dj-database-url is in requirements.txt
   - Force a rebuild: vercel redeploy
   ```

4. **Static Files:**
   ```
   Static files won't work on Vercel serverless
   Use WhiteNoise or Vercel edge middleware for CDN
   ```

### Verify Locally First

Before deploying to Vercel, test locally:

```bash
# Set production environment
export DEBUG=False
export ALLOWED_HOSTS=localhost,127.0.0.1
export DATABASE_URL=postgresql://... (if using)

# Test the application
python manage.py runserver

# Check migrations
python manage.py migrate
```

## Security Notes

⚠️ **Never commit:**
- `.env` file (has SECRET_KEY, email passwords, api keys)
- `db.sqlite3` file
- Debug logs with sensitive data

✅ **Always use:**
- `DEBUG=False` in production
- Strong `SECRET_KEY` (generate new one)
- Environment variables for all secrets
- HTTPS only (Vercel provides free SSL)

## Additional Resources

- [Django Deployment Checklist](https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/)
- [Vercel Django Integration](https://vercel.com/docs/concepts/frameworks/django)
- [dj-database-url Documentation](https://github.com/jazzband/dj-database-url)
- [Vercel Postgres Setup](https://vercel.com/docs/storage/vercel-postgres)
