#!/usr/bin/env python3
"""Compatibility entry point for existing php-test-lock-hook installations."""

from runpy import run_path
from pathlib import Path

run_path(str(Path(__file__).with_name("laravel-test-lock-check.py")), run_name="__main__")
