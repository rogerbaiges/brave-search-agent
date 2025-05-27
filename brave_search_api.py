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

# NEW: Import for Google API client
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


from config import VERBOSE # Keep VERBOSE import if other parts of the system might still use it or if it's meant to be configurable globally.

from dotenv import load_dotenv

from langchain_core.tools import ToolException

# --- Load Environment Variables ---
load_dotenv()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

# NEW: Google API Key and Custom Search Engine ID
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID")

# Assert that Google keys are set, as they are now essential for web search
if not GOOGLE_API_KEY or not GOOGLE_CX_ID:
    print("WARNING: GOOGLE_API_KEY or GOOGLE_CX_ID not found in .env. Web search functionality will be unavailable.", file=sys.stderr)


# --- Brave Search API Interaction Class ---

class BraveSearchManual:
	"""Handles interactions with the Brave Search API and optionally Google Images."""
	# Brave Endpoints (still used for images, news, videos)
	BASE_WEB_URL = "https://api.search.brave.com/res/v1/web/search" # This Brave URL is no longer used by search_web
	BASE_IMAGES_URL = "https://api.search.brave.com/res/v1/images/search"
	BASE_NEWS_URL  = "https://api.search.brave.com/res/v1/news/search"
	BASE_VIDEOS_URL = "https://api.search.brave.com/res/v1/videos/search"

	# Google Custom Search Engine Service details
	GOOGLE_CSE_API_SERVICE_NAME = "customsearch"
	GOOGLE_CSE_API_VERSION = "v1"

	def __init__(self, api_key: str, verbose: bool = VERBOSE):
		self.verbose = verbose
		self.api_key = api_key # This is the Brave API key

		# These headers are specifically for Brave API calls, not used by Google CSE API
		self.headers = {
			"Accept": "application/json",
			"Accept-Encoding": "gzip",
			"X-Subscription-Token": self.api_key,
			"X-Loc-State": "ES",
			"X-Loc-State-Name": "Spain",
		}

		# NEW: Initialize Google Custom Search Engine service
		try:
			if GOOGLE_API_KEY and GOOGLE_CX_ID:
				self.google_cse_service = build(
					self.GOOGLE_CSE_API_SERVICE_NAME,
					self.GOOGLE_CSE_API_VERSION,
					developerKey=GOOGLE_API_KEY
				)
				if self.verbose:
					print("Google Custom Search Engine service initialized successfully.", file=sys.stderr)
			else:
				self.google_cse_service = None
				if self.verbose:
					print("Google Custom Search Engine service not initialized (missing API key or CX ID). Web search will use Brave.", file=sys.stderr)
		except Exception as e:
			self.google_cse_service = None
			print(f"Error initializing Google Custom Search Engine service: {e}. Web search will use Brave as fallback.", file=sys.stderr)
			traceback.print_exc(file=sys.stderr)


	def search_web(self, query: str, count: int = 5, **kwargs) -> List[Dict[str, Any]]:
		"""
		Performs a web search using the Google Custom Search Engine API.
		This method replaces the Brave Web Search functionality.
		"""
		# Check if Google CSE service is available; if not, fall back to Brave search if possible,
		# or raise an error if Brave API key is also missing.
		if not self.google_cse_service:
			if self.api_key: # Fallback to Brave search if Google service not initialized
				if self.verbose:
					print("Google CSE service not available. Falling back to Brave Web Search for this query.", file=sys.stderr)
				# Original Brave search logic (copy-pasted for fallback)
				params = {
					"q": query,
					"count": min(count, 20),
					"cr": "countryES",  # Country code for Spain
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
					raise ToolException(f"Brave API request failed (fallback): {e}")
				except json.JSONDecodeError as e:
					raise ToolException(f"Brave API response parsing failed (fallback): {e}")
				except Exception as e:
					print(f"--- Brave API Error: Unexpected error (fallback): {e} ---", file=sys.stderr)
					traceback.print_exc(file=sys.stderr)
					raise ToolException(f"An unexpected error occurred during Brave search (fallback): {e}")
			else:
				# Neither Google CSE nor Brave API key is available
				raise ToolException("Google CSE not configured and Brave API key not configured for web search.")


		# Map 'freshness' parameter from Brave format to Google's 'dateRestrict'
		freshness_map = {
			"pd": "d1",  # past day
			"pw": "w1",  # past week
			"pm": "m1",  # past month
			"py": "y1",  # past year
		}
		
		freshness_arg = kwargs.pop("freshness", None)
		date_restrict = freshness_map.get(freshness_arg, None)

		# Google CSE 'num' parameter has a max of 10 results per request.
		# The `tools.py` file handles higher `k` values by capping or making multiple calls if needed.
		# Here, we just cap at the Google API's limit.
		num_results = min(count, 10)

		# Parameters for Google CSE API call
		# Note: 'cx' is provided directly in the 'list' call, not in 'developerKey'
		params = {
			"q": query,           # Search query
			"num": num_results,   # Number of results (max 10 for Google CSE)
			"cx": GOOGLE_CX_ID,   # Custom Search Engine ID
			**kwargs              # Pass through any other valid Google CSE parameters
		}

		if date_restrict:
			params["dateRestrict"] = date_restrict
		
		# Remove any Brave-specific kwargs that might have been passed down from tools.py
		params.pop("safesearch", None) # Example: if `safesearch` was passed from tools

		try:
			# Execute the search using the google-api-python-client
			# The build() function requires developerKey, but cx is passed to cse().list()
			search_results = self.google_cse_service.cse().list(**params).execute()

			# Google CSE returns search results under the 'items' key.
			results = search_results.get("items", [])

			sanitized_results = []
			for r in results:
				title = r.get("title")
				url = r.get("link")      # Google CSE uses 'link' for the URL
				description = r.get("snippet") # Google CSE uses 'snippet' for description text

				if url: # Only add result if a URL is present
					sanitized_results.append({
						"title": title,
						"url": url,
						"description": description
					})
			return sanitized_results
		except HttpError as e:
			# Google API client raises HttpError for HTTP status codes >= 400
			error_msg = f"Google CSE API request failed for query '{query}': {e.resp.status}"
			if e.content:
				try:
					error_details = json.loads(e.content)
					# Extract specific error message from Google's error response
					error_msg += f" - Details: {error_details.get('error', {}).get('message', e.content.decode('utf-8'))}"
				except json.JSONDecodeError:
					error_msg += f" - Raw response: {e.content.decode('utf-8')}"
			raise ToolException(error_msg)
		except Exception as e:
			# Catch any other unexpected errors during the process
			print(f"--- Search API Error: Unexpected error during Google CSE search: {e} ---", file=sys.stderr)
			traceback.print_exc(file=sys.stderr)
			raise ToolException(f"An unexpected error occurred during Google CSE search: {e}")

	def search_news(self, query: str, count: int = 5, **kwargs):
		"""Searches Brave News API. (No change - still uses Brave)
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
		"""Searches Brave Image Search API. Downloads valid images if save_to_dir is provided. (No change - still uses Brave)"""
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
		normalizing to standard Base64 alphabet and applying robust padding. (No change - still uses Brave proxy URL logic)
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
		or by inferring from file extension if content type is generic. (No change - still used by Brave image search)
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
		"""Downloads an image from a URL image and saves it to a specified path. (No change - still used by Brave image search)"""
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
		
# Example test for search_web
if __name__ == "__main__":
	# Example usage of the BraveSearchManual class
	brave_search = BraveSearchManual(api_key=BRAVE_API_KEY, verbose=True)
	try:
		results = brave_search.search_web("sunset time Barcelona 27 May 2025", count=5)
		print("Web Search Results:", results)
	except ToolException as e:
		print(f"Web search failed: {e}", file=sys.stderr)