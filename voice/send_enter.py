#!/usr/bin/env python3
"""Pulsa Enter en la terminal de Claude (el destino actual) sin darle el foco."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dictate  # noqa: E402

dictate.send_return()
