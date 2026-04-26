#!/data/data/com.termux/files/usr/bin/bash
# Load environment variables from .env file
if [ -f "$HOME/.env" ]; then
  . "$HOME/.env"
fi

# Navigate to the repository and pull
git pull origin main