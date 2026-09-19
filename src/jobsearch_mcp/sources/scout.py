"""Read-only adapter for the Scout remote MCP discovery tool.

Scout stays inactive unless an operator supplies a provider-approved access token
and an explicit argument template that matches the provider's published schema.
"""

import asyncio
import json
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator, SchemaError
from jsonschema.validators import validator_for
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ..models import Job
from ..security import _validate_url
from .normalize import clean, employment, make_job, number, period, restrictions, scope

SCOUT_MCP_ENDPOINT = "https://agentco.in/api/mcp-remote"
DISCOVER_TOOL = "scout_discover"
_CANONICAL_REMOTE_SCOPES = {
    "worldwide",
    "uk",
    "emea",
    "europe",
    "restricted",
    "remote_unspecified",
    "onsite",
    "hybrid",
    "unknown",
}
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


@asynccontextmanager
async def _open_session(access_token: str):
    """Open an authenticated MCP session without allowing endpoint overrides."""
    await asyncio.to_thread(_validate_url, SCOUT_MCP_ENDPOINT)
    async with AsyncExitStack() as stack:
        try:
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=httpx.Timeout(30),
                    follow_redirects=False,
                    trust_env=False,
                )
            )
        except Exception:
            raise RuntimeError("Scout HTTP client initialization failed") from None

        try:
            streams = await stack.enter_async_context(
                streamable_http_client(SCOUT_MCP_ENDPOINT, http_client=http_client)
            )
        except Exception:
            raise RuntimeError("Scout MCP connection failed") from None

        try:
            session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
            await session.initialize()
        except Exception:
            raise RuntimeError("Scout MCP session initialization failed") from None
        yield session


def _value(item, name: str, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _render_query(value, query: str) -> tuple[object, bool]:
    """Replace the one supported template variable in JSON values."""
    if isinstance(value, str):
        return value.replace("{query}", query), "{query}" in value
    if isinstance(value, list):
        output = []
        found = False
        for item in value:
            rendered, item_found = _render_query(item, query)
            output.append(rendered)
            found = found or item_found
        return output, found
    if isinstance(value, dict):
        output = {}
        found = False
        for key, item in value.items():
            rendered, item_found = _render_query(item, query)
            output[key] = rendered
            found = found or item_found
        return output, found
    return value, False


def _placeholder_names(value) -> set[str]:
    if isinstance(value, str):
        return set(_PLACEHOLDER.findall(value))
    if isinstance(value, list):
        return set().union(*(_placeholder_names(item) for item in value))
    if isinstance(value, dict):
        return set().union(*(_placeholder_names(item) for item in value.values()))
    return set()


def _arguments_from_config(config: str, query: str) -> dict:
    try:
        template = json.loads(config)
    except json.JSONDecodeError:
        raise ValueError("SCOUT_DISCOVER_ARGUMENTS must be valid JSON") from None
    if not isinstance(template, dict):
        raise ValueError("SCOUT_DISCOVER_ARGUMENTS must be a JSON object")

    placeholders = _placeholder_names(template)
    if placeholders - {"query"}:
        raise ValueError("SCOUT_DISCOVER_ARGUMENTS supports only the {query} placeholder")

    arguments, found_query = _render_query(template, query)
    if not found_query:
        raise ValueError("SCOUT_DISCOVER_ARGUMENTS must include a {query} placeholder")
    return arguments


def _input_schema(tool) -> dict:
    schema = _value(tool, "inputSchema")
    if not isinstance(schema, dict):
        raise ValueError("Scout discovery tool did not publish a JSON input schema")
    return schema


def _check_local_references(schema: object):
    """Prevent a provider schema from causing jsonschema to fetch remote refs."""
    if isinstance(schema, dict):
        for key in ("$ref", "$dynamicRef", "$recursiveRef"):
            reference = schema.get(key)
            if isinstance(reference, str) and not reference.startswith("#"):
                raise ValueError("Scout JSON Schema may not contain remote references")
        for value in schema.values():
            _check_local_references(value)
    elif isinstance(schema, list):
        for value in schema:
            _check_local_references(value)


def _validate_arguments(arguments: dict, schema: dict):
    _check_local_references(schema)
    try:
        validator_type = validator_for(schema, default=Draft202012Validator)
        validator_type.check_schema(schema)
    except SchemaError:
        raise ValueError("Scout published an invalid JSON input schema") from None

    errors = list(validator_type(schema).iter_errors(arguments))
    if errors:
        error = sorted(errors, key=lambda item: list(map(str, item.absolute_path)))[0]
        path = ".".join(str(part) for part in error.absolute_path)
        location = f" at {path}" if path else ""
        raise ValueError(f"Scout discovery arguments do not match its input schema{location}")


def _result_rows(result) -> list:
    if _value(result, "isError", False):
        raise RuntimeError("Scout discovery returned an MCP tool error")

    structured = _value(result, "structuredContent")
    if structured is not None:
        rows = _rows_from_json(structured)
        if rows is None:
            raise ValueError("Scout structured output must contain a jobs or results array")
        return rows

    content = _value(result, "content", []) or []
    for block in content:
        if _value(block, "type") != "text":
            continue
        text = _value(block, "text")
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        rows = _rows_from_json(payload)
        if rows is not None:
            return rows

    raise ValueError("Scout output was not JSON containing a jobs or results array")


def _rows_from_json(payload) -> list | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("jobs", "results"):
            if key in payload:
                rows = payload[key]
                if isinstance(rows, list):
                    return rows
                raise ValueError(f"Scout {key} field must be an array")
    return None


def _first(row: dict, names: tuple[str, ...], default=None):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _text(value, field: str, *, required: bool = False) -> str:
    if value is None:
        result = ""
    elif isinstance(value, (str, int, float)):
        result = clean(value)
    else:
        raise ValueError(f"Scout job field {field} has an unsupported shape")
    if required and not result:
        raise ValueError(f"Scout job is missing required field {field}")
    return result


def _location_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = _first(value, ("display_name", "displayName", "name", "label"))
    if isinstance(value, list):
        parts = [_text(part, "location") for part in value]
        return ", ".join(part for part in parts if part)
    return _text(value, "location")


def _boolean(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.casefold().strip()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _skills(value) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        raise ValueError("Scout job field skills has an unsupported shape")
    output = []
    for item in values:
        if isinstance(item, dict):
            item = _first(item, ("name", "label", "skill"))
        skill = _text(item, "skills")
        if skill:
            output.append(skill)
    return output


def _external_url(value, field: str, *, required: bool = False) -> str:
    url = _text(value, field, required=required)
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"Scout job field {field} must be an absolute HTTP(S) URL")
    return url


def _normalize_job(row: object) -> Job:
    if not isinstance(row, dict):
        raise ValueError("Scout jobs array must contain JSON objects")

    title = _text(
        _first(row, ("title", "job_title", "jobTitle", "position")), "title", required=True
    )
    company = _text(_first(row, ("company", "company_name", "companyName", "employer")), "company")
    location = _location_text(_first(row, ("location", "location_name", "locationName")))
    source_url = _external_url(
        _first(row, ("source_url", "sourceUrl", "job_url", "jobUrl", "listing_url", "url", "link")),
        "source_url",
        required=True,
    )
    application_url = _external_url(
        _first(
            row,
            (
                "application_url",
                "applicationUrl",
                "apply_url",
                "applyUrl",
                "application_link",
                "applicationLink",
            ),
        ),
        "application_url",
    )
    description = _text(
        _first(row, ("description", "job_description", "jobDescription")), "description"
    )

    explicit_scope = _text(_first(row, ("remote_scope", "remoteScope")), "remote_scope")
    if explicit_scope.casefold() in _CANONICAL_REMOTE_SCOPES:
        remote_scope = explicit_scope.casefold()
    else:
        remote_hint = _first(row, ("remote", "is_remote", "isRemote"))
        known_remote = _boolean(remote_hint) is True or "remote" in explicit_scope.casefold()
        remote_scope = scope(location or explicit_scope, description, known_remote=known_remote)

    currency = _text(_first(row, ("currency", "salary_currency", "salaryCurrency")), "currency")
    salary_text = _text(_first(row, ("salary_text", "salaryText")), "salary_text")
    prediction = _boolean(_first(row, ("salary_is_predicted", "salaryIsPredicted")))
    normalized = {
        "title": title,
        "company": company,
        "location": location,
        "remote_scope": remote_scope,
        "salary_min": number(_first(row, ("salary_min", "min_salary", "salaryMin"))),
        "salary_max": number(_first(row, ("salary_max", "max_salary", "salaryMax"))),
        "currency": currency or None,
        "salary_period": period(_first(row, ("salary_period", "salaryPeriod"))),
        "salary_is_predicted": prediction is True,
        "salary_text": salary_text,
        "employment_type": employment(
            _first(row, ("employment_type", "employmentType", "contract_type", "contractType"))
        ),
        "posted_at": _first(row, ("posted_at", "postedAt", "published_at", "publishedAt")),
        "source_url": source_url,
        "application_url": application_url,
        "description": description,
        "skills": _skills(_first(row, ("skills", "tags"))),
        "country_restrictions": restrictions(
            _first(row, ("country_restrictions", "countryRestrictions", "location_restrictions"))
        ),
    }
    source_id = _first(row, ("source_id", "sourceId", "job_id", "jobId", "id"))
    if source_id is not None:
        normalized["source_id"] = _text(source_id, "source_id")
    return make_job("scout", normalized)


async def search(query: str) -> list[Job]:
    """Search Scout using only the schema-validated, read-only discovery tool."""
    access_token = os.getenv("SCOUT_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise RuntimeError("Scout is disabled: SCOUT_ACCESS_TOKEN is not configured")

    discover_config = os.getenv("SCOUT_DISCOVER_ARGUMENTS", "").strip()
    if not discover_config:
        raise RuntimeError("Scout is disabled: SCOUT_DISCOVER_ARGUMENTS is not configured")

    arguments = _arguments_from_config(discover_config, query)
    async with _open_session(access_token) as session:
        try:
            tools = await session.list_tools()
        except Exception:
            raise RuntimeError("Scout tools/list request failed") from None
        discover_tool = next(
            (
                tool
                for tool in (_value(tools, "tools", []) or [])
                if _value(tool, "name") == DISCOVER_TOOL
            ),
            None,
        )
        if discover_tool is None:
            raise RuntimeError("Scout does not expose the scout_discover tool")
        _validate_arguments(arguments, _input_schema(discover_tool))

        try:
            result = await session.call_tool(DISCOVER_TOOL, arguments)
        except Exception:
            raise RuntimeError("Scout discovery request failed") from None

    return [_normalize_job(row) for row in _result_rows(result)]
