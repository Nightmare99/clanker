"""PyInstaller hook for github-copilot-sdk package."""

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# Collect everything from the copilot package
datas, binaries, hiddenimports = collect_all('copilot')

# Ensure all submodules are included
hiddenimports += collect_submodules('copilot')

# Also explicitly add known modules in case collect_all misses them (v0.2.0)
hiddenimports += [
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
]
