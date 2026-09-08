"""
SUMO configuration & binary resolution module.
Ported and enhanced from anti-hesitation to dynamically resolve SUMO paths
on Windows/Linux without requiring manual system environment variable setup.
"""
import os
import sys
import shutil
import logging
from typing import Optional

logger = logging.getLogger("sumo_config")


def get_sumo_home() -> str:
    """
    Locates the SUMO home directory.
    Checks environment variable first; if not set, falls back to the
    bundled directory inside the `eclipse-sumo` / `sumo` python package.
    """
    env_home = os.environ.get("SUMO_HOME")
    if env_home and os.path.exists(env_home):
        return env_home

    # Fallback to python package directory
    try:
        import sumo as _sumo_pkg
        pkg_dir = os.path.dirname(_sumo_pkg.__file__)
        if os.path.exists(pkg_dir):
            os.environ["SUMO_HOME"] = pkg_dir
            return pkg_dir
    except ImportError:
        pass

    raise RuntimeError(
        "SUMO_HOME is not set and eclipse-sumo package is not found. "
        "Please install eclipse-sumo via 'pip install eclipse-sumo' or set SUMO_HOME."
    )


def get_sumo_bin_dir() -> str:
    """Returns the bin directory containing sumo, netconvert, etc."""
    home = get_sumo_home()
    bin_dir = os.path.join(home, "bin")
    if os.path.exists(bin_dir):
        return bin_dir
    return home


def get_sumo_tools_dir() -> str:
    """Returns the tools directory containing python helper scripts."""
    home = get_sumo_home()
    tools_dir = os.path.join(home, "tools")
    if os.path.exists(tools_dir):
        return tools_dir
    return home


def get_binary(binary_name: str) -> str:
    """
    Resolves full executable path for a SUMO tool (e.g. 'sumo', 'netconvert', 'sumo-gui').
    Appends .exe automatically on Windows if omitted.
    """
    if sys.platform.startswith("win") and not binary_name.endswith(".exe"):
        exe_name = f"{binary_name}.exe"
    else:
        exe_name = binary_name

    bin_dir = get_sumo_bin_dir()
    direct_path = os.path.join(bin_dir, exe_name)
    if os.path.exists(direct_path):
        return direct_path

    which_path = shutil.which(binary_name) or shutil.which(exe_name)
    if which_path and os.path.exists(which_path):
        return which_path

    raise FileNotFoundError(f"SUMO binary '{binary_name}' not found in {bin_dir} or PATH.")
