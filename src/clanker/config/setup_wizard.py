"""Interactive first-run setup wizard for Clanker."""

import os
import time
from pathlib import Path

import click

from clanker.config.settings import CONFIG_PATH, Settings


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
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "azure": bool(os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT")),
        "azure_anthropic": bool(os.getenv("ANTHROPIC_FOUNDRY_API_KEY")),
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
        click.echo(f"    {provider.upper():12} API key: {status}")

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
    default_provider = "azure"
    if detected_keys["azure_anthropic"]:
        default_provider = "azure_anthropic"
    elif detected_keys["anthropic"]:
        default_provider = "anthropic"
    elif detected_keys["openai"]:
        default_provider = "openai"
    elif detected_keys["azure"]:
        default_provider = "azure"

    click.echo()
    click.echo("  Available providers:")
    providers = [
        ("azure", "Azure OpenAI", "Enterprise-grade, your deployment"),
        ("azure_anthropic", "Azure Anthropic", "Claude on Microsoft Foundry"),
        ("openai", "OpenAI", "GPT-4o, GPT-4-turbo, etc."),
        ("anthropic", "Anthropic", "Claude 3.5/4, extended thinking"),
        ("ollama", "Ollama", "Local models, privacy-first"),
    ]

    for i, (key, name, desc) in enumerate(providers, 1):
        marker = "→" if key == default_provider else " "
        detected = " (key detected)" if detected_keys.get(key) else ""
        click.echo(f"    {marker} [{i}] {name:16} - {desc}{click.style(detected, fg='green')}")

    click.echo()
    provider_choice = click.prompt(
        click.style("  Select provider", fg="white"),
        type=click.Choice(["azure", "azure_anthropic", "openai", "anthropic", "ollama"]),
        default=default_provider,
        show_default=True,
    )

    # ─────────────────────────────────────────────────────────────
    # Step 3: Model Configuration
    # ─────────────────────────────────────────────────────────────
    _print_step(3, 4, "MODEL CONFIGURATION")

    # Suggest model based on provider
    default_models = {
        "azure": "gpt-4o",
        "azure_anthropic": "claude-sonnet-4-5",
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-20250514",
        "ollama": "llama3.1:8b",
    }

    model_name = click.prompt(
        click.style("  Model name", fg="white"),
        default=default_models.get(provider_choice, "gpt-4o"),
        show_default=True,
    )

    # Azure OpenAI-specific config
    azure_deployment = None
    if provider_choice == "azure":
        click.echo()
        click.secho("  Azure OpenAI requires a deployment name.", fg="yellow")
        azure_deployment = click.prompt(
            click.style("  Deployment name", fg="white"),
            default=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", model_name),
        )

        if not detected_keys["azure"]:
            click.echo()
            click.secho("  ⚠ Set these environment variables:", fg="yellow")
            click.echo("    export AZURE_OPENAI_API_KEY='your-key'")
            click.echo("    export AZURE_OPENAI_ENDPOINT='https://your-resource.openai.azure.com'")

    # Azure Foundry Anthropic-specific config
    azure_anthropic_resource = None
    azure_anthropic_deployment = None
    if provider_choice == "azure_anthropic":
        click.echo()
        click.secho("  Azure Foundry Anthropic uses your Azure resource endpoint.", fg="yellow")
        azure_anthropic_resource = click.prompt(
            click.style("  Resource name (e.g., my-ai-resource)", fg="white"),
            default=os.getenv("ANTHROPIC_FOUNDRY_RESOURCE", ""),
        )
        azure_anthropic_deployment = click.prompt(
            click.style("  Deployment name", fg="white"),
            default=model_name,
        )

        if not detected_keys["azure_anthropic"]:
            click.echo()
            click.secho("  ⚠ Set this environment variable:", fg="yellow")
            click.echo("    export ANTHROPIC_FOUNDRY_API_KEY='your-azure-api-key'")

    # Anthropic thinking option (works for both anthropic and azure_anthropic)
    thinking_enabled = False
    if provider_choice in ("anthropic", "azure_anthropic"):
        click.echo()
        thinking_enabled = click.confirm(
            click.style("  Enable extended thinking?", fg="white"),
            default=False,
        )

    # Temperature (optional)
    click.echo()
    temp_input = click.prompt(
        click.style("  Temperature (leave blank for default)", fg="white"),
        default="",
        show_default=False,
    )
    temperature = float(temp_input) if temp_input else None

    # ─────────────────────────────────────────────────────────────
    # Step 4: Finalize
    # ─────────────────────────────────────────────────────────────
    _print_step(4, 4, "FINALIZING CONFIGURATION")

    # Build settings
    settings = Settings()
    settings.agent.name = agent_name
    settings.model.provider = provider_choice
    settings.model.name = model_name

    if temperature is not None:
        settings.model.temperature = temperature

    if azure_deployment:
        settings.model.azure.deployment_name = azure_deployment

    if azure_anthropic_resource:
        settings.model.azure_anthropic.resource = azure_anthropic_resource
    if azure_anthropic_deployment:
        settings.model.azure_anthropic.deployment_name = azure_anthropic_deployment

    if thinking_enabled:
        settings.model.thinking_enabled = True

    # Show summary
    click.echo()
    click.secho("  Configuration summary:", fg="cyan")
    click.echo(f"    Agent:     {agent_name}")
    click.echo(f"    Provider:  {provider_choice}")
    click.echo(f"    Model:     {model_name}")
    if azure_deployment:
        click.echo(f"    Azure deployment: {azure_deployment}")
    if azure_anthropic_resource:
        click.echo(f"    Azure Foundry resource: {azure_anthropic_resource}")
    if azure_anthropic_deployment:
        click.echo(f"    Azure Foundry deployment: {azure_anthropic_deployment}")
    if thinking_enabled:
        click.echo(f"    Extended thinking: enabled")
    if temperature:
        click.echo(f"    Temperature: {temperature}")

    click.echo()

    # Confirm and save
    if click.confirm(click.style("  Write configuration?", fg="white"), default=True):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        settings.save_yaml(CONFIG_PATH)

        click.echo()
        click.secho(f"  ✓ Configuration saved to {CONFIG_PATH}", fg="green")
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
