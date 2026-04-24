"""Clanker - An agentic coding CLI powered by LangChain."""

try:
    from clanker._version import __version__
except ImportError:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("clanker")
    except PackageNotFoundError:
        __version__ = "0.0.0-dev"
