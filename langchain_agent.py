import sys
import traceback
import requests
from bs4 import BeautifulSoup
import re
from typing import List, Optional, Callable, Iterator, Dict # Added Dict
import concurrent.futures

# Assume brave_search_api.py contains the BraveSearch class and BRAVE_API_KEY setup
try:
    from brave_search_api import BraveSearch, BRAVE_API_KEY
except ImportError:
    print("Error: Could not import BraveSearch class.", file=sys.stderr)
    from dotenv import load_dotenv
    import os
    load_dotenv()
    BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
    BraveSearch = None

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.tools import tool, ToolException
# We won't use AgentExecutor directly for the final stream, but keep imports for now
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage

# --- Web Scraping Helper ---
# (Keep the function exactly as before)
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


# --- Combined Search and Scrape Tool (Concurrent) ---
# (Keep the tool function exactly as before)
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


# --- The Langchain Agent Class (Manual Final Stream) ---

class LangchainAgent:
    """
    Agent using Langchain, Ollama, and search tool.
    Manually streams the final LLM response token-by-token in the run() method.
    """
    def __init__(self,
                 model_name: str = "qwen2.5:3b",
                 tools: List[Callable] = [search_and_scrape_web],
                 system_message: str = (
                     "You are a helpful assistant. Answer using internal knowledge IF confident. "
                     "Use `search_and_scrape_web` ONLY for recent/specific/requested info. "
                     "Do NOT use the tool for common knowledge, creative tasks, or known summaries. "
                     "If using tool, state you are searching, then answer based ONLY on tool results."
                 ),
                 verbose_agent: bool = False # Keep for potential future use
                 ):
        """Initializes the agent."""
        self.model_name = model_name
        self.tools = [t for t in tools if callable(t)]
        if not self.tools:
             print("Warning: No valid tools provided.", file=sys.stderr)
        self.verbose_agent = verbose_agent # Store if needed later
        self.tool_map = {tool.name: tool for tool in self.tools} # Map for easy lookup

        if search_and_scrape_web in self.tools and not brave_search_client:
            print("Warning: Search tool included but is non-functional.", file=sys.stderr)

        try:
            # Initialize LLM simply
            self.llm = ChatOllama(model=model_name, temperature=0)
            # Bind tools for easy use later
            self.llm_with_tools = self.llm.bind_tools(self.tools)
            _ = self.llm.invoke("OK") # Connection check
            print(f"Successfully connected to Ollama model '{self.model_name}'.")
        except Exception as e:
            print(f"Error initializing/connecting to Ollama model '{self.model_name}'. Details: {e}", file=sys.stderr)
            sys.exit(1)

        # Define prompt template (we'll use it to format messages manually)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("placeholder", "{chat_history}"), # Use placeholder for history
            ("human", "{input}")
            # Note: No agent_scratchpad needed in this manual approach
        ])

    def _format_messages(self, task: str, history: List[BaseMessage]) -> List[BaseMessage]:
        """Helper to format messages for the LLM call."""
        # Use invoke to format. `chat_history` expects a list of messages.
        prompt_value = self.prompt.invoke({"input": task, "chat_history": history})
        return prompt_value.to_messages()

    def run(self, task: str) -> Iterator[str]:
        """
        Executes a task, potentially calling tools, and yields the final
        response tokens synchronously by streaming the last LLM call.
        """
        print(f"\n--- Task Received ---\n{task}")
        print("\n--- Agent Response ---")

        # Start with just the human input
        messages: List[BaseMessage] = [HumanMessage(content=task)]

        try:
            # === First LLM Call (Planning/Tool Calling or Direct Answer) ===
            # Format messages including history (which is empty initially)
            formatted_messages = self._format_messages(task, [])
            # Use invoke to get the *complete* first response
            # We don't stream this, as we need to know if tools were called
            first_response: AIMessage = self.llm_with_tools.invoke(formatted_messages)
            messages.append(first_response) # Add AI response to history

            # === Tool Execution (If Needed) ===
            if first_response.tool_calls:
                print("--- Agent: Decided to use tools ---", file=sys.stderr)
                tool_messages = []
                for tool_call in first_response.tool_calls:
                    tool_name = tool_call["name"]
                    if tool_name in self.tool_map:
                        selected_tool = self.tool_map[tool_name]
                        tool_output = selected_tool.invoke(tool_call) # This is the ToolMessage
                        tool_messages.append(tool_output)
                    else:
                        # Handle case where model hallucinates a tool name
                        error_msg = f"Tool '{tool_name}' not found."
                        print(f"--- Agent Error: {error_msg} ---", file=sys.stderr)
                        tool_messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call["id"]))
                messages.extend(tool_messages) # Add tool results to history

                # === Second LLM Call (Generate Final Answer using Tool Results) ===
                print("--- Agent: Streaming final response after tool use ---", file=sys.stderr)
                # Format messages again, now including tool calls and results
                final_formatted_messages = self._format_messages(task, messages[:-len(tool_messages)-1]) # Pass history *before* this turn
                # *** Stream THIS call ***
                for chunk in self.llm_with_tools.stream(final_formatted_messages):
                     if isinstance(chunk, AIMessageChunk) and chunk.content:
                          yield chunk.content
            else:
                # === Direct Answer (No Tools Called) ===
                print("--- Agent: Answering directly (streaming) ---", file=sys.stderr)
                # The first response *was* the final answer, but invoke doesn't stream.
                # So, we stream the same request again.
                formatted_messages = self._format_messages(task, []) # Re-format initial request
                # *** Stream THIS call ***
                for chunk in self.llm_with_tools.stream(formatted_messages):
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                         yield chunk.content

        except Exception as e:
            print(f"\n--- Error during Agent Execution: {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            yield f"\n[Agent Error: {e}]"

# --- Example Usage (Synchronous) ---
def main():
    """Runs example tasks using the LangchainAgent."""
    if not brave_search_client:
         print("\nWARNING: Brave search client not initialized.", file=sys.stderr)

    try:
        langchain_agent = LangchainAgent(model_name="qwen2.5:3b", verbose_agent=False)

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