#!/bin/bash

# Directory of the script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "[SETUP] Checking Docker..."
if ! command -v docker &> /dev/null; then
    echo "Docker not found!"
    echo "Please install Docker Desktop for Mac from: https://www.docker.com/products/docker-desktop/"
    # Attempt to open the download page
    open "https://www.docker.com/products/docker-desktop/"
    exit 1
fi

echo "[SETUP] Using bundled configuration..."

echo "[SETUP] Starting Containers..."
# Run docker compose using the local file (builds from source)
docker compose up
