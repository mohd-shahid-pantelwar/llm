import html
import re
import urllib.parse

import requests

from database.redis import r

# Provider settings live in Redis so admins can change them from the UI
# without a redeploy. DuckDuckGo needs no key and is the default.
SETTINGS_PREFIX = "admin:settings:webSearch:"

DEFAULT_RESULT_COUNT = 5
REQUEST_TIMEOUT = 10
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def get_search_settings():
    return {
        "provider": r.get(SETTINGS_PREFIX + "provider") or "duckduckgo",
        "apiKey": r.get(SETTINGS_PREFIX + "apiKey") or "",
        "googleCx": r.get(SETTINGS_PREFIX + "googleCx") or "",
        "resultCount": int(r.get(SETTINGS_PREFIX + "resultCount") or DEFAULT_RESULT_COUNT),
    }


def save_search_settings(provider: str, api_key: str, google_cx: str, result_count: int):
    r.set(SETTINGS_PREFIX + "provider", provider)
    r.set(SETTINGS_PREFIX + "apiKey", api_key)
    r.set(SETTINGS_PREFIX + "googleCx", google_cx)
    r.set(SETTINGS_PREFIX + "resultCount", str(result_count))


def _search_duckduckgo(query: str, count: int):
    # lite.duckduckgo.com first: some DNS filters block html.duckduckgo.com
    # (CNAME to safe.duckduckgo.com) but leave the lite endpoint working.
    page = None
    last_err = None
    for url, kwargs in (
        ("https://lite.duckduckgo.com/lite/", {"params": {"q": query}}),
        ("https://html.duckduckgo.com/html/", {"data": {"q": query}}),
    ):
        try:
            res = requests.post(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, **kwargs)
            res.raise_for_status()
            page = res.text
            break
        except Exception as e:
            last_err = e
    if page is None:
        raise last_err

    # Both endpoints mark result links/snippets with result-link/result__a and
    # result-snippet/result__snippet classes (lite uses single quotes).
    links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*class=[\'"]result[-_]+(?:link|a)[\'"][^>]*>(.*?)</a>', page, re.DOTALL)
    if not links:
        links = re.findall(r'<a[^>]*class=[\'"]result[-_]+(?:link|a)[\'"][^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.DOTALL)
    snippets = re.findall(r'<(?:a|td)[^>]*class=[\'"]result[-_]+snippet[\'"][^>]*>(.*?)</(?:a|td)>', page, re.DOTALL)

    results = []
    for i, (href, title_html) in enumerate(links[:count]):
        # DDG links are redirects: //duckduckgo.com/l/?uddg=<urlencoded-target>&...
        url = href
        uddg = re.search(r"[?&]uddg=([^&]+)", href)
        if uddg:
            url = urllib.parse.unquote(uddg.group(1))
        title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        snippet = ""
        if i < len(snippets):
            snippet = html.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


def _search_brave(query: str, count: int, api_key: str):
    res = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": count},
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    res.raise_for_status()
    items = res.json().get("web", {}).get("results", [])
    return [
        {"title": i.get("title", ""), "url": i.get("url", ""), "snippet": i.get("description", "")}
        for i in items[:count]
    ]


def _search_google_pse(query: str, count: int, api_key: str, cx: str):
    res = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": api_key, "cx": cx, "q": query, "num": min(count, 10)},
        timeout=REQUEST_TIMEOUT,
    )
    res.raise_for_status()
    items = res.json().get("items", [])
    return [
        {"title": i.get("title", ""), "url": i.get("link", ""), "snippet": i.get("snippet", "")}
        for i in items[:count]
    ]


def search_web(query: str):
    """Run a web search with the admin-configured provider.

    Returns (results, error). results is a list of {title, url, snippet};
    error is None on success or a human-readable string on failure.
    """
    settings = get_search_settings()
    provider = settings["provider"]
    count = settings["resultCount"]
    try:
        if provider == "brave":
            if not settings["apiKey"]:
                return [], "Brave search selected but no API key is configured"
            return _search_brave(query, count, settings["apiKey"]), None
        if provider == "google_pse":
            if not settings["apiKey"] or not settings["googleCx"]:
                return [], "Google PSE selected but API key or engine ID (cx) is missing"
            return _search_google_pse(query, count, settings["apiKey"], settings["googleCx"]), None
        return _search_duckduckgo(query, count), None
    except Exception as e:
        return [], f"Web search failed ({provider}): {e}"


def format_results_for_prompt(results):
    lines = ["Web search results for the user's latest question. Use them to answer and cite source URLs where relevant:"]
    for i, res in enumerate(results, 1):
        lines.append(f"{i}. {res['title']}\n   {res['snippet']}\n   URL: {res['url']}")
    return "\n".join(lines)


def results_as_sources(results):
    # Match the RAG source shape ({id, chunk, score}) so the frontend
    # renders web results in the existing sources UI.
    return [
        {"id": res["url"], "chunk": f"🌐 {res['title']}\n{res['snippet']}\n{res['url']}", "score": 1.0}
        for res in results
    ]
