# autopull.py
import subprocess
import time
import os
from dotenv import load_dotenv

load_dotenv()

REPO_PATH = os.getenv("REPO_PATH")
BRANCH = os.getenv("WATCH_BRANCH", "main")
INTERVAL = int(os.getenv("PULL_INTERVAL", 60 * 5))  # 120 seconds = 2 minutes


def git_pull():
    result = subprocess.run(
        ["git", "pull", "origin", BRANCH],
        cwd=REPO_PATH,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"[autopull] git pull failed:\n{result.stderr}")
    else:
        print(f"[autopull] {result.stdout.strip()}")


if __name__ == "__main__":
    print(f"[autopull] Watching {REPO_PATH} on branch {BRANCH} every {INTERVAL}s...")
    while True:
        git_pull()
        time.sleep(INTERVAL)