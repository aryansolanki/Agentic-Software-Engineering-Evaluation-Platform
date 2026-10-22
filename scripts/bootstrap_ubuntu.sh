#!/usr/bin/env bash
set -euo pipefail
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl unzip build-essential
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
echo "Ubuntu project bootstrap complete. Next: cp .env.example .env && edit .env"
