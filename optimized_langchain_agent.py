import sys
import traceback
import requests
from bs4 import BeautifulSoup
import re
from typing import List, Optional, Callable, Iterator, Dict, Tuple
import concurrent.futures
import time
import json

from langchain_community.tools import BraveSearch
from brave_search_api import BraveSearchManual

from dotenv import load_dotenv
import os
load_dotenv()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.tools import tool, ToolException
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage


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
        print(f"--- Scraping Error (Parsing/Other): {url} - {e} ---", file=sys.stderr)
        return None



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
        print(f"--- Link Extraction Timeout: {url} ---", file=sys.stderr)
        return []
    except requests.exceptions.RequestException as e:
        print(f"--- Link Extraction RequestException: {url} - {e} ---", file=sys.stderr)
        return []
    except Exception as e:
        print(f"--- Link Extraction Error: {url} - {e} ---", file=sys.stderr)
        return []


# --- Combined Search and Scrape Tool (Concurrent) ---
if BraveSearchManual and BRAVE_API_KEY:
    try:
        brave_search_client = BraveSearchManual(api_key=BRAVE_API_KEY)
        print("BraveSearch client initialized.")
    except ValueError as e:
        print(f"Error initializing BraveSearch: {e}", file=sys.stderr)
        brave_search_client = None
else:
    brave_search_client = None



@tool
def search_and_scrape_web(query: str, k: int = 3) -> dict:
    """
    Searches web (Brave Search), concurrently scrapes content from top 'k' results (max 5).
    Use ONLY for recent/specific info NOT in internal knowledge. Be specific.
    """
    if not brave_search_client:
         raise ToolException("Brave search client not available.")

    print(f"--- TOOL: Searching '{query}' (k={k}) ---", file=sys.stderr)
    num_to_scrape = min(k, 5)
    if num_to_scrape <= 0:
         raise ToolException("k must be positive.")

    try:
        initial_results = brave_search_client.search(query, count=num_to_scrape)
        urls_to_scrape = [r.get("url") for r in initial_results if r.get("url")]
        if not urls_to_scrape: return {"results": []}

        print(f"--- TOOL: Starting concurrent scraping for {len(urls_to_scrape)} URLs... ---", file=sys.stderr)
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_to_scrape) as executor:
            future_to_url = {executor.submit(_scrape_and_extract_text, url): url for url in urls_to_scrape}
            scrape_results_map = {}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    scrape_results_map[url] = future.result()
                except Exception as exc:
                    print(f'--- TOOL: Scraping thread exception for {url}: {exc} ---', file=sys.stderr)
                    scrape_results_map[url] = None

        final_scraped_results = [
            {"url": url, "content": scrape_results_map.get(url)}
            for url in urls_to_scrape
        ]
        print(f"--- TOOL: Returning {len(final_scraped_results)} results ---", file=sys.stderr)
        return {"results": final_scraped_results}

    except ToolException: raise
    except Exception as e:
        print(f"--- TOOL ERROR (Orchestration): {e} ---", file=sys.stderr)
        raise ToolException(f"Unexpected error in search/scrape tool: {e}")


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

    print(f"--- TOOL: Finding interesting links for '{query}' (k={k}) ---", file=sys.stderr)
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
            print(f"--- TOOL: Extracting links from {len(urls_to_extract)} top pages... ---", file=sys.stderr)
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
                        print(f"--- TOOL: Link extraction error for {url}: {e} ---", file=sys.stderr)

        # Deduplicate links by URL
        seen_urls = set()
        unique_links = []
        for link in all_links:
            if link["url"] not in seen_urls:
                seen_urls.add(link["url"])
                unique_links.append(link)
        
        # Limit total number of links to return
        final_links = unique_links[:10]  # Return at most 10 unique links
        
        print(f"--- TOOL: Returning {len(final_links)} interesting links ---", file=sys.stderr)
        return json.dumps({
            "links": final_links,
            "message": f"Found {len(final_links)} interesting links related to '{query}'."
        })

    except ToolException: raise
    except Exception as e:
        print(f"--- TOOL ERROR (Link Finding): {e} ---", file=sys.stderr)
        raise ToolException(f"Unexpected error in find_interesting_links tool: {e}")


# --- Optimized Brave Search Tool ---
brave_tool = BraveSearch.from_api_key(api_key=BRAVE_API_KEY, search_kwargs={"count": 5})  


class OptimizedLangchainAgent:
    """
    Optimized Agent using Langchain, Ollama, and search tools.
    Includes performance improvements for faster processing of search results.
    """
    def __init__(self,
                 model_name: str = "qwen2.5:3b",
                 layout_model: str = "gema3:12b",
                 tools: List[Callable] = [brave_tool, search_and_scrape_web, find_interesting_links],
                 system_message: str = (
                    "You are a helpful assistant. "
                    "Answer using internal knowledge for basic facts like capitals common historical events, and general knowledge."
                    "Use tools when appropriate:"
                    "1. Use `BraveSearch` for general info, headlines, or to know what's trending. "
                    "2. Use `search_and_scrape_web` for specific recent information, like news articles or specific events. "
                    "3. ALWAYS use `find_interesting_links` when providing information that users might want to explore further "
                    "or when the user could benefit from additional resources on the topic."
                    "Do NOT use search tools for common knowledge, geographical information, creative tasks, or known summaries. "
                    "When using a tool, state that you are searching, then answer based ONLY on tool results."
                    "Always aim to provide useful links that expand on your answer when relevant."
                 ),
                 verbose_agent: bool = False
                 ):
        """Initializes the agent with optimized parameters."""
        self.model_name = model_name
        self.tools = [t for t in tools if callable(t)]
        if not self.tools:
             print("Warning: No valid tools provided.", file=sys.stderr)
        self.verbose_agent = verbose_agent
        self.tool_map = {tool.name: tool for tool in self.tools}

        if search_and_scrape_web in self.tools and not brave_search_client:
            print("Warning: Search tool included but is non-functional.", file=sys.stderr)

        try:
            # Initialize LLM with optimized parameters
            self.llm = ChatOllama(model=model_name, temperature=0)
            # Bind tools for easy use later
            self.llm_with_tools = self.llm.bind_tools(self.tools)
            _ = self.llm.invoke("OK")  # Simple connection check
            print(f"Successfully connected to Ollama model '{self.model_name}'.")
        except Exception as e:
            print(f"Error initializing/connecting to Ollama model '{self.model_name}'. Details: {e}", file=sys.stderr)
            sys.exit(1)

        # Define prompt template with more focused instructions
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("placeholder", "{chat_history}"),
            ("human", "{input}")
        ])
        
        # Define a more concise prompt for processing tool results
        self.tool_processing_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful assistant. Process the search results and links concisely. "
                      "Extract only key information related to the query. "
                      "When interesting links are available, incorporate them into your response. "
                      "ALWAYS include 2-5 of the most relevant links when they are available. "
                      "Format links as markdown [Title](URL) with brief descriptions of what they contain. "
                      "Be direct and to the point."),
            ("placeholder", "{chat_history}"),
            ("human", "{input}")
        ])

    def _format_messages(self, task: str, history: List[BaseMessage], is_tool_processing: bool = False) -> List[BaseMessage]:
        """Helper to format messages for the LLM call with option for different prompts."""
        if is_tool_processing:
            prompt_value = self.tool_processing_prompt.invoke({"input": task, "chat_history": history})
        else:
            prompt_value = self.prompt.invoke({"input": task, "chat_history": history})
        return prompt_value.to_messages()

    def _truncate_tool_results(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Helper to truncate tool results to improve processing speed."""
        truncated_messages = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                # Try to extract just the essential information from tool results
                try:
                    content = msg.content
                    # If it's JSON-like and very long, try to extract just key portions
                    if isinstance(content, str) and len(content) > 1000 and (content.startswith('{') or content.startswith('[')):
                        # Keep just the beginning portion that likely contains the most relevant info
                        truncated_content = content[:1000] + "... [truncated for efficiency]"
                        new_msg = ToolMessage(content=truncated_content, tool_call_id=msg.tool_call_id)
                        truncated_messages.append(new_msg)
                    else:
                        truncated_messages.append(msg)
                except:
                    # If any issues, keep original message
                    truncated_messages.append(msg)
            else:
                truncated_messages.append(msg)
        return truncated_messages

    def run(self, task: str) -> Iterator[str]:
        """
        Executes a task with optimized processing for faster responses.
        Always attempts to find interesting links for most queries.
        """
        print(f"\n--- Task Received ---\n{task}")
        print("\n--- Agent Response ---")
        start_time = time.time()

        # Start with just the human input
        messages: List[BaseMessage] = [HumanMessage(content=task)]

        try:
            # === First LLM Call (Planning/Tool Calling or Direct Answer) ===
            formatted_messages = self._format_messages(task, [])
            first_response: AIMessage = self.llm_with_tools.invoke(formatted_messages)
            messages.append(first_response)

            # === Tool Execution (If Needed) ===
            tool_used = False
            if first_response.tool_calls:
                print("--- Agent: Decided to use tools ---", file=sys.stderr)
                tool_messages = []
                for tool_call in first_response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_start = time.time()
                    print(f"--- Agent: Calling tool '{tool_name}' ---", file=sys.stderr)
                    if tool_name in self.tool_map:
                        selected_tool = self.tool_map[tool_name]
                        tool_output = selected_tool.invoke(tool_call)
                        tool_messages.append(tool_output)
                        tool_used = True
                        print(f"--- Agent: Tool '{tool_name}' completed in {time.time() - tool_start:.2f}s ---", file=sys.stderr)
                    else:
                        error_msg = f"Tool '{tool_name}' not found."
                        print(f"--- Agent Error: {error_msg} ---", file=sys.stderr)
                        tool_messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call["id"]))
                messages.extend(tool_messages)
                
                # Check if find_interesting_links was NOT called but task is informational
                # This ensures we always try to include relevant links
                link_tool_called = any(tc["name"] == "find_interesting_links" for tc in first_response.tool_calls)
                
                if not link_tool_called and tool_used and "find_interesting_links" in self.tool_map:
                    print("--- Agent: Automatically finding interesting links ---", file=sys.stderr)
                    try:
                        link_tool = self.tool_map["find_interesting_links"]
                        # Create a properly formatted invocation using the tool's invoke method
                        link_result = link_tool.invoke({"query": task, "k": 5})
                        # Add the result as a tool message
                        tool_message = ToolMessage(
                            content=link_result if isinstance(link_result, str) else json.dumps(link_result),
                            tool_call_id="auto_link_tool_call"
                        )
                        messages.append(tool_message)
                    except Exception as e:
                        print(f"--- Agent: Auto link finding failed: {e} ---", file=sys.stderr)

                # === Optimization: Apply truncation to tool results ===
                optimized_messages = self._truncate_tool_results(messages)
                
                # === Second LLM Call with special prompt for processing tool results ===
                process_start = time.time()
                print("--- Agent: Processing search results and links ---", file=sys.stderr)
                final_formatted_messages = self._format_messages(task, optimized_messages, is_tool_processing=True)
                # Stream the response
                print("--- Agent: Streaming final response ---", file=sys.stderr)
                for chunk in self.llm.stream(final_formatted_messages):
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        yield chunk.content
                
                print(f"--- Processing completed in {time.time() - process_start:.2f}s ---", file=sys.stderr)
            else:
                # === Even for direct answers, try to find relevant links ===
                print("--- Agent: Answering directly but still finding links ---", file=sys.stderr)
                
                # First yield the direct answer
                direct_answer_chunks = []
                for chunk in self.llm.stream(formatted_messages):
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        direct_answer_chunks.append(chunk.content)
                        yield chunk.content
                
                # Then try to find relevant links
                if "find_interesting_links" in self.tool_map:
                    try:
                        # Don't print this to user - just gather the links
                        yield "\n\n**Relevant resources:**\n"
                        
                        # Use the proper invoke method with a dictionary of arguments
                        link_tool = self.tool_map["find_interesting_links"]
                        link_result = link_tool.invoke({"query": task, "k": 3})
                        
                        # Process the links result
                        try:
                            # Handle various formats of results
                            if isinstance(link_result, str):
                                try:
                                    link_data = json.loads(link_result)
                                except:
                                    link_data = {"links": []}
                            else:
                                link_data = link_result
                                
                            # Extract links, handling different possible formats
                            if isinstance(link_data, dict):
                                links = link_data.get("links", [])
                            elif isinstance(link_data, list):
                                links = link_data
                            else:
                                links = []
                                
                                if links:
                                    for i, link in enumerate(links[:5]):  # Limit to top 5
                                        title = link.get("title", "Resource")
                                        url = link.get("url", "")
                                        desc = link.get("description", "")
                                        
                                        # Format as markdown link with brief description
                                        link_text = f"- [{title}]({url})"
                                        if desc and len(desc) > 20:  # Only add description if meaningful
                                            # Truncate long descriptions
                                            if len(desc) > 100:
                                                desc = desc[:97] + "..."
                                            link_text += f": {desc}"
                                        
                                        yield link_text + "\n"
                                else:
                                    yield "No additional resources found.\n"
                        except Exception as e:
                            print(f"--- Agent: Link processing error: {e} ---", file=sys.stderr)
                            # Don't show error to user - just continue
                    except Exception as e:
                        print(f"--- Agent: Link finding failed: {e} ---", file=sys.stderr)
                        # Don't show error to user - just continue

            print(f"--- Total time: {time.time() - start_time:.2f}s ---", file=sys.stderr)

        except Exception as e:
            print(f"\n--- Error during Agent Execution: {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            yield f"\n[Agent Error: {e}]"


# --- Example Usage ---
def main():
    """Runs example tasks using the LangchainAgent."""
    if not brave_search_client:
         print("\nWARNING: Brave search client not initialized.", file=sys.stderr)

    try:
        langchain_agent = OptimizedLangchainAgent(model_name="qwen2.5:3b", verbose_agent=False)

        separator = "\n" + "="*60

        # --- Task 1 ---
        print(separator)
        task1 = "What is the capital of France?"
        for token in langchain_agent.run(task1):
            print(token, end="", flush=True)
        print()
        print(separator)

        # # --- Task 2 ---
        task2 = "What are the latest developments regarding the Artemis program missions?"
        for token in langchain_agent.run(task2):
            print(token, end="", flush=True)
        print()
        print(separator)

        # # --- Task 3 ---
        task3 = "Write a short haiku about a web scraping robot."
        for token in langchain_agent.run(task3):
            print(token, end="", flush=True)
        print()
        print(separator)

        # --- Task 4 ---
        task4 = "Are there any recent news articles discussing the plot or reception of the movie 'Dune: Part Two'?"
        for token in langchain_agent.run(task4):
            print(token, end="", flush=True)
        print()
        print(separator)

    except SystemExit:
        print("Exiting due to configuration error.", file=sys.stderr)
    except Exception as e:
        print(f"\nAn unexpected error occurred in the main block: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
    main()