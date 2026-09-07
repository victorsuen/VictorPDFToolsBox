from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "VictorPDFToolsBox"
HIDDEN_IMPORTS = [
    "fitz",
    "pymupdf",
    "document_workspace",
    "audit_log",
    "stamp_library",
    "flow_layout",
    "runtime_deps",
    "docx",
    "openpyxl",
    "lxml",
    "pytesseract",
    "pptx",
]
MAC_USAGE = """Victor PDF Tools Box（Mac 版）

第一次開啟：
1. 解壓這個 zip
2. 把 VictorPDFToolsBox.app 拖到「應用程式」或任何資料夾
3. 若系統提示無法驗證開發者：在 Finder 對 App 按右鍵 → 打開 → 打開

Office 轉 PDF：請安裝 LibreOffice。若已有 Homebrew，程式可代為安裝。
掃描件 OCR：請安裝 Tesseract。若已有 Homebrew，程式可代為安裝。

Apple 晶片（M 系列）請下載 macos-arm64；較舊的 Intel Mac 請下載 macos-x86_64。
"""


def _hidden_imports() -> list[str]:
    names = list(HIDDEN_IMPORTS)
    if sys.platform == "win32":
        names.extend(["win32com", "win32com.client", "pythoncom"])
    return names


def default_dist() -> Path:
    if sys.platform == "win32":
        return Path(r"C:\tmp\victor_pdf_dist")
    return ROOT / "dist"


def default_work() -> Path:
    if sys.platform == "win32":
        return Path(r"C:\tmp\victor_pdf_build")
    return ROOT / "build"


def mac_arch_label() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return "x86_64"


def run_pyinstaller(dist: Path, work: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        APP_NAME,
    ]
    if sys.platform == "darwin":
        command.extend(
            [
                "--windowed",
                "--osx-bundle-identifier",
                "com.victorsuen.victorpdftoolbox",
            ]
        )
    else:
        command.extend(["--noconsole", "--icon", "NONE"])
    for name in _hidden_imports():
        command.extend(["--hidden-import", name])
    command.extend(["--distpath", str(dist), "--workpath", str(work), str(ROOT / "qt_app.py")])
    subprocess.run(command, check=True, cwd=ROOT)


def windows_app_dir(dist: Path) -> Path:
    return dist / APP_NAME


def mac_app_path(dist: Path) -> Path:
    direct = dist / f"{APP_NAME}.app"
    if direct.exists():
        return direct
    nested = dist / APP_NAME / f"{APP_NAME}.app"
    if nested.exists():
        return nested
    raise FileNotFoundError(f"找不到 {APP_NAME}.app")


def zip_directory(source: Path, dest_zip: Path, arc_root: str) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    if dest_zip.exists():
        dest_zip.unlink()
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, Path(arc_root) / path.relative_to(source))


def make_windows_zip(dist: Path) -> Path:
    folder = windows_app_dir(dist)
    dest = dist / f"{APP_NAME}-windows-x64.zip"
    zip_directory(folder, dest, APP_NAME)
    return dest


def make_mac_zip(dist: Path) -> Path:
    app = mac_app_path(dist)
    dest = dist / f"{APP_NAME}-macos-{mac_arch_label()}.zip"
    if dest.exists():
        dest.unlink()
    note = dist / "使用說明-Mac.txt"
    note.write_text(MAC_USAGE, encoding="utf-8")
    staging = dist / "_mac_zip_stage"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / app.name, symlinks=True)
    shutil.copy2(note, staging / note.name)
    if shutil.which("ditto"):
        subprocess.run(["ditto", "-c", "-k", str(staging), str(dest)], check=True)
    else:
        zip_directory(staging, dest, ".")
    shutil.rmtree(staging, ignore_errors=True)
    return dest


def copy_windows_to_cursor_tools(dist: Path) -> Path:
    desktop = Path.home() / "Desktop"
    tools_dir = desktop / "Cursor Tools" if desktop.exists() else ROOT / "VictorPDFToolsBox-desktop-copy"
    tools_dir.mkdir(parents=True, exist_ok=True)
    dest = tools_dir / APP_NAME
    source = windows_app_dir(dist)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    return dest / f"{APP_NAME}.exe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package Victor PDF Tools Box for this computer.")
    parser.add_argument("--dist", type=Path, default=default_dist())
    parser.add_argument("--work", type=Path, default=default_work())
    parser.add_argument("--zip", action="store_true", help="Also create a download zip.")
    parser.add_argument("--no-desktop-copy", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dist = args.dist.resolve()
    work = args.work.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    run_pyinstaller(dist, work)
    zip_path = None
    if sys.platform == "darwin":
        zip_path = make_mac_zip(dist)
        print(f"Mac app: {mac_app_path(dist)}")
    else:
        exe = windows_app_dir(dist) / f"{APP_NAME}.exe"
        print(f"EXE output: {exe}")
        if args.zip:
            zip_path = make_windows_zip(dist)
        if not args.no_desktop_copy:
            copied = copy_windows_to_cursor_tools(dist)
            print(f"Cursor Tools copy: {copied}")
    if zip_path is not None:
        print(f"Download zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
