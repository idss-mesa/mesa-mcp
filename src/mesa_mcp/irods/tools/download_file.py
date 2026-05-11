"""``ds_download_file`` — return human-readable download instructions.

Python port of ``irods-mcp-server/irods/download_file.go``. Like
``ds_upload_file``, this returns the CLI snippets a client should run; it
does *not* fetch bytes itself.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
    require_current_config,
)
from mesa_mcp.irods._helpers import resolve_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.webdav import make_webdav_url
from mesa_mcp.server import register_tool


class DownloadFileInput(BaseModel):
    irods_path: str = Field(
        description="The iRODS path to the file (data-object) to download.",
    )
    local_path: str = Field(
        description=(
            "The local path to download the file (data-object) to. Must be "
            "a full path including the file name."
        ),
    )


def _curl_instruction(webdav_uri: str, local_path: str, recursive: bool) -> str:
    if recursive:
        return (
            "To download the entire directory using curl, run the following "
            f"command: \ncurl -r -L -o {local_path} {webdav_uri}\n"
            "This is just an example command. You may need to adjust it "
            "based on your requirements.\n"
        )
    return (
        "To download the file using curl, run the following command: \n"
        f"curl -L -o {local_path} {webdav_uri}\n"
        "This is just an example command. You may need to adjust it based "
        "on your requirements.\n"
    )


def _wget_instruction(webdav_uri: str, local_path: str, recursive: bool) -> str:
    if recursive:
        return (
            "You cannot download the entire directory using wget. Please "
            "use other methods for downloading directories.\n\t\t"
        )
    return (
        "To download the file using wget, run the following command: \n"
        f"\twget -O {local_path} {webdav_uri}\n"
        "\tThis is just an example command. You may need to adjust it "
        "based on your requirements.\n\t"
    )


def _gocmd_instruction(irods_path: str, local_path: str) -> str:
    return (
        "To download the entire directory using gocommands, run the "
        f"following command: \n\t\tgocmd get -K --progress {irods_path} "
        f"{local_path}\n\t\tThis is just an example command. You may need "
        "to adjust it based on your requirements.\n\t\t"
        "You will need to have gocommands installed and configured to use "
        "this command.\n\t\tCheck out https://learning.cyverse.org/ds/"
        "gocommands/ for more details.\n\t\t"
    )


def _icommands_instruction(
    irods_path: str,
    local_path: str,
    recursive: bool,
) -> str:
    flag = "-K -r -P" if recursive else "-K -P"
    return (
        "To download the file using gocommands, run the following "
        f"command: \n\t\tiget {flag} {irods_path} {local_path}\n\t\t"
        "This is just an example command. You may need to adjust it based "
        "on your requirements.\n\t\t"
        "You will need to have iCommands installed and configured to use "
        "this command.\n\t\tCheck out https://learning.cyverse.org/ds/"
        "icommands/ for more details.\n\t\t"
    )


@register_tool(
    "ds_download_file",
    "Returns how to download the full contgent of a file (data-object) "
    "with the specified path.\n\t\tThe specified path must be an iRODS "
    "path.\n\t\tReturns how to download the file using WebDAV, GoCommands "
    "(gocmd), and iCommands.",
    input_model=DownloadFileInput,
)
async def handle_download_file(args: DownloadFileInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    normalized = assert_allowed(args.irods_path, auth_value)

    pool = require_current_client_pool()
    config = require_current_config()
    session = pool.get(auth_value)

    kind, _model = resolve_target(session, normalized)
    recursive = kind == "collection"

    webdav_uri = make_webdav_url(config.irods.webdav_url, normalized, auth_value)
    curl = _curl_instruction(webdav_uri, args.local_path, recursive)
    wget = _wget_instruction(webdav_uri, args.local_path, recursive)
    gocmd = _gocmd_instruction(normalized, args.local_path)
    icmd = _icommands_instruction(normalized, args.local_path, recursive)

    text = f"{curl}\n{wget}\n{gocmd}\n{icmd}\n"
    return {
        "text": text,
        "irods_path": normalized,
        "local_path": args.local_path,
        "webdav_uri": webdav_uri,
        "is_dir": recursive,
    }
