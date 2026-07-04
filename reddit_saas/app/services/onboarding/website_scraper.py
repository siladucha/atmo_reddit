"""Website Scraper — fetches and extracts text from company websites.

Used in onboarding Step 1 to auto-build company profile.
Uses httpx (async) + BeautifulSoup4 for HTML parsing.
Total timeout: 15 seconds. Graceful failure on any error.
"""

import asyncio
import re
from urllib.parse import urljoin, urlparse

from app.logging_config import get_logger

logger = get_logger(__name__)

# Pages to try fetching beyond homepage
SUBPAGE_PATHS = ["/about", "/about-us", "/product", "/platform", "/solutions"]

# Tags to remove before text extraction
REMOVE_TAGS = ["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]

# Max content length per page (chars)
MAX_PAGE_TEXT = 5000


async def scrape_company_website(url: str) -> dict:
    """Scrape company website and extract structured text content.

    Fetches homepage + attempts /about and /product pages.
    Strips navigation, scripts, styles. Returns clean text.

    Args:
        url: Company website URL (with or without https://).

    Returns:
        Dict with keys:
        - pages: {"home": "...", "about": "...", "product": "..."} (may be partial)
        - title: Page title from homepage
        - meta_description: Meta description from homepage
        - domain: Extracted domain name
        - error: Error message if scraping failed (None on success)
    """
    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError as e:
        logger.error("Missing dependency for website scraper: %s", e)
        return {"error": f"Missing dependency: {e}", "pages": {}, "title": "", "meta_description": "", "domain": ""}

    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    url = url.rstrip("/")

    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path.split("/")[0]

    result = {
        "pages": {},
        "title": "",
        "meta_description": "",
        "domain": domain,
        "error": None,
    }

    # User-Agent rotation for sites that block bots
    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]

    try:
        homepage_fetched = False

        for ua in USER_AGENTS:
            try:
                async with httpx.AsyncClient(
                    timeout=12.0,
                    follow_redirects=True,
                    headers={"User-Agent": ua},
                ) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")

                        # Extract title
                        title_tag = soup.find("title")
                        if title_tag:
                            result["title"] = title_tag.get_text(strip=True)[:200]

                        # Extract meta description
                        meta = soup.find("meta", attrs={"name": "description"})
                        if meta and meta.get("content"):
                            result["meta_description"] = meta["content"][:500]

                        # Extract main text
                        result["pages"]["home"] = _extract_text(soup)
                        homepage_fetched = True

                        # Find about/product links
                        subpages_to_fetch = _find_subpage_links(soup, url)
                        break  # Success, stop retrying
                    elif resp.status_code in (403, 401, 429, 503):
                        # Blocked — try next UA
                        continue
                    else:
                        # Other error — don't retry
                        result["error"] = f"Homepage returned status {resp.status_code}"
                        break
            except (httpx.TimeoutException, httpx.ConnectError):
                continue  # Try next UA

        if not homepage_fetched:
            # All retries failed — return partial result with domain-derived name
            result["error"] = f"Website blocked our request (tried {len(USER_AGENTS)} approaches). Fill in details manually."
            result["company_name_fallback"] = _derive_company_name(domain)
            return result

        # Fetch subpages (best effort)
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENTS[0]},
        ) as client:
            for path, page_type in subpages_to_fetch[:3]:
                try:
                    sub_url = urljoin(url, path)
                    sub_resp = await client.get(sub_url)
                    if sub_resp.status_code == 200:
                        sub_soup = BeautifulSoup(sub_resp.text, "html.parser")
                        text = _extract_text(sub_soup)
                        if text and len(text) > 50:
                            result["pages"][page_type] = text
                except Exception:
                    continue

    except asyncio.TimeoutError:
        result["error"] = "Website scraping timed out"
        result["company_name_fallback"] = _derive_company_name(domain)
    except Exception as e:
        result["error"] = f"Scraping failed: {str(e)[:150]}"
        result["company_name_fallback"] = _derive_company_name(domain)

    logger.info(
        "Scraped %s: pages=%d title='%s' error=%s",
        domain,
        len(result["pages"]),
        result["title"][:50],
        result["error"],
    )

    return result


def _derive_company_name(domain: str) -> str:
    """Derive a company name from domain (strip TLD, capitalize).

    Examples:
        atera.com → Atera
        xmcyber.com → Xmcyber
        my-company.io → My-Company
    """
    # Remove www prefix
    name = domain.lower().removeprefix("www.")
    # Take the part before the TLD
    parts = name.split(".")
    if len(parts) >= 2:
        name = parts[0]
    # Capitalize
    return name.capitalize()


def _extract_text(soup) -> str:
    """Extract clean text content from a BeautifulSoup document.

    Removes navigation, scripts, styles, and other non-content elements.
    Returns concatenated text limited to MAX_PAGE_TEXT chars.
    """
    # Remove unwanted tags
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()

    # Try to find main content area
    main = soup.find("main") or soup.find("article") or soup.find("div", {"role": "main"})
    if not main:
        main = soup.find("body") or soup

    # Get text with space separator
    text = main.get_text(separator=" ", strip=True)

    # Clean up whitespace
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    return text[:MAX_PAGE_TEXT]


def _find_subpage_links(soup, base_url: str) -> list[tuple[str, str]]:
    """Find links to about/product/platform pages in the homepage.

    Returns list of (path, page_type) tuples.
    """
    found = []
    seen_types = set()

    for link in soup.find_all("a", href=True):
        href = link["href"].lower()
        text = link.get_text(strip=True).lower()

        # Match by href path
        for path in SUBPAGE_PATHS:
            if path in href and "about" not in seen_types and "about" in path:
                found.append((link["href"], "about"))
                seen_types.add("about")
            elif path in href and "product" not in seen_types and any(p in path for p in ["product", "platform", "solution"]):
                found.append((link["href"], "product"))
                seen_types.add("product")

        # Match by link text
        if not seen_types.intersection({"about"}) and any(w in text for w in ["about us", "about", "company", "who we are"]):
            found.append((link["href"], "about"))
            seen_types.add("about")
        elif not seen_types.intersection({"product"}) and any(w in text for w in ["product", "platform", "solution", "features"]):
            found.append((link["href"], "product"))
            seen_types.add("product")

        if len(found) >= 3:
            break

    return found


def scrape_company_website_sync(url: str) -> dict:
    """Synchronous wrapper for scrape_company_website.

    For use in non-async contexts (Celery tasks, route handlers without async).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, scrape_company_website(url))
                return future.result(timeout=20)
        else:
            return asyncio.run(scrape_company_website(url))
    except Exception as e:
        logger.error("Sync scraper wrapper failed: %s", e)
        return {"error": str(e), "pages": {}, "title": "", "meta_description": "", "domain": ""}
