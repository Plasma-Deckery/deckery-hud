#!/usr/bin/env python3
"""
deckery-hud — Steam Deck button layout overlay
Watches /tmp/makima-state.json via inotify, redraws on change.
Toggle: ~/.local/bin/deckery-hud-toggle
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from app import App

App().run(None)
