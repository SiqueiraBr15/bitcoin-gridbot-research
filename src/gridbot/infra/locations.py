"""Classificação de caminhos: local seguro vs. pasta sincronizada/rede (ADR-004).

Funções puras sobre ``PurePath`` + ambiente injetado, para serem testáveis em qualquer SO.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from pathlib import PurePath

ONEDRIVE_ENV_VARS = ("ONEDRIVE", "ONEDRIVECOMMERCIAL", "ONEDRIVECONSUMER")
DRIVE_REMOTE = 4  # GetDriveTypeW

_ONEDRIVE_PART = re.compile(r"onedrive(?:\s*-\s*.+)?", re.IGNORECASE)
_OTHER_SYNC_PARTS = frozenset(
    {"dropbox", "google drive", "googledrive", "my drive", "icloud drive", "iclouddrive"}
)

type DriveTypeFn = Callable[[str], int | None]


class LocationRisk(IntEnum):
    LOCAL = 0
    OTHER_SYNC = 1  # Dropbox, Google Drive, iCloud: WARNING
    CLOUD_SYNC = 2  # OneDrive, SharePoint: BLOCKED
    NETWORK = 3  # UNC ou unidade de rede mapeada: BLOCKED


@dataclass(frozen=True, slots=True)
class LocationAssessment:
    risk: LocationRisk
    reason: str


def windows_drive_type(root: str) -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes

    return int(ctypes.windll.kernel32.GetDriveTypeW(root))


def assess_location(
    path: PurePath,
    env: Mapping[str, str],
    drive_type: DriveTypeFn | None = windows_drive_type,
) -> LocationAssessment:
    """Classifica ``path`` (já resolvido) quanto a sincronização em nuvem e rede."""
    findings = [_check_unc(path), _check_env_roots(path, env), *_check_parts(path)]
    if drive_type is not None:
        findings.append(_check_drive(path, drive_type))
    worst = max(
        (f for f in findings if f is not None),
        key=lambda f: f.risk,
        default=None,
    )
    return worst or LocationAssessment(LocationRisk.LOCAL, "caminho local")


def _check_unc(path: PurePath) -> LocationAssessment | None:
    drive = path.drive.replace("/", "\\")
    if drive.upper().startswith("\\\\?\\UNC\\"):
        return LocationAssessment(LocationRisk.NETWORK, f"caminho de rede UNC ({drive})")
    if drive.startswith(("\\\\?\\", "\\\\.\\")):
        return None
    if drive.startswith("\\\\"):
        return LocationAssessment(LocationRisk.NETWORK, f"caminho de rede UNC ({drive})")
    return None


def _check_env_roots(path: PurePath, env: Mapping[str, str]) -> LocationAssessment | None:
    upper_env = {key.upper(): value for key, value in env.items()}
    for var in ONEDRIVE_ENV_VARS:
        value = upper_env.get(var)
        if not value:
            continue
        root = type(path)(value)
        if path == root or root in path.parents:
            return LocationAssessment(
                LocationRisk.CLOUD_SYNC, f"dentro da pasta OneDrive (%{var}% = {root})"
            )
    return None


def _check_parts(path: PurePath) -> list[LocationAssessment]:
    found: list[LocationAssessment] = []
    for part in path.parts:
        lower = part.lower()
        if _ONEDRIVE_PART.fullmatch(part) or "sharepoint" in lower:
            found.append(LocationAssessment(LocationRisk.CLOUD_SYNC, f"componente '{part}'"))
        elif lower in _OTHER_SYNC_PARTS:
            found.append(LocationAssessment(LocationRisk.OTHER_SYNC, f"componente '{part}'"))
    return found


def _check_drive(path: PurePath, drive_type: DriveTypeFn) -> LocationAssessment | None:
    drive = path.drive
    if len(drive) == 2 and drive[1] == ":" and drive_type(drive + "\\") == DRIVE_REMOTE:
        return LocationAssessment(LocationRisk.NETWORK, f"unidade de rede mapeada ({drive})")
    return None
