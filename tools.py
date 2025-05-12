import requests
import re
import json
import sys
import concurrent.futures
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

from langchain.tools import tool
from langchain_core.tools import ToolException
from langchain_community.tools import BraveSearch

from config import VERBOSE, IMAGES_DIR, SCREENSHOTS_DIR

from brave_search_api import BraveSearchManual

from playwright.sync_api import sync_playwright, Route, Request

from dotenv import load_dotenv
import os
load_dotenv()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

assert BRAVE_API_KEY, "BRAVE_API_KEY must be set in .env file"

# --- Manual Brave Search Client ---
_brave_search_client = BraveSearchManual(api_key=BRAVE_API_KEY)

# --- LangChain Brave Search Tool (with modification to save images) ---
_brave_search_tool = BraveSearch.from_api_key(
    api_key=BRAVE_API_KEY,
    search_kwargs={"count": 5}
)

@tool
def web_search(query: str) -> str:
    """
    Searches the web using Brave Search API
    Returns 5 results with a short description of their content.
    Useful for obtaining a short description of a topic or finding relevant content.

    Parameters:
        query (str): The search query.

    Returns:
        str: JSON string with list of search results.    
    """
    # Original docstring from langchain implementation:
    # """
    # a search engine. useful for when you need to answer questions about current events.
    # input should be a search query.
    # """
    result_json = _brave_search_tool.run(query)

    try:
        _brave_search_client.search_images(
            query=query,
            save_to_dir=IMAGES_DIR,
            count=5,
            save_basename=f"web_search_{query}" # brave_search_{query}
        )
    except Exception:
        pass
    return result_json

# --- Web Scraping Tool ---
def _scrape_and_extract_text(url: str, timeout: int = 10, max_chars: int = 4000) -> Optional[str]:
    """Fetches and extracts text content from a URL, returning up to max_chars or None."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=False)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type:
            return None

        soup = BeautifulSoup(response.content, 'html.parser')
        for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "noscript", "button", "input"]):
            element.decompose()

        main_content = soup.find('main') or soup.find('article') or \
                       soup.find('div', attrs={'role': 'main'}) or \
                       soup.find('div', id='content') or \
                       soup.find('div', class_='content') or soup.body
        text = main_content.get_text(separator=' ', strip=True) if main_content else ""
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]

    except requests.exceptions.Timeout: return None
    except requests.exceptions.RequestException: return None
    except Exception as e:
        if VERBOSE: print(f"--- Scraping Error (Parsing/Other): {url} - {e} ---", file=sys.stderr)
        return None

@tool
def extended_web_search(query: str, k: int = 3) -> dict:
    """
    Searches the web using Brave Search API and provides the full content from top 'k' results (max 5).
    This is useful for obtaining full context about something or detailed information on a topic. 
    Use ONLY when you believe that the short description of a web result provided by the basic web search tool won't be enough to answer the user's question properly.
    Use ALWAYS when the already provided content of the web results obtained by the basic web search is not enough to directly answer the user's question properly.

    Parameters:
        query: The search query to find relevant content
        k: Number of search results to scrape (max 5)

    Returns:
        JSON string with list of scraped results.
    """
    if not _brave_search_client:
        raise ToolException("Brave search client not available.")
    

    if VERBOSE: print(f"--- TOOL: Searching '{query}' (k={k}) ---", file=sys.stderr)
    num_to_scrape = min(k, 5)
    if num_to_scrape <= 0:
         raise ToolException("k must be positive.")

    try:
        initial_results = _brave_search_client.search_web(query, count=num_to_scrape)
        _brave_search_client.search_images(query, save_to_dir=IMAGES_DIR, count=num_to_scrape, save_basename=f"full_web_search_{query}") # Save images to IMAGES_DIR

        urls_to_scrape = [r.get("url") for r in initial_results if r.get("url")]
        if not urls_to_scrape: return {"results": []}

        if VERBOSE: print(f"--- TOOL: Starting concurrent scraping for {len(urls_to_scrape)} URLs... ---", file=sys.stderr)
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_to_scrape) as executor:
            future_to_url = {executor.submit(_scrape_and_extract_text, url): url for url in urls_to_scrape}
            scrape_results_map = {}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    scrape_results_map[url] = future.result()
                except Exception as exc:
                    if VERBOSE: print(f'--- TOOL: Scraping thread exception for {url}: {exc} ---', file=sys.stderr)
                    scrape_results_map[url] = None

        final_scraped_results = [
            {"url": url, "content": scrape_results_map.get(url)}
            for url in urls_to_scrape
        ]
        if VERBOSE: print(f"--- TOOL: Returning {len(final_scraped_results)} results ---", file=sys.stderr)
        return {"results": final_scraped_results}

    except ToolException: raise
    except Exception as e:
        if VERBOSE: print(f"--- TOOL ERROR (Orchestration): {e} ---", file=sys.stderr)
        raise ToolException(f"Unexpected error in search/scrape tool: {e}")
    

# --- Link Extraction Tool ---
def _extract_links_and_metadata(url: str, timeout: int = 10) -> Optional[List[Dict]]:
    """Extracts links and metadata from a URL, returning a list of dictionaries with link information."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type:
            return []

        soup = BeautifulSoup(response.content, 'html.parser')
        extracted_links = []
        
        # Find all anchor tags with href attributes
        for anchor in soup.find_all('a', href=True):
            href = anchor.get('href', '').strip()
            
            # Skip empty links, javascript links, and anchors
            if not href or href.startswith(('javascript:', '#')):
                continue
                
            # Handle relative URLs
            if href.startswith('/'):
                from urllib.parse import urlparse
                base_url = "{0.scheme}://{0.netloc}".format(urlparse(url))
                href = base_url + href
            elif not href.startswith(('http://', 'https://')):
                # Skip links that aren't http/https and can't be converted to absolute
                continue
                
            # Extract title and description if available
            title = anchor.get_text(strip=True)
            title = title if title else "Link from " + url
            
            # Get a short description from the parent paragraph or div if available
            description = ""
            parent = anchor.find_parent(['p', 'div', 'li'])
            if parent:
                description = parent.get_text(strip=True)
                # Limit description length and remove the link text itself to avoid redundancy
                if description:
                    # Remove the link text from description
                    description = description.replace(title, "", 1).strip()
                    if len(description) > 200:
                        description = description[:197] + "..."
            
            extracted_links.append({
                "url": href,
                "title": title[:100],  # Limit title length
                "description": description
            })
            
        # Return only unique URLs
        seen_urls = set()
        unique_links = []
        for link in extracted_links:
            if link["url"] not in seen_urls:
                seen_urls.add(link["url"])
                unique_links.append(link)
        
        return unique_links[:10]  
    except requests.exceptions.Timeout:
        if VERBOSE: print(f"--- Link Extraction Timeout: {url} ---", file=sys.stderr)
        return []
    except requests.exceptions.RequestException as e:
        if VERBOSE: print(f"--- Link Extraction RequestException: {url} - {e} ---", file=sys.stderr)
        return []
    except Exception as e:
        if VERBOSE: print(f"--- Link Extraction Error: {url} - {e} ---", file=sys.stderr)
        return []


@tool
def find_interesting_links(query: str, k: int = 5) -> str:
    """
    Finds interesting and relevant links related to a query. 
    Searches the web and extracts links from search results.
    Use for finding resources, references, or interesting related content.
    VERY IMPORTANT: Always use this tool when the user might benefit from having links for further reading.
    
    Parameters:
        query: The search query to find relevant links
        k: Number of search results to process (max 5)
        
    Returns:
        JSON string with list of links and metadata
    """
    if not _brave_search_client:
        raise ToolException("Brave search client not available.")

    if VERBOSE: print(f"--- TOOL: Finding interesting links for '{query}' (k={k}) ---", file=sys.stderr)
    num_results = min(k, 5)
    if num_results <= 0:
        raise ToolException("k must be positive.")

    try:
        # First, get search results
        search_results = _brave_search_client.search_web(query, count=num_results)
        if not search_results:
            return {"links": [], "message": "No results found."}

        all_links = []

        # Process direct search results (these are guaranteed to be relevant)
        for result in search_results:
            if not result.get("url"):
                continue
                
            # Add the search result itself as a link
            all_links.append({
                "url": result.get("url"),
                "title": result.get("title", ""),
                "description": result.get("description", ""),
                "source": "search_result"
            })
        
        # Then extract additional links from the top result pages (for deeper exploration)
        urls_to_extract = [r.get("url") for r in search_results[:5] if r.get("url")]
        
        if urls_to_extract:
            if VERBOSE: print(f"--- TOOL: Extracting links from {len(urls_to_extract)} top pages... ---", file=sys.stderr)
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(urls_to_extract)) as executor:
                futures = {executor.submit(_extract_links_and_metadata, url): url for url in urls_to_extract}
                
                for future in concurrent.futures.as_completed(futures):
                    url = futures[future]
                    try:
                        links = future.result()
                        if links:
                            # Add source information to each link
                            for link in links:
                                link["source"] = f"extracted_from_{url}"
                            all_links.extend(links[:10])  # Limit to top 5 links per page
                    except Exception as e:
                        if VERBOSE: print(f"--- TOOL: Link extraction error for {url}: {e} ---", file=sys.stderr)

        # Deduplicate links by URL
        seen_urls = set()
        unique_links = []
        for link in all_links:
            if link["url"] not in seen_urls:
                seen_urls.add(link["url"])
                unique_links.append(link)
        
        # Limit total number of links to return
        final_links = unique_links[:10]  # Return at most 10 unique links
        
        if VERBOSE: print(f"--- TOOL: Returning {len(final_links)} interesting links ---", file=sys.stderr)
        return json.dumps({
            "links": final_links,
            "message": f"Found {len(final_links)} interesting links related to '{query}'."
        })

    except ToolException: raise
    except Exception as e:
        print(f"--- TOOL ERROR (Link Finding): {e} ---", file=sys.stderr)
        raise ToolException(f"Unexpected error in find_interesting_links tool: {e}")

# --- Screenshot Tool ---
def web_screenshot(
    url: str,
    output_path: str = "screenshot.png",
    full_page: bool = False,
) -> None:
    """Capture a screenshot of a web page while programmatically hiding most cookie-, banner-,
    modal-, and CAPTCHA overlays.

    Parameters:
        url (str): The URL to visit.
        output_path (str): File path where the screenshot image will be written.
        full_page (bool, optional): If ``True`` the entire scrolling page is captured;
            otherwise only the visible viewport is saved.  Defaults to ``False``.

    Raises:
        playwright.sync_api.Error: Propagates any unhandled Playwright browser errors.

    Example:
        >>> take_screenshot("https://example.com", "example.png", full_page=True)
    """
    # CSS rules that aggressively hide elements whose id/class names *commonly* appear
    # in cookie banners, GDPR pop-ups, subscription modals, overlays, and reCAPTCHA iframes.
    _HIDE_OVERLAYS_CSS = """
    /* Cookie / consent banners */
    [id*="cookie" i],
    [class*="cookie" i],
    [id*="consent" i],
    [class*="consent" i],
    [id*="gdpr" i],
    [class*="gdpr" i],

    /* Generic banners, overlays, modals, dialogs */
    [id*="banner" i],
    [class*="banner" i],
    [id*="overlay" i],
    [class*="overlay" i],
    [id*="modal" i],
    [class*="modal" i],
    div[role="dialog"][aria-modal="true"],

    /* “Subscribe to our newsletter”-style pop-ups */
    [id*="subscribe" i],
    [class*="subscribe" i],

    /* reCAPTCHA & similar widgets */
    iframe[src*="recaptcha"],
    iframe[src*="captcha"],
    #g-recaptcha,
    .grecaptcha-badge
    {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }
    """
    def _block_captcha(route: Route, request: Request) -> None:  # noqa: D401
        """Abort obvious CAPTCHA and tracker requests to reduce overlay risk."""
        url_low = request.url.lower()
        if "recaptcha" in url_low or "google.com/recaptcha" in url_low:
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",  # less bot fingerprinting
            ],
        )

        # “Stealth” context settings that look like a typical desktop Chrome session
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            device_scale_factor=1.0,
            locale="en-US",
        )

        # Block the most frequent CAPTCHA network calls
        context.route("**/*recaptcha*/**", _block_captcha)

        page = context.new_page()

        # Fast but reliable load strategy: DOM content is enough; networkidle is too strict.
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        # Hide overlays before the screenshot is taken
        page.add_style_tag(content=_HIDE_OVERLAYS_CSS)

        # A short delay ensures the CSS has been applied and late overlays are injected.
        page.wait_for_timeout(500)

        page.screenshot(path=str(output_path), full_page=full_page)

        browser.close()

# --- Brave Image Search Tool ---
@tool
def image_search(query: str, k: int = 5) -> dict:
    """
    Search Brave Image API and return up to *k* images.

    Args:
        query: Image search query.
        k: Desired number of image results (max 20).

    Returns:
        A ``dict`` with key ``images`` containing a list of image-result
        dictionaries ``{title, page_url, image_url, thumbnail_url, source}``.
    """
    if not _brave_search_client:
        raise ToolException("Brave search client not available.")

    if k <= 0:
        raise ToolException("k must be positive.")

    try:
        images = _brave_search_client.search_images(query, count=k)
        return {"images": images}
    except ToolException:
        raise
    except Exception as e:
        raise ToolException(f"Unexpected error in search_images tool: {e}")

# --- Brave News Search Tool ---
@tool
def news_search(query: str, k: int = 5, freshness: Optional[str] = None) -> dict:
    """
    Searches Brave News API and returns up to *k* news articles.
    DO NOT use this tool for regular information that can be easily found with a web search. Instead, use it ONLY for current events or news-related queries.
    Use the ``freshness`` parameter to filter results by time period if this is convenient to properly answer the user's question.

    Parameters:
        query (str): News search query.
        k (int): Number of news results to return (max 20).
        freshness (str, optional): Freshness filter for news articles.
            Options:
                - "pd": articles from the last day (24 hours)
                - "pw": articles from the last week (7 days)
                - "pm": articles from the last month (31 days)
                - "py": articles from the last year (365 days)
                - None: articles from any time period (default)

    Returns:
        List of news-result dictionaries with keys:
            ``title``, ``url``, ``description``
    """
    if not _brave_search_client:
        raise ToolException("Brave search client not available.")
    if k <= 0:
        raise ToolException("k must be positive.")

    try:
        news_items = _brave_search_client.search_news(query, count=k, freshness=freshness)
        _brave_search_client.search_images(query, save_to_dir=IMAGES_DIR, count=k, save_basename=f"news_search_{query}") # Save images to IMAGES_DIR
        return {"news": news_items}
    except ToolException:
        raise
    except Exception as e:
        raise ToolException(f"Unexpected error in search_news tool: {e}")
