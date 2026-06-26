import os
from pathlib import Path

PROJECT_NAME = "Decentralized Tamper-Resistant Civic Issue Reporting System"
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend" / "src"
UPLOADS_DIR = ROOT_DIR / "uploads"

# Ensure directories exist
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Cooldowns
SUBMISSION_COOLDOWN = 30  # seconds between complaint submissions
VOTE_COOLDOWN = 5          # seconds between votes
