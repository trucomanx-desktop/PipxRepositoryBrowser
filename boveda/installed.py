#!/usr/bin/python3

import json
from pathlib import Path
from importlib.metadata import distribution



def get_executables(package_name: str) -> list[str]:
    try:
        dist = distribution(package_name)

        return sorted(
            ep.name
            for ep in dist.entry_points
            if ep.group == "console_scripts"
        )

    except Exception:
        return []


def add_installed_package(installed_filepath: str, package_name: str):
    FilePath = Path(installed_filepath)
    
    if FilePath.exists():
        data = json.loads(FilePath.read_text())
    else:
        data = {}

    data[package_name] = {
        "executables": get_executables(package_name)
    }

    FilePath.write_text(json.dumps(data, indent=4))
