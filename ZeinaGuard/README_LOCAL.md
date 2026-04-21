# ZeinaGuard Local Runtime

ZeinaGuard now uses a single lifecycle launcher for local Linux development and testing.

## One command

```bash
cd ~/FINAL/ZeinaGuard
bash ./run.sh
```

Stop the full stack with `Ctrl + C`.

## Runtime behavior

`run.sh` performs these steps:

1. Validates required tools such as `node`, `pnpm`, `python3`, `sudo -n`, and the service virtual environments.
2. Verifies backend and frontend ports are free before starting anything.
3. Starts the backend first and waits for:
   `http://localhost:5000/health`
   `http://localhost:5000/ready`
   `http://localhost:5000/socket.io/...`
4. Starts the frontend second and waits for `http://localhost:3000`.
5. Runs a privileged sensor self-test with `sudo -n`.
6. Starts the sensor last, with isolated privileged execution only for that process.

## Logs

Each service writes to its own log file:

- `logs/backend.log`
- `logs/frontend.log`
- `logs/sensor.log`

## Notes

- `run.sh` is the only supported startup entry point.
- The frontend source lives at the repository root. The `frontend/` directory is not a standalone launcher anymore.
- Only the sensor is allowed to use `sudo`, and it must succeed in non-interactive mode.
- Older launch scripts have been removed or deprecated.
