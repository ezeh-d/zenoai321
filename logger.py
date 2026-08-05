"""Simple, readable logging."""
from __future__ import annotations

import logging
import os

from config import settings

os.makedirs(settings.data_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(settings.data_dir, "reyes.log"), encoding="utf-8"),
    ],
)

log = logging.getLogger("reyes")
