# ZeinaGuard Local Setup

ZeinaGuard now runs fully locally without Docker.

## Services

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:5000`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- Sensor: `sensor/main.py`

## Prerequisites

- Python 3
- Node.js + pnpm
- PostgreSQL
- Redis
- Linux shell for the helper scripts

## Environment

Create or update the root `.env` file:

```env
POSTGRES_USER=zeinaguard_user
POSTGRES_PASSWORD=secure_password
POSTGRES_DB=zeinaguard_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

BACKEND_URL=http://localhost:5000
NEXT_PUBLIC_SOCKET_URL=http://localhost:5000
NEXT_PUBLIC_API_URL=http://localhost:5000

JWT_SECRET_KEY=super_secret_key
```

## One-Time Setup

```bash
bash scripts/setup.sh
```

TimescaleDB is optional. Plain PostgreSQL works for local development.

## Database Initialization

Create the database:

```bash
psql -U postgres
CREATE DATABASE zeinaguard_db;
```

Then run the schema migration:

```bash
cd backend
python schema_migration.py
```

## Run Everything

`run.sh` is the only supported lifecycle entry point.

```bash
bash run.sh
```

Stop the full stack with `Ctrl + C`.

Or use Make:

```bash
make setup
make run
```

All older launcher scripts are deprecated and should not be used.

## Notes

- The frontend uses `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_SOCKET_URL` directly, so no reverse proxy is required.
- The backend builds its PostgreSQL and Redis connection settings from the root `.env`.
- `run.sh` requires `pnpm` in the user environment and fails fast if it is missing.
- If PostgreSQL or Redis are not running, restart them with:

```bash
sudo service postgresql start
sudo service redis-server start || sudo service redis start
```
