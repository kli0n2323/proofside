from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_BASE_URL = "https://api.openai.com/v1"
LOCAL_BASE_URL = "http://localhost:11434/v1"
REQUEST_TIMEOUT_SECONDS = 60
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class ProposalError(ValueError):
    pass


# Refuse redirects so bearer credentials cannot leave the selected endpoint.
class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


_MODEL_OPENER = build_opener(NoRedirectHandler())


def request_model(base_url: str, model: str, prompt: str, api_key: str | None) -> str:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with _MODEL_OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response_text = response.read().decode("utf-8")
    except HTTPError as error:
        if error.code in REDIRECT_STATUS_CODES:
            raise ProposalError(
                f"model endpoint returned HTTP redirect {error.code}; "
                "redirects are not followed for credential safety"
            ) from error
        raise ProposalError(f"model endpoint returned HTTP {error.code}: {error.reason}") from error
    except (URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise ProposalError(f"could not reach model endpoint: {reason}") from error
    except UnicodeDecodeError as error:
        raise ProposalError("model endpoint returned non-UTF-8 content") from error

    try:
        response_data = json.loads(response_text)
        content = response_data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise ProposalError("model endpoint returned an unexpected response shape") from error
    if not isinstance(content, str) or not content.strip():
        raise ProposalError("model endpoint returned no model text")
    return content


def resolve_model_endpoint_and_key(
    model_source: str,
    base_url: str | None,
    api_key_env: str | None,
) -> tuple[str, str | None]:
    if model_source == "local":
        if api_key_env:
            raise ProposalError("--api-key-env is not supported in local mode")
        return base_url or LOCAL_BASE_URL, None
    if model_source != "api":
        raise ProposalError("model source must be api or local")

    endpoint = base_url or API_BASE_URL
    if urlparse(endpoint).scheme.lower() != "https":
        raise ProposalError("API mode requires an https:// endpoint")
    if base_url is None:
        if api_key_env:
            raise ProposalError("--api-key-env requires a custom API --base-url")
        environment_name = "OPENAI_API_KEY"
    else:
        if not api_key_env:
            raise ProposalError("a custom API endpoint requires --api-key-env")
        environment_name = api_key_env
    api_key = os.environ.get(environment_name)
    if not api_key:
        raise ProposalError(f"API mode requires environment variable {environment_name}")
    return endpoint, api_key
