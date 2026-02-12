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

from pathlib import Path

# Get the backend directory
backend_dir = Path(SPECPATH).resolve()

# Collect agent profile YAML files (bundled with exe)
agent_profiles_src = backend_dir / "library" / "agent_profiles"
agent_profiles_data = []
if agent_profiles_src.exists():
    for yaml_file in agent_profiles_src.glob("*.yaml"):
        agent_profiles_data.append(
            (str(yaml_file), "agent_profiles")
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

a = Analysis(
    ['main.py'],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=agent_profiles_data + paperbanana_data,
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
        'tenacity',
        'typer',
        'aiofiles',
        'pydantic_settings',
        'rich',
        'rich.console',
        'rich.progress',
        'rich.panel',
        'matplotlib',
        'matplotlib.pyplot',
        'pandas',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
