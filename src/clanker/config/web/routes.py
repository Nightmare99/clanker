"""API routes for Clanker configuration."""

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from clanker.config import CONFIG_PATH, Settings, get_settings, reload_settings
from clanker.config.models import (
    ModelConfig,
    ModelsConfig,
    MODELS_CONFIG_PATH,
    get_models_config,
    save_models_config,
    get_model_by_name,
    get_default_model,
    set_default_model,
    add_model,
    remove_model,
)

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
    env_vars = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
        "ANTHROPIC_FOUNDRY_API_KEY",
        "ANTHROPIC_FOUNDRY_RESOURCE",
    ]
    return {var: bool(os.getenv(var)) for var in env_vars}


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


# ==================== Models API ====================

class ModelsResponse(BaseModel):
    """Models configuration response."""

    models: list[dict[str, Any]]
    default: str | None
    config_path: str


class ModelRequest(BaseModel):
    """Model creation/update request."""

    name: str
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    deployment_name: str | None = None
    api_version: str | None = None


class SetDefaultRequest(BaseModel):
    """Set default model request."""

    name: str


@router.get("/models", response_model=ModelsResponse)
async def get_models() -> ModelsResponse:
    """Get all configured models."""
    config = get_models_config()

    # Mask API keys for display
    models_list = []
    for m in config.models:
        model_dict = m.model_dump()
        if model_dict.get("api_key"):
            model_dict["api_key"] = mask_key(model_dict["api_key"])
        models_list.append(model_dict)

    return ModelsResponse(
        models=models_list,
        default=config.default,
        config_path=str(MODELS_CONFIG_PATH),
    )


@router.post("/models", response_model=MessageResponse)
async def create_model_config(request: ModelRequest) -> MessageResponse:
    """Add or update a model configuration."""
    try:
        model = ModelConfig(
            name=request.name,
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            deployment_name=request.deployment_name,
            api_version=request.api_version,
        )
        add_model(model)
        return MessageResponse(message=f"Model '{request.name}' saved successfully", success=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/models/{name}", response_model=MessageResponse)
async def update_model_config(name: str, request: ModelRequest) -> MessageResponse:
    """Update an existing model configuration."""
    try:
        # Check if model exists
        existing = get_model_by_name(name)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

        # If API key is masked (from UI), preserve the original
        api_key = request.api_key
        if api_key and api_key.startswith("****") or (api_key and "..." in api_key):
            api_key = existing.api_key

        model = ModelConfig(
            name=request.name,
            provider=request.provider,
            api_key=api_key,
            base_url=request.base_url,
            model=request.model,
            deployment_name=request.deployment_name,
            api_version=request.api_version,
        )

        # If name changed, remove old one
        if name.lower() != request.name.lower():
            remove_model(name)

        add_model(model)
        return MessageResponse(message=f"Model '{request.name}' updated successfully", success=True)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/models/{name}", response_model=MessageResponse)
async def delete_model_config(name: str) -> MessageResponse:
    """Delete a model configuration."""
    if remove_model(name):
        return MessageResponse(message=f"Model '{name}' deleted successfully", success=True)
    else:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")


@router.post("/models/default", response_model=MessageResponse)
async def set_default_model_api(request: SetDefaultRequest) -> MessageResponse:
    """Set the default model."""
    if set_default_model(request.name):
        return MessageResponse(message=f"Default model set to '{request.name}'", success=True)
    else:
        raise HTTPException(status_code=404, detail=f"Model '{request.name}' not found")


@router.post("/models/{name}/test", response_model=MessageResponse)
async def test_model_config(name: str) -> MessageResponse:
    """Test a model configuration by making a simple API call."""
    try:
        model_config = get_model_by_name(name)
        if not model_config:
            raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

        # Create a minimal LLM for testing - avoid parameters that some models don't support
        provider = model_config.provider

        if provider == "OpenAI":
            from langchain_openai import ChatOpenAI
            api_key = model_config.api_key or os.getenv("OPENAI_API_KEY")
            kwargs = {"api_key": api_key}
            if model_config.model:
                kwargs["model"] = model_config.model
            if model_config.base_url:
                kwargs["base_url"] = model_config.base_url
            llm = ChatOpenAI(**kwargs)

        elif provider == "AzureOpenAI":
            from langchain_openai import AzureChatOpenAI
            api_key = model_config.api_key or os.getenv("AZURE_OPENAI_API_KEY")
            base_url = model_config.base_url or os.getenv("AZURE_OPENAI_ENDPOINT")
            deployment = model_config.deployment_name or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
            api_version = model_config.api_version or "2024-02-15-preview"
            # Use temperature=1 - some models (o1, o3, gpt-5) only support this value
            llm = AzureChatOpenAI(
                azure_endpoint=base_url,
                azure_deployment=deployment,
                api_version=api_version,
                api_key=api_key,
                temperature=1,
            )

        elif provider == "Anthropic":
            from langchain_anthropic import ChatAnthropic
            api_key = model_config.api_key or os.getenv("ANTHROPIC_API_KEY")
            kwargs = {"api_key": api_key, "max_tokens": 100}
            if model_config.model:
                kwargs["model"] = model_config.model
            if model_config.base_url:
                kwargs["base_url"] = model_config.base_url
            llm = ChatAnthropic(**kwargs)

        elif provider == "Ollama":
            from langchain_community.chat_models import ChatOllama
            base_url = model_config.base_url or "http://localhost:11434"
            model_name = model_config.model or "llama3"
            llm = ChatOllama(base_url=base_url, model=model_name)

        else:
            raise ValueError(f"Unsupported provider: {provider}")

        # Make a simple test invocation
        response = llm.invoke("Say 'ok'")

        return MessageResponse(
            message=f"Connection successful! Model responded.",
            success=True
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {str(e)}")
