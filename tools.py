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

from config import VERBOSE

from brave_search_api import BraveSearchManual

from dotenv import load_dotenv
import os
load_dotenv()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

assert BRAVE_API_KEY, "BRAVE_API_KEY must be set in .env file"

brave_tool = BraveSearch.from_api_key(api_key=BRAVE_API_KEY, search_kwargs={"count": 5})

# --- Web Scraping Helper ---
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

# --- Combined Search and Scrape Tool (Concurrent) ---
brave_search_client = BraveSearchManual(api_key=BRAVE_API_KEY)

@tool
def search_and_scrape_web(query: str, k: int = 3) -> dict:
    """
    Searches web (Brave Search), concurrently scrapes content from top 'k' results (max 5).
    Use ONLY for recent/specific info. Be specific.
    """
    if not brave_search_client:
        raise ToolException("Brave search client not available.")
    

    if VERBOSE: print(f"--- TOOL: Searching '{query}' (k={k}) ---", file=sys.stderr)
    num_to_scrape = min(k, 5)
    if num_to_scrape <= 0:
         raise ToolException("k must be positive.")

    try:
        initial_results = brave_search_client.search(query, count=num_to_scrape)
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
    
    Args:
        query: The search query to find relevant links
        k: Number of search results to process (max 5)
        
    Returns:
        JSON string with list of links and metadata
    """
    if not brave_search_client:
        raise ToolException("Brave search client not available.")

    if VERBOSE: print(f"--- TOOL: Finding interesting links for '{query}' (k={k}) ---", file=sys.stderr)
    num_results = min(k, 5)
    if num_results <= 0:
        raise ToolException("k must be positive.")

    try:
        # First, get search results
        search_results = brave_search_client.search(query, count=num_results)
        if not search_results:
            return {"links": [], "message": "No results found."}

        all_links = []
        link_extraction_tasks = []

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