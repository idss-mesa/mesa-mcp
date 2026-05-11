"""Tests for the iRODS env-file credential loader.

The loader is what makes Mode B (local install) and Mode C (CyVerse VICE
app) work without any ``MESA_MCP_*`` boilerplate after the user has run
``iinit``: we read ``~/.irods/irods_environment.json`` and
``~/.irods/.irodsA`` directly. These tests use temporary files and the
standard ``IRODS_ENVIRONMENT_FILE`` / ``IRODS_AUTHENTICATION_FILE``
overrides — no real iRODS server needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from irods.password_obfuscation import encode as scramble

from mesa_mcp.auth import (
    AuthValue,
    extract_from_irods_env_file,
    load_irods_environment,
    load_irods_password,
    resolve_credentials,
)
from mesa_mcp.auth.irods_env import (
    DEFAULT_ENV_FILENAME,
    DEFAULT_PASSWORD_FILENAME,
    ENV_FILE_OVERRIDE,
    PASSWORD_FILE_OVERRIDE,
    default_env_file,
    default_password_file,
)
from mesa_mcp.config import Config


@pytest.fixture
def irods_env_dir(tmp_path: Path) -> Path:
    """Create a fake ~/.irods/ layout under tmp_path."""
    d = tmp_path / ".irods"
    d.mkdir()
    return d


def _write_env(
    dirpath: Path,
    **overrides: object,
) -> Path:
    payload: dict[str, object] = {
        "irods_user_name": "alice",
        "irods_zone_name": "iplant",
        "irods_host": "data.cyverse.org",
        "irods_port": 1247,
    }
    payload.update(overrides)
    p = dirpath / DEFAULT_ENV_FILENAME
    p.write_text(json.dumps(payload))
    return p


def _write_password(dirpath: Path, plaintext: str) -> Path:
    p = dirpath / DEFAULT_PASSWORD_FILENAME
    p.write_text(scramble(plaintext))
    return p


# ---------------------------------------------------------------------------
# Default path helpers
# ---------------------------------------------------------------------------


def test_default_env_file_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_FILE_OVERRIDE, "/tmp/custom/irods_environment.json")
    assert default_env_file() == Path("/tmp/custom/irods_environment.json")


def test_default_env_file_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_FILE_OVERRIDE, raising=False)
    monkeypatch.setenv("HOME", "/tmp/fake-home")
    assert default_env_file() == Path("/tmp/fake-home/.irods/irods_environment.json")


def test_default_password_file_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PASSWORD_FILE_OVERRIDE, "/tmp/secrets/.irodsA")
    assert default_password_file() == Path("/tmp/secrets/.irodsA")


# ---------------------------------------------------------------------------
# load_irods_environment / load_irods_password
# ---------------------------------------------------------------------------


def test_load_irods_environment_reads_dict(irods_env_dir: Path) -> None:
    env_file = _write_env(irods_env_dir, irods_user_name="bob")
    data = load_irods_environment(env_file)
    assert data["irods_user_name"] == "bob"
    assert data["irods_zone_name"] == "iplant"


def test_load_irods_environment_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_irods_environment(tmp_path / "nope.json")


def test_load_irods_environment_non_object_raises(irods_env_dir: Path) -> None:
    p = irods_env_dir / "list.json"
    p.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(ValueError, match="JSON object"):
        load_irods_environment(p)


def test_load_irods_password_round_trips(irods_env_dir: Path) -> None:
    pw_file = _write_password(irods_env_dir, "hunter2")
    assert load_irods_password(pw_file) == "hunter2"


def test_load_irods_password_missing_returns_none(tmp_path: Path) -> None:
    assert load_irods_password(tmp_path / "absent.irodsA") is None


def test_load_irods_password_empty_returns_none(irods_env_dir: Path) -> None:
    pw_file = irods_env_dir / DEFAULT_PASSWORD_FILENAME
    pw_file.write_text("\n")
    assert load_irods_password(pw_file) is None


# ---------------------------------------------------------------------------
# extract_from_irods_env_file
# ---------------------------------------------------------------------------


def test_extract_native_with_password(irods_env_dir: Path) -> None:
    env_file = _write_env(irods_env_dir)
    pw_file = _write_password(irods_env_dir, "hunter2")
    av = extract_from_irods_env_file(env_file=env_file, password_file=pw_file)
    assert isinstance(av, AuthValue)
    assert av.username == "alice"
    assert av.zone == "iplant"
    assert av.password == "hunter2"
    assert av.auth_scheme == "native"


def test_extract_anonymous_user_has_no_password(irods_env_dir: Path) -> None:
    env_file = _write_env(irods_env_dir, irods_user_name="anonymous")
    # Even if a stray password file exists, anonymous gets None.
    pw_file = _write_password(irods_env_dir, "shouldnotbeused")
    av = extract_from_irods_env_file(env_file=env_file, password_file=pw_file)
    assert av.username == "anonymous"
    assert av.password is None
    assert av.auth_scheme == "anonymous"


def test_extract_recognises_pam_scheme(irods_env_dir: Path) -> None:
    env_file = _write_env(irods_env_dir, irods_authentication_scheme="pam")
    pw_file = _write_password(irods_env_dir, "hunter2")
    av = extract_from_irods_env_file(env_file=env_file, password_file=pw_file)
    assert av.auth_scheme == "pam"


def test_extract_unknown_scheme_falls_back_to_native(irods_env_dir: Path) -> None:
    env_file = _write_env(irods_env_dir, irods_authentication_scheme="quantum-tunneling")
    pw_file = _write_password(irods_env_dir, "hunter2")
    av = extract_from_irods_env_file(env_file=env_file, password_file=pw_file)
    assert av.auth_scheme == "native"


def test_extract_zone_override_wins(irods_env_dir: Path) -> None:
    env_file = _write_env(irods_env_dir, irods_zone_name="otherzone")
    pw_file = _write_password(irods_env_dir, "hunter2")
    av = extract_from_irods_env_file(
        env_file=env_file, password_file=pw_file, zone_override="iplant"
    )
    assert av.zone == "iplant"


def test_extract_missing_password_file_allowed_by_default(irods_env_dir: Path) -> None:
    env_file = _write_env(irods_env_dir)
    av = extract_from_irods_env_file(
        env_file=env_file, password_file=irods_env_dir / "missing.irodsA"
    )
    assert av.username == "alice"
    assert av.password is None  # caller falls back elsewhere
    assert av.auth_scheme == "native"


def test_extract_missing_password_file_with_require_password_raises(
    irods_env_dir: Path,
) -> None:
    env_file = _write_env(irods_env_dir)
    with pytest.raises(FileNotFoundError, match="iRODS password file"):
        extract_from_irods_env_file(
            env_file=env_file,
            password_file=irods_env_dir / "missing.irodsA",
            require_password=True,
        )


def test_extract_picks_up_irods_env_override(
    irods_env_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = _write_env(irods_env_dir)
    pw_file = _write_password(irods_env_dir, "hunter2")
    monkeypatch.setenv(ENV_FILE_OVERRIDE, str(env_file))
    monkeypatch.setenv(PASSWORD_FILE_OVERRIDE, str(pw_file))
    # Pass no explicit paths — the function must respect the env overrides.
    av = extract_from_irods_env_file()
    assert av.username == "alice"
    assert av.password == "hunter2"


# ---------------------------------------------------------------------------
# resolve_credentials chain
# ---------------------------------------------------------------------------


def test_resolve_prefers_explicit_env_vars(irods_env_dir: Path) -> None:
    env_file = _write_env(irods_env_dir, irods_user_name="filesayalice")
    pw_file = _write_password(irods_env_dir, "filepass")
    cfg = Config()
    av = resolve_credentials(
        cfg,
        env={
            "MESA_MCP_IRODS_USER": "envsaysbob",
            "MESA_MCP_IRODS_PASSWORD": "envpass",
        },
        irods_env_file=env_file,
        irods_password_file=pw_file,
    )
    assert av.username == "envsaysbob"
    assert av.password == "envpass"


def test_resolve_falls_back_to_env_file_when_env_vars_empty(
    irods_env_dir: Path,
) -> None:
    env_file = _write_env(irods_env_dir, irods_user_name="filesayalice")
    pw_file = _write_password(irods_env_dir, "filepass")
    cfg = Config()
    av = resolve_credentials(
        cfg,
        env={},  # nothing in env
        irods_env_file=env_file,
        irods_password_file=pw_file,
    )
    assert av.username == "filesayalice"
    assert av.password == "filepass"
    assert av.auth_scheme == "native"


def test_resolve_falls_back_to_anonymous_when_nothing(tmp_path: Path) -> None:
    cfg = Config()
    av = resolve_credentials(
        cfg,
        env={},
        irods_env_file=tmp_path / "missing.json",
        irods_password_file=tmp_path / "missing.irodsA",
    )
    assert av.username == "anonymous"
    assert av.auth_scheme == "anonymous"
    assert av.password is None


def test_resolve_honours_irods_env_file_when_password_missing(
    irods_env_dir: Path,
) -> None:
    """A common VICE pattern: env file present, .irodsA not yet written."""
    env_file = _write_env(irods_env_dir, irods_user_name="alice")
    cfg = Config()
    av = resolve_credentials(
        cfg,
        env={},
        irods_env_file=env_file,
        irods_password_file=irods_env_dir / "absent.irodsA",
    )
    assert av.username == "alice"
    assert av.password is None
    assert av.auth_scheme == "native"
