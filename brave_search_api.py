import os
import re
import json
import traceback
import requests
from typing import List, Dict, Any

from config import VERBOSE

from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

# --- Brave Search API Interaction Class ---

class BraveSearchManual:
    """Handles interactions with the Brave Search API."""
    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

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

    def search(self, query: str, count: int = 5, **kwargs) -> List[Dict[str, Any]]:
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
            response = requests.get(self.BASE_URL, headers=self.headers, params=params, timeout=10)
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