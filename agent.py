#!/usr/bin/env python3
"""Thin wrapper — delegates to td_agent.cli so `python agent.py` still works."""
from td_agent.cli import app

if __name__ == "__main__":
    app()
