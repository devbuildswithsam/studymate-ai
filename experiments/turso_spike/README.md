# Turso compatibility spike (SMA-35)

Throwaway code, **not part of the app**. It runs our real models, repositories and Alembic
migrations against a Turso dev database and prints PASS / FAIL / NOTE per check.
Results and the decision: [ADR-0006](../../docs/adr/0006-database-for-deployment.md).

## Run it again (e.g. at the start of v1.1, with a newer driver)
Use a **separate** virtual environment: the spike's driver must not go into the app's venv.

```bat
py -3.12 -m venv %TEMP%\turso-venv
%TEMP%\turso-venv\Scripts\python -m pip install -r backend\requirements.txt libsql==0.1.11
cd backend
%TEMP%\turso-venv\Scripts\python ..\experiments\turso_spike\spike.py
```

It needs `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` in `backend\.env` (names in
`.env.example`), pointing at a **dev database with no real data**: the spike creates and
drops tables, and its migration check deletes rows on purpose. It never prints the URL or
token. At the end it downgrades the database back to empty.
