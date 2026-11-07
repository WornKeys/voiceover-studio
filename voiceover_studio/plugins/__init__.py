"""Plugins shipped with the app. Enable them with PLUGINS=name,name in the deployment settings."""

from voiceover_studio.plugins.base import Plugin, PluginContext, Stage
from voiceover_studio.plugins.fit_to_length import FitToLength

AVAILABLE: dict[str, type[Plugin]] = {FitToLength.name: FitToLength}


class UnknownPluginError(LookupError):
    pass


def enabled_plugins(setting: str) -> list[type[Plugin]]:
    """Parse the PLUGINS setting ("fit_to_length, other") into plugin classes, in the given order."""
    names = [n.strip() for n in setting.split(",") if n.strip()]
    unknown = [n for n in names if n not in AVAILABLE]
    if unknown:
        raise UnknownPluginError(
            f"Unknown plugin(s): {', '.join(unknown)}. Available: {', '.join(AVAILABLE)}"
        )
    return [AVAILABLE[n] for n in names]


__all__ = [
    "AVAILABLE",
    "FitToLength",
    "Plugin",
    "PluginContext",
    "Stage",
    "UnknownPluginError",
    "enabled_plugins",
]
