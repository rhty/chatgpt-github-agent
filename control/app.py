"""Construct the controller from operator-only environment settings."""
import os
from pathlib import Path
from github_api import GitHub
from worker_api import Worker
from store import Store
from controller import Controller

def create_controller():
    return Controller(
        GitHub(os.environ['GITHUB_APP_ID'],Path('/run/secrets/github_app_key'),
               [r.strip() for r in os.environ['ALLOWED_REPOS'].split(',') if r.strip()]),
        Worker(os.getenv('WORKER_URL','http://worker:8080')),
        Store(Path(os.getenv('CONTROLLER_STATE','/state/tasks'))))
