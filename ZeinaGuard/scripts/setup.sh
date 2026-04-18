#!/bin/bash
set -euo pipefail

echo "Installing system dependencies..."
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm redis-server postgresql

echo "Installing pnpm..."
sudo npm install -g pnpm

echo "Starting services..."
sudo service postgresql start
sudo service redis-server start

echo "Setup complete."
echo "TimescaleDB is optional. Install it separately if you need hypertables/compression."
