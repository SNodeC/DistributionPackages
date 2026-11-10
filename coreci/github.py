"""Bounded GitHub API reads without redirects."""
import json
import urllib.error
import urllib.parse
import urllib.request
from .contract import canonical, require


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        result = None
        return result

def api(path, token, method="GET", value=None):
    require(path.startswith("/") and not path.startswith("//"), "invalid GitHub API path")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "core-ci-worker",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if value is not None:
        data = canonical(value).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request("https://api.github.com" + path, data=data, headers=headers, method=method)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        body = response.read(2 * 1024 * 1024 + 1)
        require(len(body) <= 2 * 1024 * 1024, "GitHub JSON exceeds resource bound")
        result = json.loads(body) if body else None
    return result
