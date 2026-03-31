# Vercel Quick Fix

For a brand-new Vercel site, do these four things before expecting login and signup to work:

1. Create or connect a real PostgreSQL database.
2. Set `DATABASE_URL`, `SECRET_KEY`, and `APP_BASE_URL` in Vercel `Production` environment variables.
3. Check `Deployment Protection` so the public site is not blocked by Vercel Authentication.
4. Redeploy.

## Required Variables

```env
DATABASE_URL=postgresql://user:password@host:5432/habittracker
SECRET_KEY=your-long-random-django-secret
APP_BASE_URL=https://your-public-production-domain
```

## What The Repo Already Handles

- Django startup on Vercel
- Production database parsing via `DATABASE_URL`
- Build-time `migrate --noinput`
- Build-time `collectstatic --noinput`
- Fast failure if production secrets or database settings are missing

## Expected Failure Mode

If `DATABASE_URL` or `SECRET_KEY` is missing on Vercel, the deployment should now fail during startup instead of looking healthy and breaking later at login/signup time.
