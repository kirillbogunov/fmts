# Upgrade to FMTS v0.6.2

1. Replace the application files with this release and deploy the latest commit on Render.
2. `DATABASE_URL` may now be pasted from Supabase as-is with a `postgresql://` prefix; FMTS selects psycopg v3 automatically.
3. Keep the real Supabase host, user, password and database from the project's current **Connect** dialog.
4. No SQL migration is required for this hotfix.
