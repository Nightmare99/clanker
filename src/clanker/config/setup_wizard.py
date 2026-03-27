"""Interactive first-run setup wizard for Clanker."""

import os
import time

import click

from clanker.config.settings import CONFIG_PATH, Settings
from clanker.config.models import ModelConfig, add_model, MODELS_CONFIG_PATH


def _print_banner():
    """Print the setup wizard banner."""
    click.clear()
    click.secho(r"""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     ██████╗██╗      █████╗ ███╗   ██╗██╗  ██╗███████╗    ║
    ║    ██╔════╝██║     ██╔══██╗████╗  ██║██║ ██╔╝██╔════╝    ║
    ║    ██║     ██║     ███████║██╔██╗ ██║█████╔╝ █████╗      ║
    ║    ██║     ██║     ██╔══██║██║╚██╗██║██╔═██╗ ██╔══╝      ║
    ║    ╚██████╗███████╗██║  ██║██║ ╚████║██║  ██╗███████╗    ║
    ║     ╚═════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝    ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """, fg="cyan", bold=True)
    click.secho("    *BZZZT* FIRST-RUN INITIALIZATION SEQUENCE *WHIRR*\n", fg="yellow")


def _animate_text(text: str, delay: float = 0.02):
    """Print text with typewriter effect."""
    for char in text:
        click.echo(char, nl=False)
        time.sleep(delay)
    click.echo()


def _print_step(step: int, total: int, title: str):
    """Print a step header."""
    click.echo()
    click.secho(f"  [{step}/{total}] ", fg="cyan", nl=False, bold=True)
    click.secho(title, fg="white", bold=True)
    click.secho("  " + "─" * 50, fg="bright_black")


def _detect_env_keys() -> dict:
    """Detect which API keys are already set in environment."""
    return {
        "OpenAI": bool(os.getenv("OPENAI_API_KEY")),
        "Anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "AzureOpenAI": bool(os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT")),
    }


def run_setup_wizard() -> Settings:
    """Run the interactive setup wizard.

    Returns:
        Configured Settings instance.
    """
    _print_banner()

    _animate_text("  Initializing configuration subsystems...")
    time.sleep(0.3)

    detected_keys = _detect_env_keys()

    # Show detected environment
    click.echo()
    click.secho("  Environment scan complete:", fg="green")
    for provider, found in detected_keys.items():
        status = click.style("✓ detected", fg="green") if found else click.style("○ not set", fg="bright_black")
        click.echo(f"    {provider:12} API key: {status}")

    click.echo()
    time.sleep(0.5)

    # ─────────────────────────────────────────────────────────────
    # Step 1: Agent Identity
    # ─────────────────────────────────────────────────────────────
    _print_step(1, 4, "AGENT IDENTITY")

    agent_name = click.prompt(
        click.style("  Agent name", fg="white"),
        default="Clanker",
        show_default=True,
    )

    # ─────────────────────────────────────────────────────────────
    # Step 2: LLM Provider
    # ─────────────────────────────────────────────────────────────
    _print_step(2, 4, "LLM PROVIDER SELECTION")

    # Suggest provider based on detected keys
    default_provider = "AzureOpenAI"
    if detected_keys["Anthropic"]:
        default_provider = "Anthropic"
    elif detected_keys["OpenAI"]:
        default_provider = "OpenAI"
    elif detected_keys["AzureOpenAI"]:
        default_provider = "AzureOpenAI"

    click.echo()
    click.echo("  Available providers:")
    providers = [
        ("AzureOpenAI", "Azure OpenAI", "Enterprise-grade, your deployment"),
        ("OpenAI", "OpenAI", "GPT-4o, GPT-4-turbo, etc."),
        ("Anthropic", "Anthropic", "Claude 3.5/4, extended thinking"),
        ("Ollama", "Ollama", "Local models, privacy-first"),
    ]

    for i, (key, name, desc) in enumerate(providers, 1):
        marker = "→" if key == default_provider else " "
        detected = " (key detected)" if detected_keys.get(key) else ""
        click.echo(f"    {marker} [{i}] {name:16} - {desc}{click.style(detected, fg='green')}")

    click.echo()
    provider_choice = click.prompt(
        click.style("  Select provider", fg="white"),
        type=click.Choice(["AzureOpenAI", "OpenAI", "Anthropic", "Ollama"]),
        default=default_provider,
        show_default=True,
    )

    # ─────────────────────────────────────────────────────────────
    # Step 3: Model Configuration
    # ─────────────────────────────────────────────────────────────
    _print_step(3, 4, "MODEL CONFIGURATION")

    # Suggest model based on provider
    default_models = {
        "AzureOpenAI": "gpt-4o",
        "OpenAI": "gpt-4o",
        "Anthropic": "claude-sonnet-4-20250514",
        "Ollama": "llama3.1:8b",
    }

    model_id = click.prompt(
        click.style("  Model ID", fg="white"),
        default=default_models.get(provider_choice, "gpt-4o"),
        show_default=True,
    )

    # Display name for the model
    model_display_name = click.prompt(
        click.style("  Display name", fg="white"),
        default=model_id,
        show_default=True,
    )

    # Azure OpenAI-specific config
    azure_deployment = None
    azure_endpoint = None
    if provider_choice == "AzureOpenAI":
        click.echo()
        click.secho("  Azure OpenAI requires a deployment name and endpoint.", fg="yellow")
        azure_deployment = click.prompt(
            click.style("  Deployment name", fg="white"),
            default=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", model_id),
        )
        azure_endpoint = click.prompt(
            click.style("  Endpoint URL", fg="white"),
            default=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        )

        if not detected_keys["AzureOpenAI"]:
            click.echo()
            click.secho("  ⚠ Set this environment variable:", fg="yellow")
            click.echo("    export AZURE_OPENAI_API_KEY='your-key'")

    # Anthropic thinking option
    thinking_enabled = False
    if provider_choice == "Anthropic":
        click.echo()
        thinking_enabled = click.confirm(
            click.style("  Enable extended thinking?", fg="white"),
            default=False,
        )

    # ─────────────────────────────────────────────────────────────
    # Step 4: Finalize
    # ─────────────────────────────────────────────────────────────
    _print_step(4, 4, "FINALIZING CONFIGURATION")

    # Build model config
    model_config = ModelConfig(
        name=model_display_name,
        provider=provider_choice,
        model=model_id,
        deployment_name=azure_deployment,
        base_url=azure_endpoint,
        thinking_enabled=thinking_enabled,
    )

    # Build settings (for non-model config like agent name)
    settings = Settings()
    settings.agent.name = agent_name

    # Show summary
    click.echo()
    click.secho("  Configuration summary:", fg="cyan")
    click.echo(f"    Agent:     {agent_name}")
    click.echo(f"    Provider:  {provider_choice}")
    click.echo(f"    Model:     {model_display_name} ({model_id})")
    if azure_deployment:
        click.echo(f"    Deployment: {azure_deployment}")
    if azure_endpoint:
        click.echo(f"    Endpoint: {azure_endpoint}")
    if thinking_enabled:
        click.echo(f"    Extended thinking: enabled")

    click.echo()

    # Confirm and save
    if click.confirm(click.style("  Write configuration?", fg="white"), default=True):
        # Save general settings to YAML
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        settings.save_yaml(CONFIG_PATH)

        # Save model config to JSON
        add_model(model_config)

        click.echo()
        click.secho(f"  ✓ Settings saved to {CONFIG_PATH}", fg="green")
        click.secho(f"  ✓ Model config saved to {MODELS_CONFIG_PATH}", fg="green")
    else:
        click.secho("  ✗ Setup cancelled.", fg="red")
        raise SystemExit(1)

    # Final flourish
    click.echo()
    click.secho("  ╔════════════════════════════════════════════╗", fg="cyan")
    click.secho("  ║  *CLANK* INITIALIZATION COMPLETE *WHIRR*   ║", fg="cyan")
    click.secho("  ╚════════════════════════════════════════════╝", fg="cyan")
    click.echo()

    time.sleep(0.5)

    return settings
