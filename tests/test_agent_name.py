import yaml
from clanker.config.settings import Settings, CONFIG_PATH


def test_agent_name_persisted(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    settings = Settings()
    settings.agent.name = "HAL"
    settings.save_yaml(config)

    loaded = Settings.from_yaml(config)
    assert loaded.agent.name == "HAL"
