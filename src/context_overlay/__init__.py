"""OpenAI-compatible context overlay proxy."""

from importlib.metadata import PackageNotFoundError, version

from .config import ContextOverlayConfig, load_config
from .skills import Skill, SkillStore
from .transforms import apply_rules

try:
    __version__ = version("context-overlay")
except PackageNotFoundError:  # pragma: no cover - editable tree before install.
    __version__ = "0.0.0"

__all__ = [
    "ContextOverlayConfig",
    "Skill",
    "SkillStore",
    "__version__",
    "apply_rules",
    "load_config",
]
