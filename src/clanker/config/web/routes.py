"""API routes for Clanker configuration."""

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from clanker.config import CONFIG_PATH, Settings, get_settings, reload_settings

router = APIRouter(tags=["config"])


class ConfigResponse(BaseModel):
    """Configuration response model."""

    config: dict[str, Any]
    config_path: str
    env_status: dict[str, bool]


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""

    config: dict[str, Any]


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str
    success: bool


def get_env_status() -> dict[str, bool]:
    """Check which environment variables are set."""
    from clanker.auth import is_github_token_valid

    env_vars = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
        "ANTHROPIC_FOUNDRY_API_KEY",
        "ANTHROPIC_FOUNDRY_RESOURCE",
    ]
    status = {var: bool(os.getenv(var)) for var in env_vars}
    # GitHub token can be in env or stored file
    status["GITHUB_TOKEN"] = is_github_token_valid()
    return status


def mask_key(key: str | None) -> str | None:
    """Mask an API key for display."""
    if not key:
        return None
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Get current configuration."""
    settings = reload_settings()

    # Convert to dict, excluding sensitive fields
    config_dict = settings.model_dump(
        exclude={
            "openai_api_key",
            "anthropic_api_key",
            "azure_openai_api_key",
            "azure_openai_endpoint",
            "anthropic_foundry_api_key",
            "anthropic_foundry_resource",
            "github_token",
        }
    )

    # Convert Path objects to strings
    if "memory" in config_dict and "storage_path" in config_dict["memory"]:
        config_dict["memory"]["storage_path"] = str(config_dict["memory"]["storage_path"])
    if "logging" in config_dict and "log_dir" in config_dict["logging"]:
        config_dict["logging"]["log_dir"] = str(config_dict["logging"]["log_dir"])

    return ConfigResponse(
        config=config_dict,
        config_path=str(CONFIG_PATH),
        env_status=get_env_status(),
    )


@router.put("/config", response_model=MessageResponse)
async def update_config(request: ConfigUpdateRequest) -> MessageResponse:
    """Update configuration."""
    try:
        # Load current settings to get Path fields
        current = reload_settings()

        # Get incoming config
        new_config = request.config

        # Preserve Path fields from current settings (these are read-only in UI)
        if "memory" in new_config:
            new_config["memory"]["storage_path"] = current.memory.storage_path
        if "logging" in new_config:
            new_config["logging"]["log_dir"] = current.logging.log_dir

        # Merge current config with new values
        current_dict = current.model_dump(
            exclude={
                "openai_api_key",
                "anthropic_api_key",
                "azure_openai_api_key",
                "azure_openai_endpoint",
                "anthropic_foundry_api_key",
                "anthropic_foundry_resource",
                "github_token",
            }
        )

        # Deep merge the configs
        merged = deep_merge(current_dict, new_config)

        # Validate by creating Settings object
        new_settings = Settings(**merged)

        # Save to file
        new_settings.save_yaml(CONFIG_PATH)

        # Reload to apply
        reload_settings()

        return MessageResponse(message="Configuration saved successfully", success=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/config/validate", response_model=MessageResponse)
async def validate_config(request: ConfigUpdateRequest) -> MessageResponse:
    """Validate configuration without saving."""
    try:
        # Try to create Settings object to validate
        Settings(**request.config)
        return MessageResponse(message="Configuration is valid", success=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/config/reset", response_model=MessageResponse)
async def reset_config() -> MessageResponse:
    """Reset configuration to defaults."""
    try:
        default_settings = Settings()
        default_settings.save_yaml_with_comments(CONFIG_PATH)
        reload_settings()
        return MessageResponse(message="Configuration reset to defaults", success=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/env-status")
async def env_status() -> dict[str, bool]:
    """Get environment variable status."""
    return get_env_status()


@router.post("/mcp/test")
async def test_mcp_server(server_config: dict[str, Any]) -> MessageResponse:
    """Test an MCP server connection."""
    import asyncio
    from contextlib import asynccontextmanager

    transport = server_config.get("transport", "stdio")

    try:
        if transport == "stdio":
            command = server_config.get("command")
            args = server_config.get("args", [])
            env = server_config.get("env", {})

            if not command:
                raise ValueError("Command is required for stdio transport")

            # Try to start the process and check if it responds
            import subprocess
            import shutil

            # Check if command exists
            if not shutil.which(command):
                raise ValueError(f"Command not found: {command}")

            # Try to start the process briefly
            full_env = {**os.environ, **env}
            proc = await asyncio.create_subprocess_exec(
                command, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
            )

            # Give it a moment to start, then terminate
            await asyncio.sleep(0.5)

            if proc.returncode is not None:
                # Process already exited - check stderr
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise ValueError(f"Process exited with code {proc.returncode}: {stderr.decode()[:200]}")
            else:
                # Process is running - good sign
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    proc.kill()

            return MessageResponse(message="Server started successfully", success=True)

        elif transport == "sse":
            url = server_config.get("url")
            if not url:
                raise ValueError("URL is required for SSE transport")

            # Try to connect to the SSE endpoint
            import urllib.request
            import urllib.error

            req = urllib.request.Request(url, method='GET')
            req.add_header('Accept', 'text/event-stream')

            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        return MessageResponse(message="Server is reachable", success=True)
                    else:
                        raise ValueError(f"Server returned status {response.status}")
            except urllib.error.URLError as e:
                raise ValueError(f"Cannot connect to server: {e.reason}")
        else:
            raise ValueError(f"Unknown transport: {transport}")

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/models")
async def get_available_models() -> dict[str, list[str]]:
    """Get available models from all providers."""
    models: dict[str, list[str]] = {
        "github_copilot": [],
        "ollama": [],
        "azure": [],
        "azure_anthropic": [],
    }

    # GitHub Copilot models (from API)
    try:
        from clanker.auth.github_copilot import get_available_copilot_models
        models["github_copilot"] = get_available_copilot_models()
    except Exception:
        pass

    # Ollama models (from local API)
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.ok:
            for m in resp.json().get("models", []):
                name = m.get("name", "").split(":")[0]
                if name:
                    models["ollama"].append(name)
    except Exception:
        pass

    # Azure deployments from config
    try:
        settings = reload_settings()
        if settings.model.azure.deployment_name:
            models["azure"].append(settings.model.azure.deployment_name)
        if settings.model.azure_anthropic.deployment_name:
            models["azure_anthropic"].append(settings.model.azure_anthropic.deployment_name)
    except Exception:
        pass

    return models


@router.post("/shutdown")
async def shutdown() -> MessageResponse:
    """Shutdown the config server."""
    import asyncio
    import signal
    import os

    # Schedule shutdown
    asyncio.get_event_loop().call_later(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return MessageResponse(message="Server shutting down", success=True)


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
