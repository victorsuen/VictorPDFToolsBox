from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pdf_core
from pdf_core import (
    _docx_available,
    _pptx_available,
    _tesseract_exe_candidates,
    _xlsx_available,
    configure_tesseract,
    find_libreoffice_executable,
    pdf_has_usable_text_layer,
)

TESSDATA_LANGS = ("eng", "chi_sim", "chi_tra")
TESSERACT_WINGET_ID = "UB-Mannheim.TesseractOCR"
LIBREOFFICE_WINGET_ID = "TheDocumentFoundation.LibreOffice"
TESSDATA_FAST_BASE = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"
USER_AGENT = "VictorPDFToolsBox/0.9"
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class RuntimeDependency:
    key: str
    title: str
    prompt: str


def _windows() -> bool:
    return sys.platform == "win32"


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _urlopen(url: str, timeout: int = 60):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    return urllib.request.urlopen(request, timeout=timeout)


def _download_file(url: str, dest: Path, progress=None, label: str = "下載中") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _urlopen(url, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        got = 0
        with dest.open("wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total or got, f"{label}…")


def _run_hidden(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    if _windows():
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    kwargs.setdefault("check", False)
    return subprocess.run(command, **kwargs)


def find_tesseract_executable() -> Path | None:
    found = configure_tesseract()
    if found is not None:
        return found
    for candidate in _tesseract_exe_candidates():
        if candidate.is_file():
            return candidate
    located = shutil.which("tesseract.exe" if _windows() else "tesseract")
    return Path(located) if located else None


def tesseract_tessdata_dir(exe: Path | None = None) -> Path | None:
    if exe is None:
        exe = find_tesseract_executable()
    if exe is None:
        return None
    prefix = os.environ.get("TESSDATA_PREFIX") or ""
    if prefix:
        folder = Path(prefix)
        if (folder / "eng.traineddata").is_file() or (folder / "chi_sim.traineddata").is_file():
            return folder
        nested = folder / "tessdata"
        if nested.is_dir():
            return nested
    sibling = Path(exe).parent / "tessdata"
    return sibling


def missing_traineddata_langs(tessdata: Path | None = None) -> list[str]:
    folder = tessdata if tessdata is not None else tesseract_tessdata_dir()
    if folder is None:
        return list(TESSDATA_LANGS)
    missing: list[str] = []
    for lang in TESSDATA_LANGS:
        if not (folder / f"{lang}.traineddata").is_file():
            missing.append(lang)
    return missing


def missing_ocr_dependencies() -> list[RuntimeDependency]:
    items: list[RuntimeDependency] = []
    if not pdf_core.OCR_AVAILABLE and not _frozen():
        items.append(
            RuntimeDependency(
                "pytesseract",
                "pytesseract",
                "OCR 需要 Python 套件 pytesseract。要現在用 pip 安裝嗎？安裝過程不會上傳你的 PDF。",
            )
        )
    if not pdf_core.PDF_RENDER_AVAILABLE and not _frozen():
        items.append(
            RuntimeDependency(
                "pypdfium2",
                "pypdfium2",
                "OCR 需要 Python 套件 pypdfium2 才能把 PDF 頁面轉成圖片。要現在用 pip 安裝嗎？",
            )
        )
    exe = find_tesseract_executable()
    if exe is None:
        items.append(
            RuntimeDependency(
                "tesseract",
                "Tesseract OCR",
                "掃描件需要本機 Tesseract OCR（含繁中／簡中語言包）才能辨識文字。"
                "安裝約 50–80 MB，會放到本機，不會上傳你的 PDF。",
            )
        )
        return items
    missing = missing_traineddata_langs(tesseract_tessdata_dir(exe))
    if missing:
        labels = "、".join(missing)
        items.append(
            RuntimeDependency(
                "tesseract_langs",
                "Tesseract 中文語言包",
                f"已找到 Tesseract，但缺少語言包：{labels}。\n"
                "沒有這些檔案就無法辨識繁中／簡中。下載只有幾 MB，不會上傳你的 PDF。",
            )
        )
    return items


def microsoft_office_available() -> bool:
    if not _windows():
        return False
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    relatives = (
        Path("Microsoft Office") / "root" / "Office16" / "WINWORD.EXE",
        Path("Microsoft Office") / "Office16" / "WINWORD.EXE",
        Path("Microsoft Office") / "Office15" / "WINWORD.EXE",
        Path("Microsoft Office") / "root" / "Office16" / "EXCEL.EXE",
        Path("Microsoft Office") / "Office16" / "EXCEL.EXE",
    )
    for root in (program_files, program_files_x86):
        for relative in relatives:
            if (root / relative).is_file():
                return True
    return shutil.which("WINWORD.EXE") is not None or shutil.which("EXCEL.EXE") is not None


def missing_office_to_pdf_dependencies() -> list[RuntimeDependency]:
    if find_libreoffice_executable() is not None or microsoft_office_available():
        return []
    if not _windows():
        return []
    return [
        RuntimeDependency(
            "libreoffice",
            "LibreOffice",
            "找不到 Microsoft Office 或 LibreOffice，無法把 Word／Excel／PowerPoint 轉成 PDF。\n"
            "可以安裝免費的 LibreOffice（約數百 MB，可能要幾分鐘，必要時會出現 Windows 權限提示）。"
            "安裝過程不會上傳你的檔案。",
        )
    ]


def missing_pdf_office_python_dependencies(fmt: str) -> list[RuntimeDependency]:
    if _frozen():
        return []
    items: list[RuntimeDependency] = []
    if not pdf_core.PYMUPDF_AVAILABLE:
        items.append(
            RuntimeDependency(
                "pymupdf",
                "PyMuPDF",
                "PDF 轉 Office 建議安裝 Python 套件 PyMuPDF，中文文字層會較完整。要現在用 pip 安裝嗎？",
            )
        )
    if fmt == "word" and not _docx_available():
        items.append(
            RuntimeDependency(
                "python-docx",
                "python-docx",
                "PDF 轉 Word 需要 Python 套件 python-docx。要現在用 pip 安裝嗎？",
            )
        )
    if fmt == "excel" and not _xlsx_available():
        items.append(
            RuntimeDependency(
                "openpyxl",
                "openpyxl",
                "PDF 轉 Excel 需要 Python 套件 openpyxl。要現在用 pip 安裝嗎？",
            )
        )
    if fmt == "powerpoint" and not _pptx_available():
        items.append(
            RuntimeDependency(
                "python-pptx",
                "python-pptx",
                "PDF 轉 PowerPoint 需要 Python 套件 python-pptx。要現在用 pip 安裝嗎？",
            )
        )
    return items


def pdfs_need_ocr(paths: list[Path], password: str = "") -> bool:
    for path in paths:
        if not pdf_has_usable_text_layer(path, password, "1-2"):
            return True
    return False


def _winget_executable() -> str | None:
    return shutil.which("winget")


def _winget_install(package_id: str, progress=None, label: str = "") -> bool:
    winget = _winget_executable()
    if not winget:
        return False
    if progress:
        progress(0, 0, label or f"正在安裝 {package_id}…")
    completed = _run_hidden(
        [
            winget,
            "install",
            "--id",
            package_id,
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
            "--scope",
            "user",
        ],
        capture_output=True,
        timeout=1800,
    )
    return completed.returncode == 0


def _run_installer(executable: Path, args: list[str], elevate: bool = False) -> int:
    if elevate and _windows():
        argument_list = ",".join(f"'{item}'" for item in args)
        command = (
            f"Start-Process -FilePath '{executable}' -ArgumentList {argument_list} "
            f"-Verb RunAs -Wait -WindowStyle Hidden"
        )
        completed = _run_hidden(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            timeout=1800,
        )
        return completed.returncode
    completed = _run_hidden([str(executable), *args], timeout=1800)
    return completed.returncode


def _latest_tesseract_installer_url() -> str:
    with _urlopen("https://api.github.com/repos/UB-Mannheim/tesseract/releases/latest") as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    for asset in payload.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.lower().endswith(".exe") and "w64" in name.lower() and url:
            return url
    raise ValueError("找不到 Tesseract Windows 安裝包。請改到 UB Mannheim 網站手動安裝。")


def _writable_tessdata_dir(folder: Path) -> Path:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".victor_write_test"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return folder
    except OSError:
        pass
    user_dir = Path.home() / "AppData" / "Local" / "Tesseract-OCR" / "tessdata"
    user_dir.mkdir(parents=True, exist_ok=True)
    for lang in TESSDATA_LANGS:
        source = folder / f"{lang}.traineddata"
        dest = user_dir / f"{lang}.traineddata"
        if source.is_file() and not dest.is_file():
            shutil.copy2(source, dest)
    os.environ["TESSDATA_PREFIX"] = str(user_dir)
    return user_dir


def install_tesseract_languages(progress=None) -> None:
    exe = find_tesseract_executable()
    tessdata = tesseract_tessdata_dir(exe)
    if tessdata is None:
        raise ValueError("找不到 Tesseract tessdata 資料夾，無法安裝語言包。")
    tessdata = _writable_tessdata_dir(tessdata)
    missing = missing_traineddata_langs(tessdata)
    if not missing:
        return
    for index, lang in enumerate(missing, start=1):
        dest = tessdata / f"{lang}.traineddata"
        _download_file(
            f"{TESSDATA_FAST_BASE}/{lang}.traineddata",
            dest,
            progress,
            f"正在下載語言包 {lang}（{index}/{len(missing)}）",
        )
        if dest.stat().st_size < 1024:
            dest.unlink(missing_ok=True)
            raise ValueError(f"語言包 {lang} 下載失敗。")


def install_tesseract(progress=None) -> Path:
    if progress:
        progress(0, 0, "正在安裝 Tesseract OCR…")
    if _winget_install(TESSERACT_WINGET_ID, progress, "正在用 Windows 套件管理員安裝 Tesseract…"):
        found = find_tesseract_executable()
        if found is not None:
            install_tesseract_languages(progress)
            return found
    if not _windows():
        raise ValueError("這個系統無法自動安裝 Tesseract，請先自行安裝 tesseract。")
    url = _latest_tesseract_installer_url()
    dest_dir = Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR"
    with tempfile.TemporaryDirectory() as temp_dir:
        installer = Path(temp_dir) / "tesseract-setup.exe"
        _download_file(url, installer, progress, "正在下載 Tesseract OCR")
        if progress:
            progress(0, 0, "正在安裝 Tesseract OCR…")
        args = [
            "/VERYSILENT",
            "/NORESTART",
            "/SUPPRESSMSGBOXES",
            f"/DIR={dest_dir}",
        ]
        code = _run_installer(installer, args, elevate=False)
        if code != 0:
            code = _run_installer(installer, args, elevate=True)
        if code != 0:
            raise ValueError("Tesseract 安裝失敗。若出現權限提示請選允許，或改到 UB Mannheim 網站手動安裝。")
    found = find_tesseract_executable()
    if found is None:
        raise ValueError("Tesseract 安裝完成，但程式仍找不到執行檔。請關閉後重開再試。")
    install_tesseract_languages(progress)
    return found


def _latest_libreoffice_msi_url() -> str:
    listing = _urlopen("https://download.documentfoundation.org/libreoffice/stable/").read().decode(
        "utf-8", errors="replace"
    )
    versions = re.findall(r'href="(\d+\.\d+\.\d+)/"', listing)
    if not versions:
        raise ValueError("找不到 LibreOffice 下載清單。")
    version = sorted(versions, key=lambda item: [int(part) for part in item.split(".")])[-1]
    folder = f"https://download.documentfoundation.org/libreoffice/stable/{version}/win/x86_64/"
    files = _urlopen(folder).read().decode("utf-8", errors="replace")
    names = re.findall(r'href="(LibreOffice_[^"]+_Win_x86-64\.msi)"', files)
    if not names:
        raise ValueError("找不到 LibreOffice Windows 安裝包。")
    return folder + names[0]


def install_libreoffice(progress=None) -> Path:
    if progress:
        progress(0, 0, "正在安裝 LibreOffice…")
    if _winget_install(LIBREOFFICE_WINGET_ID, progress, "正在用 Windows 套件管理員安裝 LibreOffice…"):
        found = find_libreoffice_executable()
        if found is not None:
            return found
    if not _windows():
        raise ValueError("這個系統無法自動安裝 LibreOffice，請先自行安裝。")
    url = _latest_libreoffice_msi_url()
    with tempfile.TemporaryDirectory() as temp_dir:
        installer = Path(temp_dir) / "LibreOffice.msi"
        _download_file(url, installer, progress, "正在下載 LibreOffice")
        if progress:
            progress(0, 0, "正在安裝 LibreOffice，請稍候…")
        msiexec = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "msiexec.exe"
        args = ["/i", str(installer), "/qn", "/norestart", "ALLUSERS=2", "MSIINSTALLPERUSER=1"]
        code = _run_installer(msiexec, args, elevate=False)
        if code != 0:
            code = _run_installer(msiexec, ["/i", str(installer), "/qn", "/norestart"], elevate=True)
        if code != 0:
            raise ValueError("LibreOffice 安裝失敗。若出現權限提示請選允許，或改到官網手動安裝。")
    found = find_libreoffice_executable()
    if found is None:
        raise ValueError("LibreOffice 安裝完成，但程式仍找不到。請關閉後重開再試。")
    return found


def _activate_installed_python_packages(packages: list[str]) -> None:
    import importlib

    importlib.invalidate_caches()
    names = {item.replace("_", "-") for item in packages} | set(packages)
    if "pytesseract" in names:
        module = importlib.import_module("pytesseract")
        pdf_core.pytesseract = module
        pdf_core.OCR_AVAILABLE = True
        pdf_core.TesseractNotFoundError = module.TesseractNotFoundError
    if "pypdfium2" in names:
        module = importlib.import_module("pypdfium2")
        pdf_core.pdfium = module
        pdf_core.PDF_RENDER_AVAILABLE = True
    if "pymupdf" in names:
        module = importlib.import_module("fitz")
        pdf_core.fitz = module
        pdf_core.PYMUPDF_AVAILABLE = True


def install_python_packages(packages: list[str], progress=None) -> None:
    if _frozen():
        raise ValueError("打包版已內建這些套件。若仍缺少，請改用 GitHub 發佈的完整資料夾。")
    if progress:
        progress(0, 0, f"正在安裝 {'、'.join(packages)}…")
    completed = _run_hidden(
        [sys.executable, "-m", "pip", "install", *packages],
        capture_output=True,
        timeout=300,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="replace").strip()
        raise ValueError(detail or "pip 安裝失敗。")
    _activate_installed_python_packages(packages)


def install_runtime_dependency(key: str, progress=None) -> None:
    if key == "tesseract":
        install_tesseract(progress)
        return
    if key == "tesseract_langs":
        install_tesseract_languages(progress)
        return
    if key == "libreoffice":
        install_libreoffice(progress)
        return
    python_keys = {
        "pytesseract": ["pytesseract"],
        "pypdfium2": ["pypdfium2"],
        "pymupdf": ["pymupdf"],
        "python-docx": ["python-docx"],
        "openpyxl": ["openpyxl"],
        "python-pptx": ["python-pptx"],
    }
    packages = python_keys.get(key)
    if packages:
        install_python_packages(packages, progress)
        return
    raise ValueError(f"不知道如何安裝：{key}")
