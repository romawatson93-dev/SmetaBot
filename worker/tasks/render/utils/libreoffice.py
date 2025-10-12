from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

_LIBREOFFICE_CANDIDATES = ("libreoffice", "soffice")


def _find_libreoffice() -> str:
    for candidate in _LIBREOFFICE_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("LibreOffice не найден в PATH. Установите пакет libreoffice.")


def convert_to_pdf(
    source_path: Path,
    working_dir: Path,
    *,
    filter_name: Optional[str] = None,
    timeout: int = 240,
) -> Path:
    """Convert a document supported by LibreOffice to PDF."""
    binary = _find_libreoffice()
    working_dir.mkdir(parents=True, exist_ok=True)

    profile_dir = working_dir / "lo_profile"
    profile_dir.mkdir(exist_ok=True)

    env = os.environ.copy()
    env.setdefault("HOME", str(profile_dir))
    env.setdefault("TMPDIR", str(working_dir))
    env.setdefault("SAL_USE_VCLPLUGIN", "headless")

    convert_arg = "pdf" if not filter_name else f"pdf:{filter_name}"

    cmd = [
        binary,
        "--headless",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--norestore",
        "--nolockcheck",
        "--convert-to",
        convert_arg,
        str(source_path),
        "--outdir",
        str(working_dir),
    ]

    proc = subprocess.run(
        cmd,
        cwd=working_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "LibreOffice завершился с ошибкой при конвертации в PDF.\n"
            f"Команда: {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}"
        )

    expected = source_path.with_suffix(".pdf")
    if expected.exists():
        return expected

    pdf_candidates = sorted(working_dir.glob("*.pdf"))
    if not pdf_candidates:
        raise RuntimeError("LibreOffice не создал PDF-файл.")

    # выбираем первый созданный PDF, если совпадение по имени не найдено
    return pdf_candidates[0]
