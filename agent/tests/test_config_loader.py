"""agent/tests/test_config_loader.py — load_config() sender/llm parsing."""

from __future__ import annotations

import pytest

from agent.config.loader import load_config
from agent.config.models import ConfigError

_BASE_YAML = """
campaign:
  keywords: ["solar energy"]
  location: "UK"
  target_titles: ["VP of Sales"]
limits:
  max_companies: 5
  max_leads: 5
providers:
  discovery: google_cse
  contacts: proxycurl
  email_finder: hunter
  verifier: neverbounce
  copywriter: {copywriter}
output:
  xlsx_path: "matrix.xlsx"
sender:
  company_name: "TestCo"
"""


def _write_config(tmp_path, copywriter: str = "template") -> None:
    (tmp_path / "matrix.xlsx").write_text("")  # xlsx existence isn't validated for template
    (tmp_path / "config.yaml").write_text(_BASE_YAML.format(copywriter=copywriter))


def test_sender_block_with_only_company_name_loads(tmp_path):
    _write_config(tmp_path)
    config = load_config(tmp_path / "config.yaml")
    assert config.sender.company_name == "TestCo"
    assert config.sender.narrative == ""


def test_llm_block_absent_uses_defaults(tmp_path):
    _write_config(tmp_path)
    config = load_config(tmp_path / "config.yaml")
    assert config.llm.provider == "anthropic"
    assert config.llm.model == "claude-sonnet-5"
    assert config.llm.temperature == 0.7


def test_copywriter_llm_without_profile_raises(tmp_path):
    _write_config(tmp_path, copywriter="llm")
    with pytest.raises(ConfigError, match="sender_profile.md"):
        load_config(tmp_path / "config.yaml")


def test_copywriter_llm_with_profile_loads(tmp_path):
    _write_config(tmp_path, copywriter="llm")
    (tmp_path / "sender_profile.md").write_text("TestCo builds things.")
    config = load_config(tmp_path / "config.yaml")
    assert config.sender.narrative == "TestCo builds things."


def test_invalid_copywriter_value_raises(tmp_path):
    _write_config(tmp_path, copywriter="not_a_real_option")
    with pytest.raises(ConfigError, match="providers.copywriter"):
        load_config(tmp_path / "config.yaml")
