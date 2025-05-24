import os
import json
import traceback
import requests
import sys
from typing import List, Dict, Any, Optional # Added Optional
import shutil # For renaming/moving files if needed
from pathlib import Path
from bs4 import BeautifulSoup
import time
import random


from config import VERBOSE

from dotenv import load_dotenv

from langchain_core.tools import ToolException

# --- Attempt to import google_images_download ---
try:
	from google_images_download import google_images_download as gid
except ImportError:
	gid = None
	if VERBOSE:
		print("--- WARNING: `google_images_download` library not found. "
			  "The Google-based `search_images` will not be available. "
			  "Install with `pip install google_images_download` ---", file=sys.stderr)

# --- Load Environment Variables ---
load_dotenv()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

# --- Brave Search API Interaction Class ---

class BraveSearchManual:
	"""Handles interactions with the Brave Search API and optionally Google Images."""
	BASE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
	BASE_IMAGES_URL = "https://api.search.brave.com/res/v1/images/search"
	BASE_NEWS_URL  = "https://api.search.brave.com/res/v1/news/search"
	BASE_VIDEOS_URL = "https://api.search.brave.com/res/v1/videos/search"

	def __init__(self, api_key: str, verbose: bool = VERBOSE):
		if not api_key and gid is None: # Require Brave key if Google Images isn't an option for images
			raise ValueError("Brave API key is required (or google_images_download must be installed and functional).")
		self.verbose = verbose
		self.api_key = api_key # Still keep for Brave parts
		self.headers = {
			"Accept": "application/json",
			"Accept-Encoding": "gzip",
			"X-Subscription-Token": self.api_key,
			"X-Loc-State": "ES",
		}
		# Initialize Google Images downloader object if library is available
		if gid:
			self.google_image_downloader = gid.googleimagesdownload()
		else:
			self.google_image_downloader = None

	def search_web(self, query: str, count: int = 5, **kwargs) -> List[Dict[str, Any]]:
		"""
		Performs a web search using the Brave API.
		(Existing Brave implementation - unchanged)
		"""
		if not self.api_key:
			raise ToolException("Brave API key not configured for web search.")
		params = {
			"q": query,
			"count": min(count, 20),
			**kwargs
		}
		if self.verbose: print(f"--- Brave API Call Params: {params} ---")
		try:
			response = requests.get(self.BASE_WEB_URL, headers=self.headers, params=params, timeout=10)
			response.raise_for_status()
			data = response.json()
			results = data.get("web", {}).get("results", [])
			sanitized_results = [{
				"title": r.get("title"),
				"url": r.get("url"),
				"description": r.get("description")
				} for r in results if r.get("url")]
			if self.verbose: print(f"--- Brave API Returned {len(sanitized_results)} results ---")
			return sanitized_results
		except requests.exceptions.RequestException as e:
			raise ToolException(f"Brave API request failed: {e}")
		except json.JSONDecodeError as e:
			raise ToolException(f"Brave API response parsing failed: {e}")
		except Exception as e:
			print(f"--- Brave API Error: Unexpected error: {e} ---", file=sys.stderr)
			traceback.print_exc(file=sys.stderr)
			raise ToolException(f"An unexpected error occurred during Brave search: {e}")

	def search_news(self, query: str, count: int = 5, **kwargs):
		"""Searches Brave News API.
		(Existing Brave implementation - unchanged)
		"""
		if not self.api_key:
			raise ToolException("Brave API key not configured for news search.")
		params = {"q": query, "count": min(count, 20), **kwargs}
		if self.verbose:
			print(f"--- Brave NEWS API Call Params: {params} ---")
		try:
			resp = requests.get(self.BASE_NEWS_URL, headers=self.headers, params=params, timeout=10)
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

	def search_images( # Original Brave search_images method commented out
		self,
		query: str,
		save_to_dir: str | None = None,
		save_basename: str = "",
		count: int = 5,
		**kwargs,
	) -> List[Dict[str, Any]]:
		"""Searches Brave Image Search API. ... """
		if not self.api_key:
			raise ToolException("Brave API key not configured for image search.")
		assert save_to_dir if save_basename else True, "save_basename requires save_to_dir"
		params = { "q": query, "count": min(count, 20), **kwargs, }
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
				for i, r_item in enumerate(sanitized): # renamed r to r_item
					img_url = r_item.get("image_url")
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

	# def search_images(
	# 	self,
	# 	query: str,
	# 	save_to_dir: Optional[str] = None,
	# 	save_basename: str = "",
	# 	count: int = 5,
	# 	freshness: Optional[str] = None,
	# 	**kwargs,
	# ) -> List[Dict[str, Any]]:
	# 	"""Searches Google Images through the Custom Search JSON API.

	# 	Args:
	# 		query: Search keywords.
	# 		save_to_dir: If given, download full-resolution images there.
	# 		save_basename: Prefix for downloaded filenames.
	# 		count: Maximum number of images to return (Google ≤ 10 per call).
	# 		freshness: One-letter code ::
	# 			"d"/"pd"  → past 24 h   (dateRestrict=d1)
	# 			"w"/"pw"  → past 7 d    (dateRestrict=d7)
	# 			"m"/"pm"  → past 30 d   (dateRestrict=d30)
	# 			"y"/"py"  → past 365 d  (dateRestrict=d365)
	# 		**kwargs: Ignored (kept for signature compatibility).

	# 	Returns:
	# 		List[dict] with keys
	# 		title, page_url, image_url, thumbnail_url, source, image_path.

	# 	Raises:
	# 		ToolException on HTTP, quota, or parsing failures.
	# 	"""
	# 	from langchain_core.tools import ToolException  # local import keeps top clean
	# 	from pathlib import Path
	# 	import os
	# 	import random
	# 	import time
	# 	import requests

	# 	api_key = os.getenv("GOOGLE_API_KEY")
	# 	cse_id  = os.getenv("GOOGLE_CSE_ID")
	# 	if not (api_key and cse_id):
	# 		raise ToolException(
	# 			"GOOGLE_API_KEY and/or GOOGLE_CSE_ID environment variables not set."
	# 		)

	# 	# ── Build query parameters ────────────────────────────────────
	# 	google_endpoint = "https://www.googleapis.com/customsearch/v1"
	# 	params = {
	# 		"key": api_key,
	# 		"cx":  cse_id,
	# 		"q":   query,
	# 		"searchType": "image",
	# 		"num": min(count, 10),           # Google caps at 10
	# 		"fields": (
	# 			"items(link,displayLink,title,"
	# 			"image/contextLink,image/thumbnailLink)"
	# 		),
	# 	}
	# 	freshness_map = {"d": "d1", "pd": "d1",
	# 					 "w": "d7", "pw": "d7",
	# 					 "m": "d30", "pm": "d30",
	# 					 "y": "d365", "py": "d365"}
	# 	if freshness and freshness.lower() in freshness_map:
	# 		params["dateRestrict"] = freshness_map[freshness.lower()]

	# 	if self.verbose:
	# 		print(f"--- Google API params: {params}")

	# 	# ── Call API ──────────────────────────────────────────────────
	# 	try:
	# 		r = requests.get(google_endpoint, params=params, timeout=15)
	# 		r.raise_for_status()
	# 		data = r.json()
	# 	except requests.exceptions.RequestException as e:
	# 		raise ToolException(f"Google request failed: {e}") from e
	# 	except (ValueError, KeyError) as e:    # JSON or missing fields
	# 		raise ToolException(f"Bad JSON from Google: {e}") from e

	# 	items = data.get("items", [])
	# 	if not items:
	# 		raise ToolException("Google returned no image results.")

	# 	# ── Build result list ─────────────────────────────────────────
	# 	results: List[Dict[str, Any]] = []
	# 	for it in items[:count]:
	# 		results.append(
	# 			{
	# 				"title":          it.get("title") or query,
	# 				"page_url":       it.get("image", {}).get("contextLink"),
	# 				"image_url":      it.get("link"),
	# 				"thumbnail_url":  it.get("image", {}).get("thumbnailLink"),
	# 				"source":         it.get("displayLink", "google.com"),
	# 				"image_path":     None,      # filled if we download
	# 			}
	# 		)

	# 	# ── Optional download of originals ───────────────────────────
	# 	if save_to_dir:
	# 		save_dir = Path(save_to_dir).expanduser()
	# 		save_dir.mkdir(parents=True, exist_ok=True)

	# 		for idx, item in enumerate(results):
	# 			url = item["image_url"]
	# 			if not url:
	# 				continue
	# 			filename = f"{save_basename or 'img'}_{idx}.jpg"
	# 			dest = save_dir / filename

	# 			# polite throttle to avoid hitting origin sites too hard
	# 			time.sleep(random.uniform(0.4, 1.0))
	# 			try:
	# 				self._download_img_from_url(url, str(dest))
	# 				item["image_path"] = str(dest)
	# 			except Exception as e:
	# 				if self.verbose:
	# 					print(f"--- Download failed for {url}: {e}")

	# 	if self.verbose:
	# 		print(f"--- Returning {len(results)} images")
	# 	return results
		
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

