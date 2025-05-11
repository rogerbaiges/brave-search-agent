import os
import re
import json
import traceback
import requests
from typing import List, Dict, Any

from config import VERBOSE

from dotenv import load_dotenv

from langchain_core.tools import ToolException

# --- Load Environment Variables ---
load_dotenv()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

# --- Brave Search API Interaction Class ---

class BraveSearchManual:
    """Handles interactions with the Brave Search API."""
    BASE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
    BASE_IMAGE_URL = "https://api.search.brave.com/res/v1/images/search"
    BASE_NEWS_URL  = "https://api.search.brave.com/res/v1/news/search"

    def __init__(self, api_key: str, verbose: bool = VERBOSE):
        if not api_key:
            raise ValueError("Brave API key is required.")
        self.verbose = verbose
        self.api_key = api_key
        self.headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip", # Added for potentially better performance
            "X-Subscription-Token": self.api_key
        }

    def search_web(self, query: str, count: int = 5, **kwargs) -> List[Dict[str, Any]]:
        """
        Performs a web search using the Brave API.

        Args:
            query: The search query string.
            count: Number of results to request (default 5, max 20).
            **kwargs: Additional valid Brave API query parameters (e.g., country, search_lang).

        Returns:
            A list of result dictionaries, typically including 'url', 'title', 'description'.
            Returns an empty list if an error occurs.
        """
        params = {
            "q": query,
            "count": min(count, 20), # Respect API max limit
            **kwargs
        }
        if self.verbose: print(f"--- Brave API Call Params: {params} ---")
        try:
            response = requests.get(self.BASE_WEB_URL, headers=self.headers, params=params, timeout=10)
            response.raise_for_status() # Check for HTTP errors
            data = response.json()
            # Extract relevant web results (structure might vary slightly)
            results = data.get("web", {}).get("results", [])
            # Sanitize results slightly
            sanitized_results = [{
                "title": r.get("title"),
                "url": r.get("url"),
                "description": r.get("description")
                } for r in results if r.get("url")] # Ensure URL exists
            if self.verbose: print(f"--- Brave API Returned {len(sanitized_results)} results ---")
            return sanitized_results
        except requests.exceptions.RequestException as e:
            print(f"--- Brave API Error: Request failed: {e} ---")
            # Raise ToolException so Langchain AgentExecutor can potentially handle it
            raise ToolException(f"Brave API request failed: {e}")
        except json.JSONDecodeError as e:
            print(f"--- Brave API Error: Failed to parse response: {e} ---")
            raise ToolException(f"Brave API response parsing failed: {e}")
        except Exception as e:
            print(f"--- Brave API Error: Unexpected error: {e} ---")
            print(traceback.format_exc())
            raise ToolException(f"An unexpected error occurred during Brave search: {e}")
        
    def search_images(
        self,
        query: str,
        count: int = 5,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Searches Brave Image Search API.

        Args:
            query: Search string.
            count: Number of results requested (≤ 20).
            **kwargs: Other Brave API parameters (``search_lang``, ``country`` …).

        Returns:
            A list of image-result dictionaries with keys:
            ``title``, ``page_url``, ``image_url``, ``thumbnail_url``, ``source``.

        Raises:
            ToolException: On network / API errors.
        """
        params = {
            "q": query,
            "count": min(count, 20),
            **kwargs,
        }

        if self.verbose: print(f"--- Brave IMAGE API Call Params: {params} ---")

        try:
            response = requests.get(self.BASE_IMAGE_URL, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            sanitized = []
            for r in results:
                props = r.get("properties", {})
                thumb = r.get("thumbnail", {})
                sanitized.append(
                    {
                        "title": r.get("title"),
                        "page_url": r.get("url"),
                        "image_url": props.get("url"),
                        "thumbnail_url": thumb.get("src"),
                        "source": r.get("source"),
                    }
                )
            if self.verbose: print(f"--- Brave IMAGE API returned {len(sanitized)} results ---")

            return sanitized

        except requests.exceptions.RequestException as e:
            raise ToolException(f"Brave Image API request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise ToolException(f"Brave Image API response parsing failed: {e}") from e
        except Exception as e:
            raise ToolException(f"Unexpected error during Brave image search: {e}") from e
        
    def search_news(self, query: str, count: int = 5, **kwargs) -> List[Dict[str, Any]]:
        """
        Performs a news search using Brave’s News endpoint.

        Args:
            query: The search query string.
            count: Number of news items requested (default 5, max 20).
            **kwargs: Additional Brave API query parameters (e.g., country, search_lang).

        Returns:
            A list of dictionaries with keys: ``title``, ``url``, ``description``, ``published``.
        """
        params = {
            "q": query,
            "count": min(count, 20),
            **kwargs,
        }
        if self.verbose:
            print(f"--- Brave NEWS API Call Params: {params} ---")

        try:
            resp = requests.get(self.BASE_NEWS_URL, headers=self.headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("news", {}).get("results", [])
            sanitized = [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "description": r.get("description"),
                    "published": r.get("published_at") or r.get("date") or r.get("published"),
                }
                for r in results
                if r.get("url")
            ]

            if self.verbose:
                print(f"--- Brave NEWS API returned {len(sanitized)} results ---")

            return sanitized

        except requests.exceptions.RequestException as e:
            raise ToolException(f"Brave News API request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise ToolException(f"Brave News API response parsing failed: {e}") from e
        except Exception as e:
            raise ToolException(f"Unexpected error during Brave news search: {e}") from e
