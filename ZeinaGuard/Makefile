setup:
	bash scripts/setup.sh

run:
	bash run-all.sh

backend:
	bash backend/run.sh

frontend:
	bash frontend/run.sh

sensor:
	set -a && . ./.env && set +a && cd sensor && sudo -E env BACKEND_URL="$$BACKEND_URL" python3 main.py
