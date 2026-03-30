# Quick Fix for Vercel 500 Errors

## TL;DR - What to do NOW:

1. **In Vercel Dashboard Settings**, add these environment variables:

```
DEBUG=False
ALLOWED_HOSTS=habit-tracker-[your-id].vercel.app,yourdomain.com
SECRET_KEY=<run: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-specific-password
DATABASE_URL=postgresql://... (if using external DB or Vercel Postgres)
```

2. **In Vercel Dashboard Storage**, click "Create Database" → Select "Postgres"
   - This auto-sets DATABASE_URL

3. **Redeploy** on Vercel (Settings → Deployments → Latest → Redeploy)

## Why you got 500 errors:

- No DATABASE_URL → SQLite can't work on serverless
- DEBUG not set to False → Different error handling
- ALLOWED_HOSTS not set → Doesn't match vercel domain

## Files we added:

- ✅ `vercel.json` - Vercel configuration
- ✅ `api/index.py` - Serverless function entry point
- ✅ `VERCEL_DEPLOYMENT.md` - Full deployment guide
- ✅ `.env.example` - Template for env vars
- ✅ Updated `requirements.txt` - Added dj-database-url
- ✅ Updated `settings.py` - Added DATABASE_URL support

That's it! Try redeploying now.
