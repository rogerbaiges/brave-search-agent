import sys
import traceback
import requests
from bs4 import BeautifulSoup
import re
from typing import List, Optional, Callable, Iterator, Dict
import concurrent.futures
import time

from langchain_community.tools import BraveSearch

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
def _scrape_and_extract_text(url: str, timeout: int = 5, max_chars: int = 3000) -> Optional[str]:
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


# --- Combined Search and Scrape Tool (Concurrent) ---
if BraveSearch and BRAVE_API_KEY:
    try:
        brave_search_client = BraveSearch(api_key=BRAVE_API_KEY)
        print("BraveSearch client initialized.")
    except ValueError as e:
        print(f"Error initializing BraveSearch: {e}", file=sys.stderr)
        brave_search_client = None
else:
    brave_search_client = None

@tool
def search_and_scrape_web(query: str, k: int = 2) -> dict:
    """
    Searches web (Brave Search), concurrently scrapes content from top 'k' results (max 3).
    Use ONLY for recent/specific info NOT in internal knowledge. Be specific.
    """
    if not brave_search_client:
         raise ToolException("Brave search client not available.")

    print(f"--- TOOL: Searching '{query}' (k={k}) ---", file=sys.stderr)
    num_to_scrape = min(k, 3)  # Reduced from 5 to 3
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


# --- Optimized Brave Search Tool ---
brave_tool = BraveSearch.from_api_key(api_key=BRAVE_API_KEY, search_kwargs={"count": 2})  # Reduced count


class OptimizedLangchainAgent:
    """
    Optimized Agent using Langchain, Ollama, and search tools.
    Includes performance improvements for faster processing of search results.
    """
    def __init__(self,
                 model_name: str = "qwen2.5:3b",
                 tools: List[Callable] = [brave_tool],
                 system_message: str = (
                    "You are a helpful assistant. Answer using internal knowledge IF confident. "
                    "Use tools ONLY for recent/specific information. "
                    "Use `BraveSearch` for general info, headlines, or to know what's trending. "
                    "Do NOT use the tool for common knowledge, creative tasks, or known summaries. "
                    "If using tool, state you are searching, then answer based ONLY on tool results."
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
            ("system", "You are a helpful assistant. Process the search results concisely. "
                      "Extract only key information related to the query. "
                      "Don't analyze every detail. Be direct and to the point."),
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
                        print(f"--- Agent: Tool '{tool_name}' completed in {time.time() - tool_start:.2f}s ---", file=sys.stderr)
                    else:
                        error_msg = f"Tool '{tool_name}' not found."
                        print(f"--- Agent Error: {error_msg} ---", file=sys.stderr)
                        tool_messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call["id"]))
                messages.extend(tool_messages)

                # === Optimization: Apply truncation to tool results ===
                optimized_messages = self._truncate_tool_results(messages)
                
                # === Second LLM Call with special prompt for processing tool results ===
                process_start = time.time()
                print("--- Agent: Processing search results ---", file=sys.stderr)
                final_formatted_messages = self._format_messages(task, optimized_messages, is_tool_processing=True)
                
                # Stream the response
                print("--- Agent: Streaming final response ---", file=sys.stderr)
                for chunk in self.llm_with_tools.stream(final_formatted_messages):
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        yield chunk.content
                
                print(f"--- Processing completed in {time.time() - process_start:.2f}s ---", file=sys.stderr)
            else:
                # === Direct Answer (No Tools Called) ===
                print("--- Agent: Answering directly (streaming) ---", file=sys.stderr)
                for chunk in self.llm_with_tools.stream(formatted_messages):
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        yield chunk.content

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

        # --- Task 2 ---
        task2 = "What are the latest developments regarding the Artemis program missions?"
        for token in langchain_agent.run(task2):
            print(token, end="", flush=True)
        print()
        print(separator)

        # --- Task 3 ---
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