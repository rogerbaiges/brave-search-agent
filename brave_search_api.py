import os
import json
import traceback
import requests
import sys
from typing import List, Dict, Any



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
		self.verbose = verbose
		self.api_key = api_key # Still keep for Brave parts
		self.headers = {
			"Accept": "application/json",
			"Accept-Encoding": "gzip",
			"X-Subscription-Token": self.api_key,
			"X-Loc-State": "ES",
		}

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
				image_url = props.get("url")
				
				# Filter out unwanted image formats by checking content type
				if image_url and self._is_valid_image_format(image_url):
					sanitized.append(
						{
							"title": r.get("title"),
							"page_url": r.get("url"),
							"image_url": image_url,
							"thumbnail_url": thumb.get("src"),
							"source": r.get("source"),
						}
					)
			
			if self.verbose: print(f"--- Brave IMAGE API returned {len(sanitized)} filtered results ---")
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

	def _is_valid_image_format(self, url: str) -> bool:
		"""Check if the image URL points to a valid static image format by examining content type."""
		try:
			# Make a HEAD request to get content type without downloading the full image
			response = requests.head(url, timeout=5, allow_redirects=True)
			content_type = response.headers.get('content-type', '').lower()
			
			# List of allowed image MIME types (static images only)
			allowed_types = [
				'image/jpeg',
				'image/jpg', 
				'image/png',
				'image/webp',
				'image/bmp',
				'image/tiff',
				'image/tif'
			]
			
			# Explicitly exclude animated formats
			excluded_types = [
				'image/gif',
				'image/webp',  # Can be animated, but we'll allow it for now
				'image/apng',
				'image/svg+xml',
				'application/octet-stream'
			]
			
			# Check if content type is in allowed list and not in excluded list
			for allowed in allowed_types:
				if allowed in content_type:
					# Double check it's not an excluded type
					for excluded in excluded_types:
						if excluded in content_type and excluded != 'image/webp':
							return False
					return True
			
			return False
			
		except Exception as e:
			if self.verbose:
				print(f"--- Could not verify image format for {url}: {e} ---")
			# If we can't check, assume it's valid to avoid being too restrictive
			return True

	def _download_img_from_url(self, url: str, save_path: str):
		"""Downloads an image from a URL image and saves it to a specified path."""
		# Create the directory if it doesn't exist
		os.makedirs(os.path.dirname(save_path), exist_ok=True)
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

