import os
import json
import traceback
import requests
import sys
from typing import List, Dict, Any
# mimetypes and shutil are not used in the final production code logic, only in tests or prior debug.
# re and base64 are used for Brave proxy URL decoding.
import re
import base64


from config import VERBOSE # Keep VERBOSE import if other parts of the system might still use it or if it's meant to be configurable globally.

from dotenv import load_dotenv

from langchain_core.tools import ToolException

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
		self.api_key = api_key
		self.headers = {
			"Accept": "application/json",
			"Accept-Encoding": "gzip",
			"X-Subscription-Token": self.api_key,
			"X-Loc-State": "ES",
		}

	def search_web(self, query: str, count: int = 5, **kwargs) -> List[Dict[str, Any]]:
		"""
		Performs a web search using the Brave API.
		"""
		if not self.api_key:
			raise ToolException("Brave API key not configured for web search.")
		params = {
			"q": query,
			"count": min(count, 20),
			**kwargs
		}
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
		"""
		if not self.api_key:
			raise ToolException("Brave API key not configured for news search.")
		params = {"q": query, "count": min(count, 20), **kwargs}
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
		"""Searches Brave Image Search API. Downloads valid images if save_to_dir is provided."""
		if not self.api_key:
			raise ToolException("Brave API key not configured for image search.")
		assert save_to_dir if save_basename else True, "save_basename requires save_to_dir"
		params = { "q": query, "count": min(count, 20), **kwargs, }
		try:
			response = requests.get(self.BASE_IMAGES_URL, headers=self.headers, params=params, timeout=10)
			response.raise_for_status()
			data = response.json()
			
			results = data.get("results", [])

			sanitized = []
			for i, r in enumerate(results):
				props = r.get("properties", {})
				thumb = r.get("thumbnail", {})
				image_url = props.get("url")
				
				if image_url:
					if self._is_valid_image_format(image_url):
						sanitized.append(
							{
								"title": r.get("title"),
								"page_url": r.get("url"),
								"image_url": image_url,
								"thumbnail_url": thumb.get("src"),
								"source": r.get("source"),
							}
						)
				
			if save_to_dir:
				for i, r_item in enumerate(sanitized):
					img_url = r_item.get("image_url")
					if img_url:
						ext = self._get_extension_from_brave_proxy_url(img_url)
						if not ext:
							# Fallback to extension from the immediate URL if proxy decoding failed or not a proxy URL
							_, ext = os.path.splitext(img_url.split('?')[0]) 
						
						# Ensure extension is valid and starts with a dot
						if not ext or not ext.startswith('.'):
							ext = ".jpg" # Default to .jpg if no valid extension found
						
						filename = f"{save_basename if save_basename else 'img'}_{i}{ext}"
						file_path = os.path.join(save_to_dir, filename)
						try:
							self._download_img_from_url(img_url, file_path)
						except ToolException:
							pass # Silently fail download if it's not critical
			return sanitized
		except requests.exceptions.RequestException as e:
			raise ToolException(f"Brave Image API request failed: {e}") from e
		except json.JSONDecodeError as e:
			raise ToolException(f"Brave Image API response parsing failed: {e}") from e
		except Exception as e:
			raise ToolException(f"Unexpected error during Brave image search: {e}") from e

	def _get_extension_from_brave_proxy_url(self, brave_proxy_url: str) -> str:
		"""
		Extracts a file extension from a Brave proxy image URL by decoding its base64-encoded original URL.
		This version correctly handles the single base64 string split by '/' characters in the proxy URL,
		normalizing to standard Base64 alphabet and applying robust padding.
		"""
		try:
			# The base64 part is usually after 'g:ce/' and can contain '/' separators
			match = re.search(r'g:ce/(.*)$', brave_proxy_url)
			if match:
				# Get the full base64 string, removing path separators that Brave adds
				base64_string_raw = match.group(1).replace('/', '')

				# Normalize URL-safe base64 characters to standard base64 characters.
				# This handles cases where + is replaced with - and / with _ in URL-safe encoding.
				base64_for_decoding = base64_string_raw.replace('-', '+').replace('_', '/')

				# Add padding if missing, as base64.b64decode requires a length multiple of 4
				missing_padding = len(base64_for_decoding) % 4
				if missing_padding != 0:
					base64_for_decoding += '=' * (4 - missing_padding)
				
				# Attempt to decode
				decoded_url_bytes = base64.b64decode(base64_for_decoding)
				original_url = decoded_url_bytes.decode('utf-8', errors='ignore')
				
				# Extract extension from the reconstructed URL, removing query and fragment
				path = original_url.split('?')[0].split('#')[0] 
				_, ext = os.path.splitext(path)
				return ext.lower()
		except Exception:
			# Catch any decoding errors (e.g., Invalid character if the string is truly malformed)
			pass # Fail silently if extension cannot be determined from proxy URL
		return "" # Return empty string if extraction or decoding fails

	def _is_valid_image_format(self, url: str) -> bool:
		"""
		Check if the image URL points to a valid static image format by examining content type,
		or by inferring from file extension if content type is generic.
		"""
		# Define allowed and excluded image MIME types
		allowed_mime_types = [
			'image/jpeg', 'image/jpg', 'image/png', 'image/webp',
			'image/bmp', 'image/tiff', 'image/tif'
		]
		excluded_mime_types = [
			'image/gif', 'image/apng', 'image/svg+xml', # Animated or vector formats
		]
		
		try:
			response = requests.head(url, timeout=5, allow_redirects=True)
			content_type = response.headers.get('content-type', '').lower()
			status_code = response.status_code

			# 1. Basic validation: Check status code
			if not (200 <= status_code < 300):
				return False
			
			# 2. Check if content_type is explicitly an allowed image type
			for allowed in allowed_mime_types:
				if allowed in content_type:
					# Double check it's not an explicitly excluded type
					for excluded in excluded_mime_types:
						if excluded in content_type:
							return False
					return True # Directly accepted

			# 3. Handle generic 'application/octet-stream' or other non-image content-types by checking file extension
			if content_type == 'application/octet-stream' or not content_type.startswith('image/'):
				ext = self._get_extension_from_brave_proxy_url(url)
				
				allowed_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif']
				
				if ext and ext.lower() in allowed_extensions:
					return True
				else:
					return False
			
			# 4. If none of the above, it's an image content-type not explicitly allowed or excluded, so reject.
			return False
			
		except requests.exceptions.RequestException:
			return False # Default to rejecting if we can't verify content-type due to request error.
		except Exception:
			return False # Default to rejecting for any other unexpected error.

	def _download_img_from_url(self, url: str, save_path: str):
		"""Downloads an image from a URL image and saves it to a specified path."""
		os.makedirs(os.path.dirname(save_path), exist_ok=True)
		try:
			response = requests.get(url, stream=True, timeout=10)
			response.raise_for_status()
			with open(save_path, "wb") as f:
				for chunk in response.iter_content(1024):
					f.write(chunk)
		except requests.exceptions.RequestException as e:
			raise ToolException(f"Image download failed: {e}")
		except Exception as e:
			raise ToolException(f"Unexpected error during image download: {e}")