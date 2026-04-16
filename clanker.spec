# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Clanker."""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all copilot submodules dynamically
copilot_imports = collect_submodules('copilot')
copilot_datas = collect_data_files('copilot')

# Get the project root
project_root = Path(SPECPATH)


def collect_copilot_binary():
    """Find and collect the Copilot SDK binary."""
    import site
    binaries = []
    found_paths = set()

    def add_from_dir(copilot_bin):
        if not copilot_bin.exists():
            return False
        added = False
        for f in copilot_bin.iterdir():
            if f.is_file() and f.name not in ('__pycache__', '__init__.py'):
                if str(f) not in found_paths:
                    binaries.append((str(f), 'copilot/bin'))
                    found_paths.add(str(f))
                    added = True
        return added

    # Check venv first (most common for development)
    for venv_name in ['venv', '.venv']:
        venv_path = project_root / venv_name
        if venv_path.exists():
            for pydir in venv_path.glob('lib/python*/site-packages/copilot/bin'):
                if add_from_dir(pydir):
                    break

    # Also check system site-packages
    try:
        for sp in site.getsitepackages():
            if sp:
                add_from_dir(Path(sp) / 'copilot' / 'bin')
    except Exception:
        pass

    # Check user site-packages
    try:
        user_sp = site.getusersitepackages()
        if user_sp:
            add_from_dir(Path(user_sp) / 'copilot' / 'bin')
    except Exception:
        pass

    return binaries

a = Analysis(
    [str(project_root / 'src' / 'clanker' / 'cli.py')],
    pathex=[str(project_root / 'src')],
    binaries=collect_copilot_binary(),
    datas=[
        # Include static web UI files
        (str(project_root / 'src' / 'clanker' / 'config' / 'web' / 'static'), 'clanker/config/web/static'),
    ] + copilot_datas,
    hiddenimports=[
        # LangChain imports
        'langchain',
        'langchain.tools',
        'langchain_core',
        'langchain_openai',
        'langchain_anthropic',
        'langgraph',
        'langgraph.graph',
        'langgraph.prebuilt',
        'langgraph.checkpoint.sqlite',
        # MCP
        'langchain_mcp_adapters',
        # FastAPI/Uvicorn for config server
        'fastapi',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # Other dependencies
        'tiktoken',
        'tiktoken_ext',
        'tiktoken_ext.openai_public',
        'pydantic',
        'pydantic_settings',
        'yaml',
        'dotenv',
        'rich',
        'prompt_toolkit',
        'click',
        # SQLite for checkpointing
        'sqlite3',
        'aiosqlite',
        # SSL certificates for packaged binary
        'certifi',
        # PDF reading support
        'pypdf',
        'pdf2image',
        'PIL',
        'PIL.Image',
        # GitHub Copilot SDK - explicit imports (v0.2.0)
        'copilot',
        'copilot.types',
        'copilot.client',
        'copilot.session',
        'copilot.tools',
        'copilot.bin',
        'copilot._jsonrpc',
        'copilot._telemetry',
        'copilot._sdk_protocol_version',
        'copilot.generated',
        'copilot.generated.rpc',
        'copilot.generated.session_events',
    ] + copilot_imports,
    hookspath=[str(project_root / 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Readline - causes symbol conflicts with system shell
        'readline',
        'gnureadline',
        # GUI/plotting - not needed
        'tkinter',
        'matplotlib',
        # Heavy ML libraries - not needed for markdown-based memories
        'torch',
        'torchvision',
        'torchaudio',
        'transformers',
        'sentence_transformers',
        'faiss',
        'sklearn',
        'scikit-learn',
        'scipy',
        'sympy',
        'triton',
        'onnx',
        'onnxruntime',
        'huggingface_hub',
        # CUDA/GPU - not needed
        'nvidia',
        'cuda',
        'cudnn',
        'cublas',
        # Other heavy deps
        'tensorflow',
        'keras',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
        'numpy.distutils',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='clanker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
