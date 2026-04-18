# ZeinaGuard Local Runtime

ZeinaGuard now has a Docker-free local startup flow for modern Linux machines. The local launcher installs and repairs dependencies, recreates Python virtual environments, enforces Node.js 20, and starts every service with health checks and log files.

## What the local flow does

- Ignores Docker as a runtime dependency.
- Ensures Node.js 20 is installed through `nvm`.
- Updates `npm` and installs `pnpm` globally.
- Fixes ownership issues before frontend package operations.
- Recreates backend and sensor virtual environments from scratch.
- Ensures PostgreSQL exists locally and creates the configured role/database.
- Treats Redis as optional and keeps the backend running with in-memory realtime fallback.
- Starts backend, frontend, and sensor in that order.

## One command

```bash
cd ~/FINAL/ZeinaGuard
bash ./run-all.sh
```

## Files created for local runtime

- `run-all.sh`: full local launcher
- `setup-check.sh`: installs/repairs system dependencies
- `fix-node.sh`: installs and activates Node.js 20 with `nvm`
- `fix-python.sh`: recreates `.venv` and reinstalls Python packages

## Runtime behavior

`run-all.sh` performs these steps:

1. Creates a default `.env` if one does not exist.
2. Installs local system dependencies with `apt-get`.
3. Ensures PostgreSQL is running and provisions the configured role/database.
4. Attempts Redis startup, but only warns if Redis is unavailable.
5. Forces a clean frontend install:
   `sudo chown -R $USER:$USER .`
   `npm cache clean --force`
   `rm -rf node_modules`
   `rm -f package-lock.json`
   `pnpm install`
6. Recreates backend and sensor virtual environments with `fix-python.sh`.
7. Starts services in order:
   backend
   frontend
   sensor
8. Waits for:
   `http://localhost:5000/health`
   `http://localhost:3000`

## Logs

Each service writes to its own log file:

- `logs/backend.log`
- `logs/frontend.log`
- `logs/sensor.log`

## Notes

- The frontend source lives at the repository root. The `frontend/` directory only contains a helper script.
- The sensor is started with `sudo` when available so packet capture can work on Linux.
- If Redis is missing, startup continues and the backend reports an in-memory realtime mode.
