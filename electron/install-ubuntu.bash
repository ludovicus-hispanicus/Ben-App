#!/bin/bash

set -e

echo "Checking and installing Docker in Ubuntu (if needed)..."
if ! command -v docker &>/dev/null; then
    echo "Docker is not installed. Installing..."
    sudo apt-get update -y && sudo apt-get upgrade -y
    sudo apt-get install -y curl
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. You may need to log out and back in for Docker permissions to take effect."
else
    echo "Docker is already installed."
fi

echo "Checking and installing Docker Compose plugin (if needed)..."
if ! docker compose version &>/dev/null; then
    echo "Docker Compose plugin is not installed. Installing..."
    sudo apt-get update -y
    # Try the official plugin first, then fall back to the Ubuntu repo version
    if ! sudo apt-get install -y docker-compose-plugin; then
        echo "Official plugin not found. Trying Ubuntu repository version..."
        sudo apt-get install -y docker-compose-v2
    fi
    echo "Docker Compose plugin installed."
else
    echo "Docker Compose plugin is already installed."
fi

echo "Checking for docker-compose.yml and launching containers..."
if [ -f docker-compose.yml ]; then
    echo "Found docker-compose.yml. Cleaning up old containers..."
    docker compose down --remove-orphans
    
    # Force remove containers with fixed names to prevent cross-project conflicts
    echo "Ensuring fixed-name containers are removed..."
    docker rm -f translator app server || true

    echo "Building and launching containers (this may take a while on first run)..."
    docker compose build
    docker compose up
    echo "Containers are up and running."
else
    echo "docker-compose.yml not found in the current directory."
    exit 1
fi

echo "Ubuntu Setup complete."

cleanup() {
    echo "Stopping Docker Compose..."
    docker compose down
    echo "Docker Compose stopped."
}

trap cleanup EXIT
