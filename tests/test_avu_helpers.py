"""Unit tests for :mod:`mesa_mcp.irods._avu_helpers`.

These exercise the small shared layer behind ``ds_add_avu``,
``ds_delete_avu``, ``ds_list_avus``, ``ds_get_metadata`` and
``mesa_avu_apply_term``. Everything is mocked — no live iRODS.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from irods.exception import CollectionDoesNotExist, DataObjectDoesNotExist

from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import (
    add_avu_to_irods,
    delete_avu_from_irods,
    list_avus_for_path,
    resolve_path_target,
)


@pytest.fixture
def session() -> MagicMock:
    s = MagicMock(name="iRODSSession")
    s.collections = MagicMock(name="collections")
    s.data_objects = MagicMock(name="data_objects")
    s.metadata = MagicMock(name="metadata")
    return s


# ---------------------------------------------------------------------------
# resolve_path_target
# ---------------------------------------------------------------------------


class TestResolvePathTarget:
    def test_data_object_resolves(self, session: MagicMock) -> None:
        session.data_objects.get.return_value = MagicMock()
        assert (
            resolve_path_target(session, "/iplant/home/alice/file.csv")
            == "data_object"
        )

    def test_collection_resolves(self, session: MagicMock) -> None:
        session.data_objects.get.side_effect = DataObjectDoesNotExist
        session.collections.get.return_value = MagicMock()
        assert (
            resolve_path_target(session, "/iplant/home/alice/data")
            == "collection"
        )

    def test_missing_path_raises(self, session: MagicMock) -> None:
        session.data_objects.get.side_effect = DataObjectDoesNotExist
        session.collections.get.side_effect = CollectionDoesNotExist
        with pytest.raises(ToolError) as exc:
            resolve_path_target(session, "/iplant/home/alice/nope")
        assert exc.value.code == "not_found"

    def test_hint_collection_skips_data_object_probe(self, session: MagicMock) -> None:
        session.collections.get.return_value = MagicMock()
        result = resolve_path_target(
            session, "/iplant/home/alice/data", hint="collection"
        )
        assert result == "collection"
        session.data_objects.get.assert_not_called()

    def test_bad_hint_rejected(self, session: MagicMock) -> None:
        with pytest.raises(ToolError) as exc:
            resolve_path_target(session, "/iplant/home/alice", hint="elephant")
        assert exc.value.code == "invalid_argument"


# ---------------------------------------------------------------------------
# add_avu_to_irods
# ---------------------------------------------------------------------------


class TestAddAvuToIrods:
    def test_writes_through_metadata_add(self, session: MagicMock) -> None:
        avu = {"attribute": "envo.biome", "value": "forest", "unit": "ENVO:0001"}
        written = add_avu_to_irods(
            session, "/iplant/home/alice/file.csv", "data_object", avu
        )
        assert written == avu
        session.metadata.add.assert_called_once()
        args, _ = session.metadata.add.call_args
        # The first positional arg must be the DataObject SQL model class.
        from irods.models import DataObject

        assert args[0] is DataObject
        assert args[1] == "/iplant/home/alice/file.csv"
        meta = args[2]
        assert meta.name == "envo.biome"
        assert meta.value == "forest"
        assert meta.units == "ENVO:0001"

    def test_collection_uses_collection_model(self, session: MagicMock) -> None:
        avu = {"attribute": "mesa.enabled", "value": "true", "unit": ""}
        add_avu_to_irods(session, "/iplant/home/alice/proj", "collection", avu)
        from irods.models import Collection

        args, _ = session.metadata.add.call_args
        assert args[0] is Collection

    def test_missing_attribute_raises(self, session: MagicMock) -> None:
        with pytest.raises(ToolError) as exc:
            add_avu_to_irods(
                session,
                "/iplant/home/alice/file.csv",
                "data_object",
                {"attribute": "", "value": "x"},
            )
        assert exc.value.code == "invalid_argument"
        session.metadata.add.assert_not_called()

    def test_irods_exception_wrapped(self, session: MagicMock) -> None:
        session.metadata.add.side_effect = RuntimeError("boom")
        with pytest.raises(ToolError) as exc:
            add_avu_to_irods(
                session,
                "/iplant/home/alice/file.csv",
                "data_object",
                {"attribute": "k", "value": "v"},
            )
        assert exc.value.code == "irods_error"


# ---------------------------------------------------------------------------
# delete_avu_from_irods
# ---------------------------------------------------------------------------


class TestDeleteAvuFromIrods:
    def test_delete_through_metadata_remove(self, session: MagicMock) -> None:
        delete_avu_from_irods(
            session,
            "/iplant/home/alice/file.csv",
            "data_object",
            {"attribute": "k", "value": "v", "unit": "U"},
        )
        session.metadata.remove.assert_called_once()
        args, _ = session.metadata.remove.call_args
        meta = args[2]
        assert (meta.name, meta.value, meta.units) == ("k", "v", "U")

    def test_irods_failure_wrapped(self, session: MagicMock) -> None:
        session.metadata.remove.side_effect = RuntimeError("no such avu")
        with pytest.raises(ToolError) as exc:
            delete_avu_from_irods(
                session,
                "/iplant/home/alice/file.csv",
                "data_object",
                {"attribute": "k"},
            )
        assert exc.value.code == "irods_error"


# ---------------------------------------------------------------------------
# list_avus_for_path
# ---------------------------------------------------------------------------


class TestListAvusForPath:
    def test_returns_triples(self, session: MagicMock) -> None:
        m1 = MagicMock(name="envo.biome")
        m1.name, m1.value, m1.units = "envo.biome", "forest", "ENVO:0001"
        m1.avu_id = 7
        m2 = MagicMock(name="mesa.enabled")
        m2.name, m2.value, m2.units = "mesa.enabled", "true", ""
        m2.avu_id = 9
        session.metadata.get.return_value = [m1, m2]

        avus = list_avus_for_path(session, "/iplant/home/alice/file.csv", "data_object")
        assert avus == [
            {"id": 7, "attribute": "envo.biome", "value": "forest", "unit": "ENVO:0001"},
            {"id": 9, "attribute": "mesa.enabled", "value": "true", "unit": ""},
        ]

    def test_irods_failure_wrapped(self, session: MagicMock) -> None:
        session.metadata.get.side_effect = RuntimeError("connection lost")
        with pytest.raises(ToolError) as exc:
            list_avus_for_path(session, "/iplant/home/alice", "collection")
        assert exc.value.code == "irods_error"
