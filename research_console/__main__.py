"""Manual startup; no permanent service, scheduler, credentials or remote binding."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from research_console.data import Archive
from research_console.server import LocalServer, Service


def main() -> None:
    parser = argparse.ArgumentParser(description="GridBot local research console")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--archive-root", type=Path, help="Authorized local reviews folder; read only"
    )
    parser.add_argument(
        "--lab-dir", type=Path, help="Explicit new/owned local folder for confirmed imports"
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use uma porta de 1024 a 65535")
    archive, failed, reason = None, False, None
    if args.archive_root is not None:
        try:
            archive = Archive(args.archive_root)
        except (ValueError, OSError, KeyError, TypeError, EOFError) as exc:
            failed = True
            reason = (
                "MISSING_SOURCE"
                if isinstance(exc, FileNotFoundError)
                else "INVALID_SCHEMA_OR_SOURCE"
            )
            sys.stderr.write("Arquivo de pesquisa indisponível ou integridade inválida.\n")
    try:
        service = Service(
            archive, archive_error=failed, archive_reason=reason, lab_root=args.lab_dir
        )
        if args.lab_dir is not None:
            service.lab.check_root()
        with LocalServer(service, args.port) as server:
            sys.stdout.write(
                f"GridBot PAPER: http://127.0.0.1:{server.server_port}\nCtrl+C para encerrar.\n"
            )
            sys.stdout.flush()
            server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    except OSError:
        sys.stderr.write("Não foi possível iniciar o console local. Verifique a porta.\n")
        raise SystemExit(1) from None
    except ValueError:
        sys.stderr.write("Pasta de laboratório inválida ou sem autorização explícita.\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
