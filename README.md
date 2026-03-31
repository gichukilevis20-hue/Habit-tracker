# Habit Tracker

Habit Tracker is a Django app for building routines, logging daily progress, reviewing weekly momentum, and customizing the dashboard experience.

## Local Development

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in the values you need.
4. Run migrations:

```bash
python manage.py migrate
```

5. Start the app:

```bash
python manage.py runserver
```

## Deploying To A New Vercel Project

The repo is already prepared for Vercel:

- `vercel.json` installs dependencies, runs migrations, and collects static files during build.
- `api/index.py` is the serverless entry point.
- `habittracker/settings.py` uses PostgreSQL when `DATABASE_URL` is set and now fails fast on Vercel if required production settings are missing.

### Required Vercel Environment Variables

Add these in the new Vercel project under `Settings` -> `Environment Variables` for the `Production` environment:

```env
DATABASE_URL=postgresql://user:password@host:5432/habittracker
SECRET_KEY=your-long-random-django-secret
APP_BASE_URL=https://your-public-production-domain
```

### Optional Environment Variables

Only add these if you use the matching features:

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL="Habit Tracker <your-email@gmail.com>"

MPESA_CONSUMER_KEY=your-key
MPESA_CONSUMER_SECRET=your-secret
MPESA_SHORTCODE=174379
MPESA_PASSKEY=your-passkey
MPESA_ENVIRONMENT=sandbox
MPESA_CALLBACK_URL=https://your-public-production-domain/mpesa/callback/

BITCOIN_WALLET=your-wallet
APP_NAME="Habit Tracker"
```

### Important Vercel Notes

- Do not rely on SQLite for Vercel. The app is set to reject Vercel or non-local deploys that do not provide `DATABASE_URL`.
- Environment variable changes only apply to new deployments, so redeploy after saving them.
- If your `*.vercel.app` URL returns `401`, check `Settings` -> `Deployment Protection`. Public access may require disabling Vercel Authentication for that site or using the intended public production domain.

### Fresh Deploy Checklist

1. Import this GitHub repo into a new Vercel project.
2. Add the required production environment variables.
3. Check `Deployment Protection` and make sure the public site is reachable the way you want.
4. Deploy.
5. Test `/`, `/login/`, and `/signup/`.

## Useful Files

- `vercel.json`
- `api/index.py`
- `.env.example`
- `habittracker/settings.py`
- `VERCEL_DEPLOYMENT.md`
