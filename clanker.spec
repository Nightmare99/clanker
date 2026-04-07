# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Clanker."""

import sys
from pathlib import Path

block_cipher = None

# Get the project root
project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / 'src' / 'clanker' / 'cli.py')],
    pathex=[str(project_root / 'src')],
    binaries=[],
    datas=[
        # Include static web UI files
        (str(project_root / 'src' / 'clanker' / 'config' / 'web' / 'static'), 'clanker/config/web/static'),
    ],
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
        # GitHub Copilot SDK
        'copilot',
        'copilot.generated',
        'copilot.generated.session_events',
        # SSL certificates for packaged binary
        'certifi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Readline - causes symbol conflicts with system shell
        'readline',
        'gnureadline',
        # GUI/plotting - not needed
        'tkinter',
        'matplotlib',
        'PIL',
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
