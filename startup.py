#!/usr/bin/env python3
import subprocess
import sys
import os

print("Installing Playwright system dependencies...")
try:
    subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
    print("Playwright dependencies installed successfully")
except subprocess.CalledProcessError as e:
    print(f"Failed to install Playwright dependencies: {e}")
    # Continue anyway as some dependencies might fail but it could still work

print("Checking Playwright installation...")
try:
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    print("Playwright browsers installed successfully")
except subprocess.CalledProcessError as e:
    print(f"Failed to install Playwright browsers: {e}")
    sys.exit(1)

import uvicorn
from main import app

port = int(os.environ.get("PORT", 10000))
uvicorn.run(app, host="0.0.0.0", port=port)
