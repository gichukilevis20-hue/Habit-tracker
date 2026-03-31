# Vercel Deployment Guide

This repo is ready to deploy to a new Vercel project, but a successful production deploy still depends on Vercel project settings.

## What Is Already Fixed In The Repo

- `vercel.json` runs:

```bash
pip install -r requirements.txt && python manage.py migrate --noinput && python manage.py collectstatic --noinput
```

- `api/index.py` exposes the Django app as the Vercel serverless entry point.
- `habittracker/settings.py` supports PostgreSQL through `DATABASE_URL`.
- `habittracker/settings.py` now fails fast on Vercel or non-local deployments that do not provide:
  - `DATABASE_URL`
  - a non-default `SECRET_KEY`

## What You Must Configure In Vercel

### Required

```env
DATABASE_URL=postgresql://user:password@host:5432/habittracker
SECRET_KEY=your-long-random-django-secret
APP_BASE_URL=https://your-public-production-domain
```

### Optional

Add email, payment, and wallet settings only if you use those features.

## Recommended Deploy Flow For A New Site

1. Create a new Vercel project from this GitHub repository.
2. Add the required `Production` environment variables before the first public launch.
3. Review `Deployment Protection`.
4. Deploy or redeploy.
5. Verify:
   - home page loads
   - `/login/` loads
   - `/signup/` loads
   - account creation works

## Common Problems

### `401 Unauthorized` on the `*.vercel.app` URL

That means Vercel is blocking the site before Django receives the request. Check `Deployment Protection`.

### `ImproperlyConfigured: DATABASE_URL must be set`

That is the new expected behavior when a Vercel deployment is missing the production database URL. Add the variable, then redeploy.

### `ImproperlyConfigured: SECRET_KEY must be set`

Set a strong production `SECRET_KEY`, then redeploy.

## Local Note

SQLite is still fine for local development. The production guard only applies to Vercel or other non-local deployments.
