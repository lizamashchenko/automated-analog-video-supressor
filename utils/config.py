import tomllib
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config.toml"

def load():
    with open(_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)
