import os
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
    BASE_IMAGES_URL = "https://api.search.brave.com/res/v1/images/search"
    BASE_NEWS_URL  = "https://api.search.brave.com/res/v1/news/search"
    BASE_VIDEOS_URL = "https://api.search.brave.com/res/v1/videos/search"

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
        
    def search_news(self, query: str, count: int = 5, **kwargs):
        """Searches Brave News API.
        Args:
            query: Search string.
            count: Number of results requested (≤ 20).
            **kwargs: Other Brave API parameters (``search_lang``, ``country`` …).
        Returns:
            A list of news-result dictionaries with keys:
            ``title``, ``url``, ``description``.
        """
        params = {"q": query, "count": min(count, 20), **kwargs}
        if self.verbose:
            print(f"--- Brave NEWS API Call Params: {params} ---")

        try:
            resp = requests.get(self.BASE_NEWS_URL,
                                headers=self.headers,
                                params=params,
                                timeout=10)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])

            sanitized = [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "description": r.get("description"),
                }
                for r in results if r.get("url")
            ]
            if self.verbose:
                print(f"--- Brave NEWS API returned {len(sanitized)} results ---")
            return sanitized

        except requests.exceptions.RequestException as e:
            raise ToolException(f"Brave News API request failed: {e}") from e
        
    def search_images(
        self,
        query: str,
        save_to_dir: str | None = None,
        save_basename: str = "",
        count: int = 5,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Searches Brave Image Search API.

        Args:
            query: Search string.
            count: Number of results requested (≤ 20).
            save_to_dir: Path to save images (if provided).
            **kwargs: Other Brave API parameters (``search_lang``, ``country`` …).

        Returns:
            A list of image-result dictionaries with keys:
            ``title``, ``page_url``, ``image_url``, ``thumbnail_url``, ``source``.

        Raises:
            ToolException: On network / API errors.
        """
        assert save_to_dir if save_basename else True, "save_basename requires save_to_dir"

        params = {
            "q": query,
            "count": min(count, 20),
            **kwargs,
        }

        if self.verbose: print(f"--- Brave IMAGE API Call Params: {params} ---")

        try:
            response = requests.get(self.BASE_IMAGES_URL, headers=self.headers, params=params, timeout=10)
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

            if save_to_dir:
                for i, r in enumerate(sanitized):
                    img_url = r.get("image_url")
                    if img_url:
                        filename = f"{save_basename if save_basename else 'img'}_{i}.jpg"
                        file_path = os.path.join(save_to_dir, filename)
                        self._download_img_from_url(img_url, file_path)

            return sanitized

        except requests.exceptions.RequestException as e:
            raise ToolException(f"Brave Image API request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise ToolException(f"Brave Image API response parsing failed: {e}") from e
        except Exception as e:
            raise ToolException(f"Unexpected error during Brave image search: {e}") from e
        
    def _download_img_from_url(self, url: str, save_path: str):
        """Downloads an image from a URL image and saves it to a specified path."""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            if self.verbose: print(f"--- Image saved to {save_path} ---")
        except requests.exceptions.RequestException as e:
            print(f"--- Image download failed: {e} ---")
            raise ToolException(f"Image download failed: {e}")
        except Exception as e:
            print(f"--- Unexpected error during image download: {e} ---")
            raise ToolException(f"Unexpected error during image download: {e}")
        
#     def search_videos(
#         self,
#         query: str,
#         save_to_dir: str | None = None,
#         save_basename: str = "",
#         count: int = 5,
#         **kwargs,
#     ) -> List[Dict[str, Any]]:
#         """
#         Searches Brave Video Search API, returns video metadata, and
#         optionally saves it to a JSON file.

#         Args:
#             query: Search string.
#             save_to_dir: Directory to save the metadata JSON (if provided).
#             save_basename: Base filename for the saved JSON (no extension).
#             count: Number of results requested (≤ 50).
#             **kwargs: Other Brave API parameters (e.g. country, search_lang).

#         Returns:
#             A list of video-result dicts.
#         """
#         params = {
#             "q": query,
#             "count": min(count, 50),
#             **kwargs,
#         }
#         if self.verbose:
#             print(f"--- Brave VIDEO API Call Params: {params} ---")

#         resp = requests.get(self.BASE_VIDEOS_URL, headers=self.headers, params=params, timeout=10)
#         resp.raise_for_status()
#         data = resp.json()

#         results = data.get("results", [])
#         sanitized = []
#         for r in results:
#             thumb      = r.get("thumbnail", {})
#             video_meta = r.get("video", {})
#             sanitized.append({
#                 "title":                 r.get("title"),
#                 "page_url":              r.get("url"),
#                 "description":           r.get("description"),
#                 "age":                   r.get("age"),
#                 "thumbnail_url":         thumb.get("src"),
#                 "duration":              video_meta.get("duration"),
#                 "views":                 video_meta.get("views"),
#                 "creator":               video_meta.get("creator"),
#                 "publisher":             video_meta.get("publisher"),
#                 "requires_subscription": video_meta.get("requires_subscription"),
#                 "tags":                  video_meta.get("tags"),
#                 "meta_url":              r.get("meta_url"),
#             })

#         if self.verbose:
#             print(f"--- Brave VIDEO API returned {len(sanitized)} results ---")

#         if save_to_dir:
#             os.makedirs(save_to_dir, exist_ok=True)
#             fname = f"{save_basename or 'videos'}_metadata.json"
#             path  = os.path.join(save_to_dir, fname)
#             with open(path, "w", encoding="utf-8") as f:
#                 json.dump(sanitized, f, ensure_ascii=False, indent=2)
#             if self.verbose:
#                 print(f"--- Video metadata saved to {path} ---")

#         return sanitized
    
#     def fetch_video_metadata(self, meta_url: str) -> Dict[str, Any]:
#         """
#         Fetches the Brave API's JSON metadata for a video, which often
#         includes embed HTML or direct stream URLs.

#         Args:
#             meta_url: The URL returned in "meta_url" from search_videos.

#         Returns:
#             Parsed JSON metadata as a dict.
#         """
#         try:
#             resp = requests.get(meta_url, headers=self.headers, timeout=10)
#             resp.raise_for_status()
#             return resp.json()
#         except requests.exceptions.RequestException as e:
#             raise ToolException(f"Failed to fetch video metadata: {e}") from e

#     def load_videos_metadata(self, file_path: str) -> List[Dict[str, Any]]:
#         """
#         Loads previously saved video metadata from a JSON file.

#         Args:
#             file_path: Path to the JSON file created by `search_videos(..., save_to_dir=...)`.

#         Returns:
#             The list of video-result dicts.
#         """
#         try:
#             with open(file_path, "r", encoding="utf-8") as f:
#                 return json.load(f)
#         except Exception as e:
#             raise ToolException(f"Failed to load video metadata from {file_path}: {e}") from e
        
#     def visualize_selected_videos(
#         self,
#         metadata_path: str,
#         selected_indexes: List[int]
#     ) -> str:
#         """
#         Loads video metadata JSON from disk, filters by selected_indexes,
#         fetches any embed HTML if available, and returns an HTML snippet
#         you can inject into your chatbot UI to render the videos.

#         Args:
#             metadata_path: Path to the JSON file created by search_videos(..., save_to_dir=...).
#             selected_indexes: List of integer indexes into that metadata list.

#         Returns:
#             A single HTML string containing either <iframe> embeds (when available)
#             or thumbnail-linked blocks for each selected video.
#         """
#         import json
#         from langchain_core.tools import ToolException

#         # Load the saved metadata
#         with open(metadata_path, "r", encoding="utf-8") as f:
#             all_videos = json.load(f)

#         html_blocks: List[str] = []
#         for idx in selected_indexes:
#             if idx < 0 or idx >= len(all_videos):
#                 continue
#             vid = all_videos[idx]

#             # Try to fetch embed HTML from the Brave metadata endpoint
#             embed_html = None
#             try:
#                 meta = self.fetch_video_metadata(vid["meta_url"])
#                 embed_html = meta.get("embed", {}).get("html")
#             except ToolException:
#                 pass

#             if embed_html:
#                 html_blocks.append(embed_html)
#             else:
#                 # Fallback to a thumbnail + link block
#                 html_blocks.append(
#                     f'''<div class="video-entry">
#   <a href="{vid["page_url"]}" target="_blank">
#     <img src="{vid["thumbnail_url"]}" alt="{vid["title"]}" />
#   </a>
#   <p>{vid["title"]}</p>
# </div>'''
#                 )

#         return "\n".join(html_blocks)

