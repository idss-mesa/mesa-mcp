"""Zone and shared-collection configuration.

mesa-mcp defaults to the CyVerse ``iplant`` zone, but nothing about the
implementation is specific to it. These tests pin that: a deployment
against another zone must derive its accessible paths from configuration,
and a zone whose shared tree is not literally called ``shared`` must still
be reachable.

Note the scope: one server instance serves **one** zone. Federated paths
in another zone are refused by the path allowlist, which is the intended
behaviour — not a bug — but it is the reason a second zone needs a second
instance.
"""

from __future__ import annotations

import pytest

from mesa_mcp.auth.extract import resolve_credentials
from mesa_mcp.auth.models import AuthValue
from mesa_mcp.config import Config, IRODSConfig
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.access import assert_allowed


@pytest.mark.parametrize("zone", ["iplant", "myZone", "tempZone", "nasa-hq"])
def test_accessible_paths_follow_the_configured_zone(zone):
    cfg = Config(irods=IRODSConfig(zone=zone, user="alice", password="pw"))
    value = resolve_credentials(cfg)
    assert value.zone == zone
    assert value.accessible_paths() == [
        f"/{zone}/home/alice",
        f"/{zone}/home/shared",
    ]


@pytest.mark.parametrize(
    "shared_dir", ["shared", "projects", "community_released", "public"]
)
def test_shared_collection_name_is_configurable(shared_dir):
    """A zone whose shared tree is not called ``shared`` must be reachable.

    Regression: ``shared_dir_name`` existed in ``IRODSConfig`` but nothing
    read it, so every deployment was hard-wired to ``/<zone>/home/shared``
    regardless of configuration.
    """
    cfg = Config(
        irods=IRODSConfig(
            zone="myZone", user="alice", password="pw", shared_dir_name=shared_dir
        )
    )
    value = resolve_credentials(cfg)
    assert value.shared_path == f"/myZone/home/{shared_dir}"
    assert f"/myZone/home/{shared_dir}" in value.accessible_paths()


def test_shared_dir_name_defaults_to_shared():
    """The default must not change for existing CyVerse deployments."""
    assert (
        AuthValue(username="a", zone="z", password=None).shared_path == "/z/home/shared"
    )


def test_anonymous_caller_gets_only_the_configured_shared_tree():
    cfg = Config(irods=IRODSConfig(zone="myZone", shared_dir_name="projects"))
    value = resolve_credentials(cfg)
    assert value.is_anonymous()
    assert value.accessible_paths() == ["/myZone/home/projects"]


def test_paths_in_another_zone_are_refused():
    """One instance serves one zone.

    A federated path in a second zone is outside the allowlist. This is
    the intended boundary, and the reason multi-zone means multiple
    instances rather than one instance spanning zones.
    """
    value = AuthValue(username="alice", zone="myZone", password="pw")
    assert assert_allowed("/myZone/home/alice/data", value) == "/myZone/home/alice/data"
    for foreign in ("/otherZone/home/alice/data", "/iplant/home/shared/x"):
        with pytest.raises(ToolError) as err:
            assert_allowed(foreign, value)
        assert err.value.code == "forbidden"
