"""``gridbot doctor``: diagnóstico fail-closed do ambiente local.

Resultado por verificação e geral: READY, WARNING ou BLOCKED. O doctor não corrige nada
silenciosamente; a única ação que ele executa (criar diretórios) exige ``--create-dirs``.
Não acessa rede, não baixa dados e não lê valores de secrets.

Fonte única de verdade: ``DoctorContext.env`` alimenta tanto a configuração quanto as
verificações de localização; o CWD não é usado para nada (ADR-006).
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from pydantic import ValidationError

import gridbot
from gridbot.config.errors import ConfigError
from gridbot.config.modes import ModeNotRunnableError, ensure_mode_runnable
from gridbot.config.paths import (
    ProjectRoot,
    build_runtime_paths,
    installed_package_dir,
    resolve_project_root,
)
from gridbot.config.settings import Settings, describe_validation_error, load_settings
from gridbot.infra.locations import (
    DriveTypeFn,
    LocationRisk,
    assess_location,
    windows_drive_type,
)
from gridbot.storage.sqlite import probe_sqlite

SUPPORTED_PYTHON = (3, 13)

_BROAD_PRINCIPALS = re.compile(
    r"(?i)(\bEveryone\b|\bTodos\b|BUILTIN\\Users|BUILTIN\\Usu\S*|Authenticated Users|"
    r"Usu.rios autenticados|NT AUTHORITY\\Authenticated)"
)


class Status(IntEnum):
    READY = 0
    WARNING = 1
    BLOCKED = 2

    @property
    def exit_code(self) -> int:
        return int(self)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: Status
    detail: str
    hint: str | None = None


def git_tracks_file(path: Path) -> bool | None:
    """``True`` se o Git rastreia ``path``; ``None`` se não foi possível verificar."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - executável resolvido, argumentos fixos
            [git, "ls-files", "--error-unmatch", "--", path.name],
            cwd=path.parent,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def read_windows_acl(path: Path) -> str | None:
    """Saída do ``icacls`` para ``path`` (somente Windows); ``None`` se indisponível."""
    if sys.platform != "win32":
        return None
    icacls = shutil.which("icacls")
    if icacls is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - executável resolvido, argumentos fixos
            [icacls, str(path)],
            capture_output=True,
            timeout=10,
            check=False,
            encoding="oem",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


@dataclass(frozen=True)
class DoctorContext:
    env: Mapping[str, str]
    python_version: tuple[int, int, int]
    pointer_bits: int
    in_venv: bool
    venv_prefix: Path
    package_dir: Path
    create_dirs: bool = False
    platform: str = sys.platform
    drive_type: DriveTypeFn | None = windows_drive_type
    git_tracked: Callable[[Path], bool | None] = field(default=git_tracks_file)
    acl_reader: Callable[[Path], str | None] = field(default=read_windows_acl)

    @classmethod
    def from_runtime(cls, *, create_dirs: bool = False) -> DoctorContext:
        """Contexto da execução real: environment do processo e pacote instalado."""
        info = sys.version_info
        return cls(
            env=dict(os.environ),
            python_version=(info.major, info.minor, info.micro),
            pointer_bits=struct.calcsize("P") * 8,
            in_venv=sys.prefix != sys.base_prefix,
            venv_prefix=Path(sys.prefix).resolve(),
            package_dir=installed_package_dir(),
            create_dirs=create_dirs,
        )


# --------------------------------------------------------------------------- checks


def check_python(version: tuple[int, int, int], pointer_bits: int) -> Check:
    label = ".".join(str(part) for part in version)
    if pointer_bits != 64:
        return Check("python", Status.BLOCKED, f"Python {label} {pointer_bits}-bit; exige x64")
    if version[:2] == SUPPORTED_PYTHON:
        return Check("python", Status.READY, f"Python {label} (64-bit)")
    if version[:2] > SUPPORTED_PYTHON:
        return Check(
            "python",
            Status.WARNING,
            f"Python {label} não homologado; o projeto é homologado em 3.13",
            hint="crie o venv com: py -3.13 -m venv .venv",
        )
    return Check(
        "python",
        Status.BLOCKED,
        f"Python {label} é incompatível; mínimo 3.13",
        hint="instale com: py install 3.13-64",
    )


def check_venv(in_venv: bool, prefix: Path) -> Check:
    if in_venv:
        return Check("venv", Status.READY, f"ambiente virtual ativo ({prefix})")
    return Check(
        "venv",
        Status.WARNING,
        "rodando fora de um ambiente virtual",
        hint="py -3.13 -m venv .venv  e  .venv\\Scripts\\activate",
    )


def check_location(name: str, path: Path, ctx: DoctorContext) -> Check:
    check, _ = _resolved_location(name, path, ctx)
    return check


def _resolved_location(name: str, path: Path, ctx: DoctorContext) -> tuple[Check, Path | None]:
    """Bloqueia risco lexical e verifica o destino antes de qualquer probe/criação.

    Ausentes comuns são permitidos para --create-dirs; links quebrados ou irresolúveis
    não são. Não protege contra troca concorrente do destino depois desta verificação.
    """
    assessment = assess_location(path, ctx.env, ctx.drive_type)
    if assessment.risk < LocationRisk.CLOUD_SYNC:
        try:
            for candidate in (path, *path.parents):
                if candidate.is_symlink() or candidate.is_junction():
                    candidate.resolve(strict=True)
            path = path.resolve()
        except (OSError, RuntimeError) as exc:
            return (
                Check(name, Status.BLOCKED, f"destino de {path} não verificável: {exc}"),
                None,
            )
        assessment = assess_location(path, ctx.env, ctx.drive_type)
    if assessment.risk is LocationRisk.LOCAL:
        return Check(name, Status.READY, f"{path} (local)"), path
    status = Status.WARNING if assessment.risk is LocationRisk.OTHER_SYNC else Status.BLOCKED
    return (
        Check(
            name,
            status,
            f"{path}: {assessment.reason}",
            hint="mova o projeto/dados para um caminho local fora de sincronização (ex.: C:\\dev)",
        ),
        path if status is not Status.BLOCKED else None,
    )


def check_project_root(ctx: DoctorContext) -> tuple[list[Check], ProjectRoot | None]:
    try:
        root = resolve_project_root(ctx.env, ctx.package_dir)
    except (ConfigError, OSError, RuntimeError) as exc:
        hint = "defina GRIDBOT_HOME com o caminho absoluto da raiz do projeto"
        return [Check("project_root", Status.BLOCKED, str(exc), hint=hint)], None
    if not root.path.is_dir():
        detail = f"{root.path} (via {root.source}) não existe ou não é diretório"
        return [Check("project_root", Status.BLOCKED, detail)], None
    checks = [
        Check("project_root", Status.READY, f"{root.path} (via {root.source})"),
        check_location("project_root.location", root.path, ctx),
    ]
    return checks, root


def check_settings(ctx: DoctorContext, root: ProjectRoot) -> tuple[Check, Settings | None]:
    env_file = root.env_file
    try:
        settings = load_settings(ctx.env, env_file)
    except ConfigError as exc:
        return Check("config", Status.BLOCKED, f"configuração inválida: {exc}"), None
    except ValidationError as exc:
        detail = "; ".join(describe_validation_error(exc))
        return Check("config", Status.BLOCKED, f"configuração inválida: {detail}"), None
    source = ".env + ambiente" if env_file.is_file() else "ambiente (sem .env)"
    detail = f"carregada de {source}; modo={settings.mode}"
    if settings.has_exchange_credentials:
        return (
            Check(
                "config",
                Status.WARNING,
                f"{detail}; credenciais Binance definidas mas não usadas nesta fase",
                hint="remova GRIDBOT_BINANCE_API_KEY/SECRET até a Fase C.5",
            ),
            settings,
        )
    return Check("config", Status.READY, f"{detail}; credenciais Binance ausentes"), settings


def check_mode(settings: Settings) -> Check:
    try:
        ensure_mode_runnable(settings.mode)
    except ModeNotRunnableError as exc:
        return Check("mode", Status.BLOCKED, str(exc), hint="use GRIDBOT_MODE=backtest")
    return Check("mode", Status.READY, f"modo '{settings.mode}' permitido nesta fase")


def check_directory(name: str, path: Path, ctx: DoctorContext) -> list[Check]:
    location, resolved = _resolved_location(f"{name}.location", path, ctx)
    checks = [location]
    if resolved is None:
        return checks
    path = resolved
    if path.exists() and not path.is_dir():
        checks.append(Check(name, Status.BLOCKED, f"{path} existe mas não é diretório"))
        return checks
    if not path.exists():
        if not ctx.create_dirs:
            checks.append(
                Check(
                    name,
                    Status.WARNING,
                    f"{path} não existe",
                    hint="crie explicitamente com: gridbot doctor --create-dirs",
                )
            )
            return checks
        try:
            path.mkdir(parents=True)
        except OSError as exc:
            checks.append(Check(name, Status.BLOCKED, f"não foi possível criar {path}: {exc}"))
            return checks
        created = " (criado agora por --create-dirs)"
    else:
        created = ""
    checks.append(_check_writable(name, path, created))
    return checks


def _check_writable(name: str, path: Path, suffix: str) -> Check:
    try:
        with tempfile.TemporaryFile(dir=path) as handle:
            handle.write(b"gridbot-doctor")
    except OSError as exc:
        return Check(name, Status.BLOCKED, f"{path} sem permissão de escrita: {exc}")
    return Check(name, Status.READY, f"{path} gravável{suffix}")


def check_database(db_path: Path) -> Check:
    if not db_path.parent.is_dir():
        return Check(
            "database", Status.WARNING, f"aguardando diretório de dados ({db_path.parent})"
        )
    probe = probe_sqlite(db_path)
    return Check("database", Status.READY if probe.ok else Status.BLOCKED, probe.detail)


def check_env_file(path: Path, ctx: DoctorContext) -> list[Check]:
    if not path.exists():
        return [Check("env_file", Status.READY, ".env ausente (a Fase 0 não usa secrets)")]
    checks = [check_location("env_file.location", path, ctx)]
    if checks[0].status is Status.BLOCKED:
        return checks
    tracked = ctx.git_tracked(path)
    if tracked:
        checks.append(
            Check(
                "env_file.git",
                Status.BLOCKED,
                ".env está rastreado pelo Git",
                hint="git rm --cached .env  e revogue qualquer chave que já tenha sido commitada",
            )
        )
    elif tracked is None:
        checks.append(Check("env_file.git", Status.WARNING, "não foi possível consultar o Git"))
    else:
        checks.append(Check("env_file.git", Status.READY, ".env não rastreado pelo Git"))
    checks.append(_check_env_permissions(path, ctx))
    return checks


def _check_env_permissions(path: Path, ctx: DoctorContext) -> Check:
    if ctx.platform == "win32":
        acl = ctx.acl_reader(path)
        if acl is None:
            return Check("env_file.acl", Status.WARNING, "não foi possível ler a ACL do .env")
        broad = sorted({m.group(1) for m in _BROAD_PRINCIPALS.finditer(acl)})
        if broad:
            return Check(
                "env_file.acl",
                Status.WARNING,
                f".env acessível por grupos amplos: {', '.join(broad)}",
                hint='icacls .env /inheritance:r /grant:r "%USERNAME%:F"',
            )
        return Check("env_file.acl", Status.READY, ".env restrito ao usuário")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return Check(
            "env_file.acl",
            Status.WARNING,
            f".env com permissões {oct(mode)} (outros usuários podem ler)",
            hint="chmod 600 .env",
        )
    return Check("env_file.acl", Status.READY, f".env com permissões {oct(mode)}")


# --------------------------------------------------------------------------- orquestração


def run_doctor(ctx: DoctorContext) -> list[Check]:
    checks = [
        check_python(ctx.python_version, ctx.pointer_bits),
        check_venv(ctx.in_venv, ctx.venv_prefix),
        check_location("package_dir", ctx.package_dir, ctx),
        check_location("venv_dir", ctx.venv_prefix, ctx),
    ]
    root_checks, root = check_project_root(ctx)
    checks.extend(root_checks)
    if root is None:
        return checks
    # .env é verificado antes da validação: um .env rastreado bloqueia mesmo com config inválida.
    env_checks = check_env_file(root.env_file, ctx)
    checks.extend(env_checks)
    if any(c.status is Status.BLOCKED and c.name == "env_file.location" for c in env_checks):
        return checks
    config_check, settings = check_settings(ctx, root)
    checks.append(config_check)
    if settings is None:
        return checks
    paths = build_runtime_paths(root, settings)
    checks.append(check_mode(settings))
    data_checks = check_directory("data_dir", paths.data_dir, ctx)
    checks.extend(data_checks)
    checks.extend(check_directory("log_dir", paths.log_dir, ctx))
    if any(c.status is Status.BLOCKED for c in data_checks):
        # A sonda grava um arquivo temporário: nunca rodar em diretório bloqueado.
        checks.append(Check("database", Status.WARNING, "não verificado (data_dir bloqueado)"))
    else:
        database_location = check_location("database.location", paths.db_path, ctx)
        checks.append(database_location)
        if database_location.status is Status.BLOCKED:
            checks.append(Check("database", Status.WARNING, "não verificado (destino bloqueado)"))
        else:
            checks.append(check_database(paths.db_path))
    return checks


def overall(checks: Sequence[Check]) -> Status:
    return max((c.status for c in checks), default=Status.READY)


def render_report(checks: Sequence[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    lines = [f"gridbot doctor {gridbot.__version__}", ""]
    for check in checks:
        lines.append(f"[{check.status.name:<7}] {check.name:<{width}}  {check.detail}")
        if check.hint and check.status is not Status.READY:
            lines.append(f"{'':>10}{'':<{width}}  -> {check.hint}")
    lines += ["", f"Resultado: {overall(checks).name}"]
    return "\n".join(lines)
