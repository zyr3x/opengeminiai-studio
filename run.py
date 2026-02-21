import sys
from pathlib import Path

# Ensure the project root is in PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from app import run

if __name__ == "__main__":
    run()
