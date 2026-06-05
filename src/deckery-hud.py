#!/usr/bin/env python3
"""
deckery-hud — Steam Deck button layout overlay
Watches /tmp/makima-state.json via inotify, redraws on change.
Toggle: ~/.local/bin/deckery-hud-toggle
"""
from app import App

App().run(None)
