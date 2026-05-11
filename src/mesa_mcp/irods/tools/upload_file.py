"""``ds_upload_file`` — return human-readable upload instructions.

Python port of ``irods-mcp-server/irods/upload_file.go``. The Go tool does
*not* upload; it returns curl/gocmd/icommands instructions with the WebDAV
URI baked in. We do the same so MCP clients can route the user to the
appropriate CLI.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_config,
)
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.webdav import make_webdav_url
from mesa_mcp.server import register_tool


class UploadFileInput(BaseModel):
    local_path: str = Field(
        description="The local path to the file (data-object) to upload.",
    )
    irods_path: str = Field(
        description="The target iRODS path to upload the file (data-object) to.",
    )
    is_dir: bool = Field(
        default=False,
        description="Set to true if uploading a directory (collection). Default is false.",
    )


def _curl_instruction(local_path: str, webdav_uri: str, recursive: bool) -> str:
    if recursive:
        return (
            "You cannot upload the entire directory using curl. Please use "
            "other methods for uploading directories.\n"
        )
    return (
        "To upload the file using curl, run the following command: \n"
        f"curl -L -T {local_path} {webdav_uri}\n"
        "This is just an example command. You may need to adjust it based "
        "on your requirements.\n"
    )


def _gocmd_instruction(local_path: str, irods_path: str) -> str:
    return (
        "To upload the entire directory using gocommands, run the following "
        f"command: \n\t\tgocmd put -K --progress {local_path} {irods_path}\n"
        "\t\tThis is just an example command. You may need to adjust it "
        "based on your requirements.\n"
        "\t\tYou will need to have gocommands installed and configured to "
        "use this command.\n"
        "\t\tCheck out https://learning.cyverse.org/ds/gocommands/ for more "
        "details.\n\t\t"
    )


def _icommands_instruction(
    local_path: str,
    irods_path: str,
    recursive: bool,
) -> str:
    flag = "-r -P -K" if recursive else "-K"
    return (
        "To upload the file using gocommands, run the following command: \n"
        f"\t\tiput {flag} {local_path} {irods_path}\n"
        "\t\tThis is just an example command. You may need to adjust it "
        "based on your requirements.\n"
        "\t\tYou will need to have iCommands installed and configured to "
        "use this command.\n"
        "\t\tCheck out https://learning.cyverse.org/ds/icommands/ for more "
        "details.\n\t\t"
    )


@register_tool(
    "ds_upload_file",
    "Returns how to upload the full contgent of a file (data-object) to the "
    "specified path.\n\t\tThe specified path must be an iRODS path.\n\t\t"
    "Returns how to upload the file using WebDAV, GoCommands (gocmd), and "
    "iCommands.",
    input_model=UploadFileInput,
)
async def handle_upload_file(args: UploadFileInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    config = require_current_config()
    normalized = assert_allowed(args.irods_path, auth_value)

    webdav_uri = make_webdav_url(config.irods.webdav_url, normalized, auth_value)

    curl = _curl_instruction(args.local_path, webdav_uri, args.is_dir)
    gocmd = _gocmd_instruction(args.local_path, normalized)
    icmd = _icommands_instruction(args.local_path, normalized, args.is_dir)

    text = f"{curl}\n{gocmd}\n{icmd}\n"
    return {
        "text": text,
        "local_path": args.local_path,
        "irods_path": normalized,
        "webdav_uri": webdav_uri,
        "is_dir": args.is_dir,
    }
