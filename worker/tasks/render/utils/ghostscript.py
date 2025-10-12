from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

_GHOSTSCRIPT_CANDIDATES = ("gs", "gswin64c", "gswin32c")


def _find_ghostscript() -> str:
    for candidate in _GHOSTSCRIPT_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("Ghostscript не найден в PATH. Установите пакет ghostscript.")


def pdf_to_png(
    pdf_path: Path,
    output_dir: Path,
    *,
    base_name: str,
    dpi: int = 300,
    color: bool = True,
    first_page: Optional[int] = None,
    last_page: Optional[int] = None,
    timeout: int = 240,
) -> List[Path]:
    """Render a PDF to PNG pages via Ghostscript."""
    gs_binary = _find_ghostscript()
    output_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = output_dir / f"{base_name}-%03d.png"

    cmd = [
        gs_binary,
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-dQUIET",
    ]
    if first_page is not None:
        cmd.append(f"-dFirstPage={first_page}")
    if last_page is not None:
        cmd.append(f"-dLastPage={last_page}")

    cmd.extend(
        [
            f"-sDEVICE={'png16m' if color else 'pnggray'}",
            f"-r{dpi}",
            f"-sOutputFile={output_pattern}",
            str(pdf_path),
        ]
    )

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=output_dir,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Ghostscript завершился с ошибкой при рендеринге PDF.\n"
            f"Команда: {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}"
        )

    png_files = sorted(output_dir.glob(f"{base_name}-*.png"))
    if not png_files:
        raise RuntimeError("Ghostscript не создал PNG-файлы.")
    return png_files
