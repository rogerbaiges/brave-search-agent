import requests
import re
import json
import sys
import os
import concurrent.futures
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

from datetime import datetime, timedelta
import traceback

from langchain.tools import tool
from langchain_core.tools import ToolException

from config import VERBOSE, IMAGES_DIR, SCREENSHOTS_DIR

from brave_search_api import BraveSearchManual

from playwright.sync_api import sync_playwright, Route, Request

from dotenv import load_dotenv
load_dotenv()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
OPEN_WEATHER_API_KEY = os.getenv("OPEN_WEATHER_API_KEY")

assert BRAVE_API_KEY, "BRAVE_API_KEY must be set in .env file"
assert OPEN_WEATHER_API_KEY, "OPEN_WEATHER_API_KEY must be set in .env file"

_brave_search_client = BraveSearchManual(api_key=BRAVE_API_KEY)

def _generate_safe_filename(text: str, max_length: int = 50) -> str:
	text = str(text)
	text = re.sub(r'[<>:"/\\|?*.\s]', '_', text)
	text = re.sub(r'_+', '_', text)
	text = text.strip('_')[:max_length].lower()
	if not text:
		return "default_filename"
	return text

@tool
def general_web_search(query: str, k: int = 3, freshness: Optional[str] = None) -> str:
	"""
	Searches the web.
	Returns links with short descriptions. Useful for obtaining websites that will after searched with the `extract_web_content` tool.
	Use the ``freshness`` parameter to filter results by time period if relevant.
	Also saves related images to IMAGES_DIR and screenshots of result pages to SCREENSHOTS_DIR, respecting freshness.

	Parameters:
		query (str): The search query.
		freshness (str, optional): Freshness filter for search results and images.
			Options: "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year), None (any time).
		k (int, optional): Number of search results to return (max 5). Defaults to 3.

	Returns:
		str: JSON string with list of search results.
	"""
	if VERBOSE: print(f"--- TOOL: General Web Searching '{query}' (Freshness: {freshness}) ---", file=sys.stderr)
	k = min(k, 5)

	try:
		search_params = {"freshness": freshness} if freshness else {}
		results_list = _brave_search_client.search_web(query, count=k, **search_params)

		try:
			_brave_search_client.search_images(
				query=query,
				save_to_dir=IMAGES_DIR,
				count=max(2, k), # Ensure at least 2 images
				save_basename=f"{datetime.now().strftime('%d-%m-%y_%H_%M')}_web_search_img_{_generate_safe_filename(query)}",
				freshness=freshness # Pass freshness to image search
			)
		except Exception as e_img:
			if VERBOSE: print(f"--- Error saving images for general_web_search '{query}': {e_img} ---", file=sys.stderr)

		if results_list:
			os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
			query_slug = _generate_safe_filename(query)
			for i, result in enumerate(results_list):
				url = result.get("url")
				if url:
					ss_filename = f"{datetime.now().strftime('%d-%m-%y_%H_%M')}_general_search_ss_{query_slug}_{i}.png"
					ss_path = os.path.join(SCREENSHOTS_DIR, ss_filename)
					try:
						if VERBOSE: print(f"--- Taking screenshot for general_web_search: {url} -> {ss_path} ---", file=sys.stderr)
						web_screenshot(url=url, output_path=ss_path)
					except Exception as e_ss:
						if VERBOSE: print(f"--- Failed to take screenshot for {url}: {e_ss} ---", file=sys.stderr)

			# with open("search_results.txt", "a") as f:
			# 	f.write(f"TOOL: General Web Search for '{query}'\n")
			# 	f.write(str(results_list))
		
		return json.dumps({"results": results_list, "note": "If results are not enough, use the `extract_web_content` to get more detailed information from each link."})

	except ToolException as e_tool:
		if VERBOSE: print(f"--- Error during general_web_search (Brave API call): {e_tool} ---", file=sys.stderr)
		return json.dumps({"error": str(e_tool), "results": []})
	except Exception as e_main:
		if VERBOSE: print(f"--- Unexpected error in general_web_search '{query}': {e_main} ---", file=sys.stderr)
		traceback.print_exc(file=sys.stderr)
		return json.dumps({"error": f"Unexpected error: {e_main}", "results": []})


def _scrape_and_extract_text(url: str, timeout: int = 10, max_chars: int | None = 2500) -> Optional[str]:
	try:
		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
		}
		response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=False)
		response.raise_for_status()
		content_type = response.headers.get('content-type', '').lower()
		if 'html' not in content_type:
			return None # Changed from "" to None to indicate non-HTML or failure more clearly
		soup = BeautifulSoup(response.content, 'html.parser')
		for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "noscript", "button", "input"]):
			element.decompose()
		main_content = soup.find('main') or soup.find('article') or \
					   soup.find('div', attrs={'role': 'main'}) or \
					   soup.find('div', id='content') or \
					   soup.find('div', class_='content') or soup.body
		text = main_content.get_text(separator=' ', strip=True) if main_content else ""
		text = re.sub(r'\s+', ' ', text).strip()
		if max_chars is not None and len(text) > max_chars:
			text = text[:max_chars] + "..."
		if VERBOSE: print(f"--- Scraped {len(text)} characters from {url} ---", file=sys.stderr)
		return text
	except requests.exceptions.Timeout:
		if VERBOSE: print(f"--- Scraping Timeout: {url} ---", file=sys.stderr); return None # Changed to None
	except requests.exceptions.RequestException as e:
		if VERBOSE: print(f"--- Scraping RequestException: {url} - {e} ---", file=sys.stderr); return None # Changed to None
	except Exception as e:
		if VERBOSE: print(f"--- Scraping Error (Parsing/Other): {url} - {e} ---", file=sys.stderr)
		return None # Changed to None

@tool
def extract_web_content(url: str, max_chars: Optional[int] = 2500) -> str:
	"""
	Extracts the main textual content from a given URL. Specially useful for getting the subpages of a specific URL and therefore deepening the context of a specific URL.
	Useful for getting detailed information directly from a specific web page
	whose URL is already known (e.g., from a previous search or `find_interesting_links` tool call).

	Use this tool ONLY when you already have a specific URL that you know contains
	the information you need to answer the user's question, and you need the full
	textual content of that page.

	Do NOT use this tool for general web searches; use `general_web_search` instead. This tool does not browse or follow links;
	it only extracts content from the *provided* URL.

	Parameters:
		url (str): The URL of the web page to extract content from.

	Returns:
		str: The extracted textual content of the web page, or an error message if extraction fails.
	"""
	if VERBOSE: print(f"--- TOOL: Extracting content from URL: {url} (max_chars: {max_chars}) ---", file=sys.stderr)
	try:
		content = _scrape_and_extract_text(url, max_chars=max_chars)
		if content is None: # _scrape_and_extract_text now returns None on failure or non-HTML
			return f"Error: Could not extract content from {url}. It might be non-HTML, inaccessible, or timed out."
		return content
	except Exception as e:
		error_message = f"An unexpected error occurred during content extraction from {url}: {e}"
		if VERBOSE: traceback.print_exc(file=sys.stderr)
		raise ToolException(error_message) from e # Raise ToolException for proper agent handling


@tool
def extended_web_search(query: str, k: int = 2, freshness: Optional[str] = None, max_chars: Optional[int] = 2500) -> dict:
	"""
	Searches the web using Brave Search API and provides the full content from top 'k' results (max 5).
	This is useful for obtaining full context about something or detailed information on a topic.
	Use ONLY when you believe that the short description of a web result provided by the basic web search tool won't be enough to answer the user's question properly.
	Use ALWAYS when the already provided content of the web results obtained by the basic web search is not enough to directly answer the user's question properly.
	Use the ``freshness`` parameter to filter results by time period if relevant.

	Parameters:
		query: The search query to find relevant content
		k: Number of search results to scrape (max 2).
		freshness (str, optional): Freshness filter for search results and images.
			Options: "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year), None (any time).

	Returns:
		dict: Dictionary with list of scraped results under the "results" key.
	"""
	if not _brave_search_client:
		raise ToolException("Brave search client not available.")
	
	if VERBOSE: print(f"--- TOOL: Extended Web Searching '{query}' (k={k}, Freshness: {freshness}) ---", file=sys.stderr)
	num_to_scrape = min(k, 2)
	if num_to_scrape <= 0:
		raise ToolException("k must be positive.")

	try:
		try:
			_brave_search_client.search_images(
				query=query,
				save_to_dir=IMAGES_DIR,
				count=max(2, num_to_scrape),  # Ensure at least 2 images
				save_basename=f"{datetime.now().strftime('%d-%m-%y_%H_%M')}_extended_search_img_{_generate_safe_filename(query)}",
				freshness=freshness # Pass freshness to image search
			)
		except Exception as e_img:
			if VERBOSE: print(f"--- Error saving images for extended_web_search '{query}': {e_img} ---", file=sys.stderr)
			
		search_params = {"freshness": freshness} if freshness else {}
		initial_results = _brave_search_client.search_web(query, count=num_to_scrape, **search_params)

		urls_to_scrape = [r.get("url") for r in initial_results if r.get("url")]
		if not urls_to_scrape: return {"results": []}

		os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
		query_slug = _generate_safe_filename(query)
		for i, url in enumerate(urls_to_scrape):
			ss_filename = f"{datetime.now().strftime('%d-%m-%y_%H_%M')}_extended_search_ss_{query_slug}_{i}.png"
			ss_path = os.path.join(SCREENSHOTS_DIR, ss_filename)
			try:
				if VERBOSE: print(f"--- Taking screenshot for extended_web_search: {url} -> {ss_path} ---", file=sys.stderr)
				web_screenshot(url=url, output_path=ss_path)
			except Exception as e_ss:
				if VERBOSE: print(f"--- Failed to take screenshot for {url}: {e_ss} ---", file=sys.stderr)

		if VERBOSE: print(f"--- TOOL: Starting concurrent scraping for {len(urls_to_scrape)} URLs... ---", file=sys.stderr)
		with concurrent.futures.ThreadPoolExecutor(max_workers=num_to_scrape) as executor:
			future_to_url = {executor.submit(_scrape_and_extract_text, url, max_chars=max_chars): url for url in urls_to_scrape}
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
		# Filter out entries where scraping failed
		final_scraped_results = [r for r in final_scraped_results if r["content"] is not None]

		# if VERBOSE: print(f"--- TOOL: Returning {len(final_scraped_results)} results ---", file=sys.stderr)
		# with open("search_results.txt", "a") as f:
		# 	f.write(f"TOOL: Extended Web Search for '{query}'\n")
		# 	f.write(str(final_scraped_results))
		
		return {"results": final_scraped_results, "note": "For each URL you find interesting, you can use the `extract_web_content` tool to get the full text content."}

	except ToolException: raise
	except Exception as e:
		if VERBOSE: print(f"--- TOOL ERROR (Orchestration): {e} ---", file=sys.stderr)
		return {"error": f"Unexpected error in extended_web_search: {e}", "results": []}

def _extract_links_and_metadata(url: str, timeout: int = 10) -> Optional[List[Dict]]:
	try:
		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
		}
		response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
		response.raise_for_status()
		content_type = response.headers.get('content-type', '').lower()
		if 'html' not in content_type: return []
		soup = BeautifulSoup(response.content, 'html.parser')
		extracted_links = []
		for anchor in soup.find_all('a', href=True):
			href = anchor.get('href', '').strip()
			if not href or href.startswith(('javascript:', '#')): continue
			from urllib.parse import urlparse
			base_url_parts = urlparse(url)
			if href.startswith('/'): href = f"{base_url_parts.scheme}://{base_url_parts.netloc}{href}"
			elif not href.startswith(('http://', 'https://')): continue
			title = anchor.get_text(strip=True) or "Link from " + url
			description = ""
			parent = anchor.find_parent(['p', 'div', 'li'])
			if parent:
				description = parent.get_text(strip=True)
				if description:
					description = description.replace(title, "", 1).strip()
					description = (description[:197] + "...") if len(description) > 200 else description
			extracted_links.append({"url": href, "title": title[:100], "description": description})
		seen_urls = set()
		unique_links = [link for link in extracted_links if link["url"] not in seen_urls and not seen_urls.add(link["url"])]
		return unique_links[:10]
	except requests.exceptions.Timeout:
		if VERBOSE: print(f"--- Link Extraction Timeout: {url} ---", file=sys.stderr); return []
	except requests.exceptions.RequestException as e:
		if VERBOSE: print(f"--- Link Extraction RequestException: {url} - {e} ---", file=sys.stderr); return []
	except Exception as e:
		if VERBOSE: print(f"--- Link Extraction Error: {url} - {e} ---", file=sys.stderr); return []

@tool
def find_interesting_links(query: str, k: int = 5, freshness: Optional[str] = None) -> str:
	"""
	Finds interesting and relevant links related to a query.
	Searches the web and extracts links from search results, optionally filtering by freshness.
	Use for finding resources, references, or interesting related content.
	VERY IMPORTANT: Always use this tool when the user might benefit from having links for further reading.

	Parameters:
		query: The search query to find relevant links
		k: Number of search results to process (max 5)
		freshness (str, optional): Freshness filter for search results.
			Options: "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year), None (any time).

	Returns:
		JSON string with list of links and metadata
	"""
	if not _brave_search_client: raise ToolException("Brave search client not available.")
	if VERBOSE: print(f"--- TOOL: Finding interesting links for '{query}' (k={k}, Freshness: {freshness}) ---", file=sys.stderr)
	num_results = min(k, 5)
	if num_results <= 0: raise ToolException("k must be positive.")
	try:
		search_params = {"freshness": freshness} if freshness else {}
		search_results = _brave_search_client.search_web(query, count=num_results, **search_params)
		if not search_results: return json.dumps({"links": [], "message": "No results found."})
		
		all_links = []
		for result in search_results:
			if result.get("url"):
				all_links.append({
					"url": result.get("url"), "title": result.get("title", ""),
					"description": result.get("description", ""), "source": "search_result"
				})
		
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
							for link in links: link["source"] = f"extracted_from_{url}"
							all_links.extend(links)
					except Exception as e:
						if VERBOSE: print(f"--- TOOL: Link extraction error for {url}: {e} ---", file=sys.stderr)
		seen_urls = set()
		unique_links = [link for link in all_links if link["url"] not in seen_urls and not seen_urls.add(link["url"])][:10]
		if VERBOSE: print(f"--- TOOL: Returning {len(unique_links)} interesting links ---", file=sys.stderr)
		return json.dumps({"links": unique_links, "note": f"Found {len(unique_links)} interesting links for '{query}'. Show them to the user so they can explore further."})
	except ToolException: raise
	except Exception as e:
		print(f"--- TOOL ERROR (Link Finding): {e} ---", file=sys.stderr)
		return json.dumps({"error": f"Unexpected error in find_interesting_links: {e}", "links": []})


def web_screenshot(
	url: str,
	output_path: str = "screenshot.png",
	full_page: bool = False,
) -> None:
	output_dir = os.path.dirname(output_path)
	if output_dir: os.makedirs(output_dir, exist_ok=True)
	_HIDE_OVERLAYS_CSS = """
	[id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i],
	[id*="gdpr" i], [class*="gdpr" i], [id*="banner" i], [class*="banner" i],
	[id*="overlay" i], [class*="overlay" i], [id*="modal" i], [class*="modal" i],
	div[role="dialog"][aria-modal="true"], [id*="subscribe" i], [class*="subscribe" i],
	iframe[src*="recaptcha"], iframe[src*="captcha"], #g-recaptcha, .grecaptcha-badge
	{ display: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }
	"""
	def _block_captcha(route: Route, request: Request) -> None:
		url_low = request.url.lower()
		if "recaptcha" in url_low or "google.com/recaptcha" in url_low: route.abort()
		else: route.continue_()
	try:
		with sync_playwright() as p:
			browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
			context = browser.new_context(
				user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
				viewport={"width": 1366, "height": 768}, device_scale_factor=1.0, locale="en-US",
			)
			context.route("**/*recaptcha*/**", _block_captcha)
			page = context.new_page()
			page.goto(url, wait_until="domcontentloaded", timeout=60_000)
			page.add_style_tag(content=_HIDE_OVERLAYS_CSS)
			page.wait_for_timeout(500)
			page.screenshot(path=str(output_path), full_page=full_page)
			browser.close()
			if VERBOSE: print(f"--- Screenshot saved to {output_path} ---", file=sys.stderr)
	except Exception as e:
		if VERBOSE: print(f"--- Error during web_screenshot for {url}: {e} ---", file=sys.stderr)

@tool
def image_search(query: str, k: int = 1, freshness: Optional[str] = None) -> dict:
	"""Searches and downloads supplementary images using the Brave Image API.
	These images are intended to enrich AI-generated content visually.

	**Critical Usage Note:** This tool is exclusively for acquiring supplementary
	images. A separate AI component is expected to utilize these images to improve
	the visual presentation of the final output. This tool should NOT be used for
	general webpage screenshots or as the primary method for sourcing image content.

	**Query Formulation:**
	-   Queries must be highly specific and concise, ideally one to two words per concept.
		For example, instead of "detailed pictures of the historical monument Taj Mahal located in Agra, India",
		use "Taj Mahal" or "Taj Mahal Agra".
	-   This tool is best used to find images for concrete entities or well-defined
		visual concepts.
	-   Examples of effective queries for specific things:
		-   Specific Places: "Eiffel Tower", "Mount Fuji", "Sahara Desert"
		-   Notable Events: "Olympics 2024 Opening", "Apollo 11 Moon Landing", "Carnival Rio"
		-   Distinct Objects/Things: "Antique telescope", "Vintage typewriter", "Formula 1 car"
		-   Well-known Persons: "Marie Curie", "Leonardo da Vinci", "Nelson Mandela"
		-   Visually distinct concepts (if applicable): "Aurora Borealis", "Galaxy Andromeda"

	Images will be dowloaded so another AI can use them to improve the visual presentation of the final output.

	Parameters:
		query (str): Image search query. Must be concise and specific. Never generic or relative to the text that the agent will output (e.g., "Topic 3")
			(e.g., "Golden Gate Bridge", "Siberian Husky puppy"), focusing on
			one or two words per concept.
		k (int, optional): The desired number of image results to download.
			Maximum is 5. Defaults to 1.
		freshness (Optional[str], optional): Filters images by freshness.
			Defaults to None (any time). Accepted values:
			- "pd": Past day
			- "pw": Past week
			- "pm": Past month
			- "py": Past year

	Returns:
		True if images were successfully downloaded, otherwise an error message.
	"""
	if not _brave_search_client: raise ToolException("Brave search client not available.")
	if k <= 0: raise ToolException("k must be positive.")
	try:
		images = _brave_search_client.search_images(
			query, save_to_dir=IMAGES_DIR,
			save_basename=f"{datetime.now().strftime('%d-%m-%y_%H_%M')}_image_search_{_generate_safe_filename(query)}", count=k,
			freshness=freshness # Pass freshness to image search
		)
		return {"images": images}
	except ToolException: raise
	except Exception as e:
		return {"error": f"Unexpected error in image_search: {e}", "images": []}

@tool
def news_search(query: str, k: int = 3, freshness: Optional[str] = None) -> dict:
	"""
	Searches Brave News API and returns up to *k* news articles.
	DO NOT use this tool for regular information that can be easily found with a web search. Instead, use it ONLY for current events or news-related queries.
	Use the ``freshness`` parameter to filter results by time period if this is convenient to properly answer the user's question.
	Also saves related images to IMAGES_DIR, respecting freshness.

	Parameters:
		query (str): News search query.
		k (int): Number of news results to return (max 5).
		freshness (str, optional): Freshness filter for news articles and related images.
			Options: "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year), None (any time).

	Returns:
		dict: Dictionary with list of news-result dictionaries under the "news" key.
	"""
	if not _brave_search_client: raise ToolException("Brave search client not available.")
	if k <= 0: raise ToolException("k must be positive.")
	k = min(k, 5)  # Limit to max 3 results for news search
	try:
		search_params = {"freshness": freshness} if freshness else {}
		news_items = _brave_search_client.search_news(query, count=k, **search_params)
		
		_brave_search_client.search_images(
			query, save_to_dir=IMAGES_DIR, count=max(2, k),  # Ensure at least 2 images
			save_basename=f"{datetime.now().strftime('%d-%m-%y_%H_%M')}_news_search_img_{_generate_safe_filename(query)}",
			freshness=freshness # Pass freshness to image search
		)
		# with open("search_results.txt", "a") as f:
		# 	f.write(f"TOOL: News Search for '{query}'\n")
		# 	f.write(str(news_items))

		return {"results": news_items, "note": "If results are not enough, use `extract_web_content` to get more detailed information."}
	except ToolException: raise
	except Exception as e:
		return {"error": f"Unexpected error in news_search: {e}", "news": []}


def _parse_coordinates_from_string(loc_str: str) -> Optional[tuple[float, float]]:
	if ',' not in loc_str: return None
	parts = loc_str.split(',')
	if len(parts) == 2:
		try:
			val1, val2 = float(parts[0].strip()), float(parts[1].strip())
			is_val1_lat, is_val1_lon = -90 <= val1 <= 90, -180 <= val1 <= 180
			is_val2_lat, is_val2_lon = -90 <= val2 <= 90, -180 <= val2 <= 180
			if is_val1_lat and is_val2_lon: return val1, val2
			if is_val1_lon and is_val2_lat:
				if VERBOSE: print(f"--- OWM Helper: Parsed '{loc_str}' as lon,lat. ---", file=sys.stderr)
				return val2, val1
			if is_val1_lat and is_val2_lat and is_val1_lon and is_val2_lon:
				if VERBOSE: print(f"--- OWM Helper Warning: Ambiguous '{loc_str}'. Assuming lat,lon. ---", file=sys.stderr)
				return val1, val2
			if VERBOSE: print(f"--- OWM Helper Warning: Coords '{loc_str}' out of range. ---", file=sys.stderr)
			return None
		except ValueError: return None
	return None

def _get_coordinates_owm(location: str, api_key: Optional[str]) -> Optional[tuple[float, float]]:
	if not isinstance(location, str) or not location.strip():
		if VERBOSE: print(f"--- OWM Helper: Invalid location: '{location}' ---", file=sys.stderr); return None
	parsed_coords = _parse_coordinates_from_string(location)
	if parsed_coords:
		if VERBOSE: print(f"--- OWM Helper: Parsed coords for '{location}': {parsed_coords} ---", file=sys.stderr)
		return parsed_coords
	if not api_key: print("--- OWM Helper Error: API Key missing for geocoding. ---", file=sys.stderr); return None
	geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={location.strip()}&limit=1&appid={api_key}"
	try:
		response = requests.get(geo_url, timeout=10); response.raise_for_status(); data = response.json()
		if data and isinstance(data, list) and len(data) > 0 and data[0].get('lat') is not None and data[0].get('lon') is not None:
			lat, lon = data[0]['lat'], data[0]['lon']
			if VERBOSE: print(f"--- OWM Helper: Geocoded '{location}' to ({lat}, {lon}) ---", file=sys.stderr)
			return lat, lon
		if VERBOSE: print(f"--- OWM Helper Warning: No geocoding results for '{location}'. Resp: {data} ---", file=sys.stderr)
		return None
	except requests.exceptions.RequestException as e:
		err = e.response.text[:200] if e.response else str(e)
		print(f"--- OWM Helper Error: Geocoding req failed for '{location}': {e}. Detail: {err}... ---", file=sys.stderr); return None
	except Exception as e:
		print(f"--- OWM Helper Error: Unexpected geocoding error for '{location}': {e} ---", file=sys.stderr)
		traceback.print_exc(file=sys.stderr); return None

@tool
def weather_search(city: str, num_days: int = 5) -> str:
	"""
	Provides a daily summary with ONLY the following information:
	Temperature range, weather description, precipitation chance, and average wind speed.

	Retrieves daily weather forecast for up to 5 days in the future from OpenWeatherMap API (https://openweathermap.org).
	Requires the city name as input and the number of days to forecast (1-5, it should be chosen in accordance with the user's question).
	

	Example:
		Date: 2025-05-27 (Tuesday)
		Temp: 21.8°C - 22.3°C (Feels like avg: 22.1°C)
		Weather: Scattered clouds
		Precipitation Chance: ~0%
		Avg Wind: 2.6 m/s

	Args:
		city (str): The name of the city to get the weather forecast for.
		num_days (int): Number of days to retrieve the forecast for (1-5).

	Returns:
		str: A summary of the weather forecast for the specified city and number of days.
		If an error occurs, returns an error message.
	"""
	if not OPEN_WEATHER_API_KEY: return "Error: OpenWeatherMap API Key not configured."
	coords = _get_coordinates_owm(city, OPEN_WEATHER_API_KEY)
	if not coords: return f"Error: Could not get coords for '{city}'. Valid city or 'lat,lon'?"
	lat, lon = coords; num_days = min(max(1, num_days), 5)
	fc_url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={OPEN_WEATHER_API_KEY}&units=metric"
	try:
		fc_resp = requests.get(fc_url, timeout=15); fc_resp.raise_for_status(); fc_data = fc_resp.json()
		daily_summary = {}
		targets = [datetime.now().date() + timedelta(days=i) for i in range(num_days)]
		for entry in fc_data.get('list', []):
			dt_txt = entry.get('dt_txt')
			if not dt_txt: continue
			try: entry_date = datetime.strptime(dt_txt, '%Y-%m-%d %H_%M:%S').date()
			except ValueError: continue
			if entry_date not in targets: continue
			if entry_date not in daily_summary: daily_summary[entry_date] = {'temps':[],'winds':[],'desc':set()}
			if entry.get('main', {}).get('temp') is not None: daily_summary[entry_date]['temps'].append(entry['main']['temp'])
			if entry.get('wind', {}).get('speed') is not None: daily_summary[entry_date]['winds'].append(entry['wind']['speed'])
			daily_summary[entry_date]['desc'].add(entry.get('weather', [{}])[0].get('description', 'N/A').capitalize())
		if not daily_summary: return f"No forecast data processed for {city} for specified dates."
		out = [f"Weather Forecast for {city} (next {num_days} day(s)):" ]
		for date_obj in sorted(daily_summary.keys()):
			d = daily_summary[date_obj]
			t_min, t_max = (f"{min(d['temps']):.1f}", f"{max(d['temps']):.1f}") if d['temps'] else ('N/A','N/A')
			w_avg = f"{sum(d['winds'])/len(d['winds']):.1f} m/s" if d['winds'] else 'N/A'
			desc = ", ".join(sorted(list(d['desc']))) or 'N/A'
			out.extend([f"\n- {date_obj.strftime('%Y-%m-%d (%A')}:",f"  Temp: {t_min}°C - {t_max}°C",f"  Weather: {desc}",f"  Avg Wind: {w_avg}"])
		return "\n".join(out)
	except requests.exceptions.RequestException as e:
		err = e.response.text[:200] if e.response else str(e)
		return f"Error: Fetch weather failed for {city}: {e}. Detail: {err}..."
	except Exception as e:
		if VERBOSE: traceback.print_exc(file=sys.stderr)
		return f"Error: Unexpected weather error for {city}: {e}"