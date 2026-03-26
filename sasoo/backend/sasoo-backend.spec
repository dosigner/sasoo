# -*- mode: python ; coding: utf-8 -*-
"""
Sasoo Backend - PyInstaller Spec File
Bundles FastAPI + uvicorn + all dependencies into a standalone executable.

Usage:
    cd backend
    pyinstaller sasoo-backend.spec

Output:
    dist/sasoo-backend/sasoo-backend.exe
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

# Get the backend directory
backend_dir = Path(SPECPATH).resolve()

# Collect agent .md files (bundled with exe)
agents_src = backend_dir / "agents"
agents_data = []
if agents_src.exists():
    for md_file in agents_src.glob("*.md"):
        agents_data.append(
            (str(md_file), "agents")
        )

# ---------------------------------------------------------------------------
# PaperBanana data files (prompts, reference sets, configs)
# These are installed as sibling directories to the paperbanana package
# in site-packages, NOT inside it. PyInstaller only bundles .py files
# via hiddenimports, so data files must be added explicitly.
# ---------------------------------------------------------------------------
paperbanana_data = []
try:
    import paperbanana as _pb
    _pb_site = Path(_pb.__file__).resolve().parent.parent
    for _dir_name in ("prompts", "data", "configs"):
        _src = _pb_site / _dir_name
        if _src.exists():
            for _f in _src.rglob("*"):
                if _f.is_file():
                    # Preserve directory structure relative to site-packages
                    paperbanana_data.append(
                        (str(_f), str(_f.parent.relative_to(_pb_site)))
                    )
    print(f"[SPEC] PaperBanana data files collected: {len(paperbanana_data)}")
except ImportError:
    print("[SPEC] PaperBanana not installed, skipping data files")

# Optional bundled Java runtime for OpenDataLoader
java_runtime_data = []


def _java_executable_name() -> str:
    return "java.exe" if sys.platform == "win32" else "java"


def _java_home_matches_platform(java_home: Path) -> bool:
    candidates = [
        java_home / "bin" / _java_executable_name(),
        java_home / "Contents" / "Home" / "bin" / _java_executable_name(),
    ]
    return any(candidate.exists() for candidate in candidates)


def _find_java_runtime_source() -> tuple[Path | None, str | None]:
    bundled_runtime = backend_dir / "java-runtime"
    if bundled_runtime.exists() and _java_home_matches_platform(bundled_runtime):
        return bundled_runtime, "backend/java-runtime"

    for env_var in ("SASOO_BUNDLED_JAVA_HOME", "JAVA_HOME"):
        value = os.environ.get(env_var)
        if not value:
            continue
        candidate = Path(value).expanduser()
        if candidate.exists() and _java_home_matches_platform(candidate):
            return candidate, env_var

    return None, None


java_runtime_src, java_runtime_source = _find_java_runtime_source()
if java_runtime_src:
    for _f in java_runtime_src.rglob("*"):
        if _f.is_file():
            java_runtime_data.append(
                (str(_f), str(Path("java-runtime") / _f.parent.relative_to(java_runtime_src)))
            )
    print(
        f"[SPEC] Bundled Java runtime files collected: {len(java_runtime_data)} "
        f"from {java_runtime_source}"
    )
elif (backend_dir / "java-runtime").exists():
    print("[SPEC] backend/java-runtime exists but does not match the current platform; skipping bundled runtime")
elif os.environ.get("SASOO_BUNDLED_JAVA_HOME") or os.environ.get("JAVA_HOME"):
    print("[SPEC] Java runtime environment variable exists but does not match the current platform; skipping bundled runtime")

odl_data = collect_data_files("opendataloader_pdf")
print(f"[SPEC] OpenDataLoader package data files collected: {len(odl_data)}")

a = Analysis(
    ['main.py'],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=agents_data + paperbanana_data + java_runtime_data + odl_data,
    hiddenimports=[
        # FastAPI and dependencies
        'fastapi',
        'starlette',
        'starlette.routing',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.staticfiles',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',

        # Async support
        'asyncio',
        'aiosqlite',

        # HTTP clients
        'httpx',
        'httpcore',
        'anyio',
        'sniffio',
        'h11',

        # Pydantic
        'pydantic',
        'pydantic_core',
        'pydantic.deprecated.decorator',

        # PDF and image processing
        'fitz',  # PyMuPDF
        'pymupdf',
        'PIL',
        'PIL.Image',
        'opendataloader_pdf',

        # YAML
        'yaml',

        # Google AI (google-genai package)
        'google.genai',
        'google.genai.types',

        # Anthropic
        'anthropic',

        # Environment
        'dotenv',

        # Multipart form handling
        'python_multipart',
        'multipart',

        # SSL / Network
        'truststore',

        # Encodings
        'encodings',
        'encodings.idna',

        # PaperBanana and submodules
        'paperbanana',
        'paperbanana.cli',
        'paperbanana.agents',
        'paperbanana.agents.base',
        'paperbanana.agents.critic',
        'paperbanana.agents.planner',
        'paperbanana.agents.retriever',
        'paperbanana.agents.stylist',
        'paperbanana.agents.visualizer',
        'paperbanana.core',
        'paperbanana.core.config',
        'paperbanana.core.pipeline',
        'paperbanana.core.types',
        'paperbanana.core.utils',
        'paperbanana.evaluation',
        'paperbanana.evaluation.judge',
        'paperbanana.evaluation.metrics',
        'paperbanana.guidelines',
        'paperbanana.guidelines.methodology',
        'paperbanana.guidelines.plots',
        'paperbanana.providers',
        'paperbanana.providers.base',
        'paperbanana.providers.registry',
        'paperbanana.providers.image_gen',
        'paperbanana.providers.image_gen.google_imagen',
        'paperbanana.providers.vlm',
        'paperbanana.providers.vlm.gemini',
        'paperbanana.reference',
        'paperbanana.reference.store',

        # PaperBanana dependencies
        'structlog',
        'structlog.stdlib',
        'structlog.processors',
        'structlog._config',
        'structlog._base',
        'structlog.contextvars',
        'tenacity',
        'typer',
        'aiofiles',
        'pydantic_settings',
        'pydantic_settings.main',
        'rich',
        'rich.console',
        'rich.progress',
        'rich.panel',
        'matplotlib',
        'matplotlib.pyplot',
        'pandas',
        'click',
        'typing_extensions',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Hybrid OCR stack is intentionally excluded from the slim build.
        'accelerate',
        'cv2',
        'docling',
        'docling_core',
        'docling_ibm_models',
        'docling_parse',
        'easyocr',
        'huggingface_hub',
        'opencv_python',
        'opencv_python_headless',
        'rapidocr',
        'torch',
        'torchvision',
        'transformers',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='sasoo-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='sasoo-backend',
)
