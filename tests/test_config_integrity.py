"""Configuration must be honoured, and typos must be visible.

Pydantic ignores unknown keys by default, which is how several settings in
this codebase came to exist without any reader: nothing complained, and a
setting that did nothing looked identical to one that worked.

These tests cover both halves — that the settings we claim to honour are
actually honoured, and that a key nobody will read is reported rather than
silently dropped.
"""

from __future__ import annotations

import logging
import textwrap

import pytest

from mesa_mcp.config import Config, OLSConfig, load_config, set_active_config
from mesa_mcp.ols.client import OLSClient, get_ols_client


@pytest.fixture(autouse=True)
def _clear_active_config():
    yield
    set_active_config(None)


def _write(tmp_path, body: str):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(body))
    return path


# ---------------------------------------------------------------------------
# Unknown keys are reported
# ---------------------------------------------------------------------------


def test_unknown_key_in_a_known_section_warns(tmp_path, caplog):
    path = _write(
        tmp_path,
        """
        irods:
          zone: myZone
          shared_dir: typo_for_shared_dir_name
        """,
    )
    with caplog.at_level(logging.WARNING):
        config = load_config(path)
    assert "shared_dir" in caplog.text
    # The valid key in the same section must still apply.
    assert config.irods.zone == "myZone"


def test_unknown_section_warns(tmp_path, caplog):
    path = _write(tmp_path, "not_a_section:\n  x: 1\n")
    with caplog.at_level(logging.WARNING):
        load_config(path)
    assert "not_a_section" in caplog.text


def test_valid_config_warns_about_nothing(tmp_path, caplog):
    """A correct file must stay quiet, or operators learn to ignore warnings."""
    path = _write(
        tmp_path,
        """
        irods:
          zone: myZone
          shared_dir_name: projects
        ols:
          request_timeout: 5
        """,
    )
    with caplog.at_level(logging.WARNING):
        config = load_config(path)
    assert "unknown" not in caplog.text
    assert config.irods.shared_dir_name == "projects"


# ---------------------------------------------------------------------------
# OLS settings are actually honoured
# ---------------------------------------------------------------------------


def test_ols_client_honours_configured_ttls_and_timeout():
    """Regression: OLSConfig advertised TTLs the client ignored.

    The client hardcoded the values ported from esiil-portal, so an
    operator setting ``search_cache_ttl: 60`` silently got 3600.
    """
    set_active_config(
        Config(
            ols=OLSConfig(
                ontology_cache_ttl=111,
                term_cache_ttl=222,
                search_cache_ttl=333,
                request_timeout=44.0,
            )
        )
    )
    client = get_ols_client()
    assert client._cache_ontology.ttl == 111
    assert client._cache_term.ttl == 222
    assert client._cache_search.ttl == 333
    assert client.timeout == 44.0


def test_ols_client_falls_back_to_ported_defaults():
    """Usable with no config bound — tests, scripts, embedders."""
    client = OLSClient()
    assert client.timeout == 15
    assert client._cache_ontology.ttl == 86400
    assert client._cache_search.ttl == 3600


def test_ols_base_url_default_targets_the_v2_api():
    """The config default must match what the endpoints require.

    Every OLS call appends to ``base_url``; the OLS4 v1 root does not
    serve them. The default was ``.../ols4/api`` while the client used
    ``.../ols4/api/v2`` — harmless only while nothing read the field.
    """
    assert OLSConfig().base_url.endswith("/v2")
    set_active_config(Config())
    assert get_ols_client().base_url == OLSConfig().base_url
