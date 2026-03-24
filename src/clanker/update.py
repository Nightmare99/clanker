"""Update checker for Clanker."""

import urllib.request
import json
from typing import Optional, Tuple

from clanker import __version__

REPO = "Nightmare99/clanker"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(version: str) -> Tuple[int, ...]:
    """Parse version string to tuple for comparison."""
    # Remove 'v' prefix if present
    v = version.lstrip("v")
    # Split and convert to integers
    parts = []
    for part in v.split("."):
        # Handle versions like "1.0.0-beta"
        num = ""
        for char in part:
            if char.isdigit():
                num += char
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def get_latest_version() -> Optional[str]:
    """Fetch the latest release version from GitHub."""
    try:
        req = urllib.request.Request(
            RELEASES_URL,
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "Clanker"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("tag_name")
    except Exception:
        return None


def check_for_update() -> Tuple[bool, Optional[str], str]:
    """
    Check if an update is available.

    Returns:
        Tuple of (update_available, latest_version, current_version)
    """
    current = __version__
    latest = get_latest_version()

    if latest is None:
        return False, None, current

    try:
        current_tuple = parse_version(current)
        latest_tuple = parse_version(latest)
        update_available = latest_tuple > current_tuple
        return update_available, latest, current
    except Exception:
        return False, latest, current


def get_update_message() -> Optional[str]:
    """Get a message if an update is available, otherwise None."""
    update_available, latest, current = check_for_update()

    if update_available and latest:
        return (
            f"Update available: v{current} -> {latest}\n"
            f"Run: curl -fsSL https://raw.githubusercontent.com/{REPO}/main/scripts/install.sh | bash"
        )
    return None
