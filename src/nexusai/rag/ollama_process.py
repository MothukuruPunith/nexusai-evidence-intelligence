"""Bounded local HTTP transport. Runs in a disposable process; never follows redirects."""

import json
import sys
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exchange(base: str, route: str, body=None):
    # Configuration validation in the parent accepts only numeric loopback HTTP URLs.
    request = urllib.request.Request(
        base + route,
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=55) as response:
        raw = response.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("response too large")
        return json.loads(raw)


def run(payload):
    tags = exchange(payload["url"], "/api/tags")
    found = next((m for m in tags["models"] if m["name"] == payload["model"]), None)
    if not found:
        return {"error": "generation_model_missing"}
    if found["digest"] != payload["digest"]:
        return {"error": "generation_model_changed"}
    result = exchange(payload["url"], "/api/chat", payload["body"])
    if result.get("done") is not True or result.get("done_reason") != "stop":
        return {"error": "generation_incomplete"}
    return {"content": result["message"]["content"]}


def main():
    try:
        result = run(json.load(sys.stdin))
    except TimeoutError:
        result = {"error": "generation_timeout"}
    except urllib.error.URLError:
        result = {"error": "generation_unavailable"}
    except (ValueError, KeyError, TypeError, StopIteration):
        result = {"error": "generation_invalid_response"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
