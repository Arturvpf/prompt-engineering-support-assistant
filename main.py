"""Ponto de entrada: python main.py [interactive | list | generate ...]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from support_assistant.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
