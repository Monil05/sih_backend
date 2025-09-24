# services/web_service.py
import requests
import urllib.parse
from typing import Optional

DDG_API = "https://api.duckduckgo.com/"

def _ddg_search(query: str, timeout: int = 8) -> Optional[str]:
    """
    Use DuckDuckGo Instant Answer API to fetch a short snippet.
    Returns a best-effort text snippet or None.
    """
    try:
        if not query:
            return None
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "no_redirect": 1,
            "skip_disambig": 1
        }
        r = requests.get(DDG_API, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()

        # Preferred: AbstractText
        abstract = data.get("AbstractText")
        if abstract and abstract.strip():
            return abstract.strip()

        # Fallback: RelatedTopics (take first few Texts)
        rel = data.get("RelatedTopics", [])
        snippets = []

        def collect_text(items):
            for item in items:
                if isinstance(item, dict):
                    t = item.get("Text")
                    if t and t.strip():
                        snippets.append(t.strip())
                    # some items have nested 'Topics'
                    if "Topics" in item and isinstance(item["Topics"], list):
                        collect_text(item["Topics"])
        collect_text(rel)

        if snippets:
            # return first 2-3 short snippets joined
            return " — ".join(snippets[:3])
        return None
    except Exception:
        return None


def get_prevalent_soils(state: str) -> Optional[str]:
    """
    Query DDG for common soils in a state (India). Returns a short snippet or None.
    """
    if not state:
        return None
    q = f"common soil types in {state} India"
    return _ddg_search(q)


def get_fertilizer_guidance(soil: str, ph: Optional[float] = None, moisture: Optional[float] = None) -> Optional[str]:
    """
    Query DDG for fertilizer guidance for a soil + pH/moisture context.
    Returns a snippet or None.
    """
    if not soil:
        return None
    q = f"fertilizer recommendation for {soil} soil India"
    if ph is not None:
        q += f" pH {ph}"
    if moisture is not None:
        q += f" moisture {moisture}"
    return _ddg_search(q)
