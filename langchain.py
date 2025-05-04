import sys
import traceback
import requests # For scraping
from bs4 import BeautifulSoup # For parsing scraped HTML
import re # For cleaning scraped text
from typing import List, Optional, Callable, Dict, Any # Added Dict, Any

# Assume brave_search_api.py contains the BraveSearch class from the previous step
# Make sure brave_search_api.py and .env are in the correct path
try:
    from brave_search_api import BraveSearch, BRAVE_API_KEY # Import class and key
except ImportError:
    print("Error: Could not import BraveSearch class. Make sure brave_search_api.py exists.")
    # Fallback for BRAVE_API_KEY if import fails but .env might exist
    from dotenv import load_dotenv
    import os
    load_dotenv()
    BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
    BraveSearch = None # Indicate class is unavailable

# Langchain specific imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.tools import tool, ToolException
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate

# --- Web Scraping Helper (Unchanged from previous version) ---

def _scrape_and_extract_text(url: str, timeout: int = 10, max_chars: int = 4000) -> Optional[str]:
    """
    Fetches content from a URL and extracts meaningful text using BeautifulSoup.
    Handles basic cleaning and error conditions. Returns truncated text or None.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if 'html' not in content_type:
            print(f"--- Skipping scrape (Non-HTML): {url} ({content_type}) ---", file=sys.stderr) # Print info to stderr
            return None

        soup = BeautifulSoup(response.content, 'html.parser')
        for element in soup(["script", "style", "header", "footer", "nav", "aside", "form", "noscript"]): # Added noscript
            element.decompose()

        main_content = soup.find('main') or soup.find('article') or \
                       soup.find('div', attrs={'role': 'main'}) or \
                       soup.find('div', id='content') or \
                       soup.find('div', class_='content') or soup
        text = main_content.get_text(separator=' ', strip=True)
        text = re.sub(r'\s\s+', ' ', text).strip() # Consolidate whitespace more efficiently

        print(f"--- Scraped {len(text)} chars from: {url} ---", file=sys.stderr) # Print info to stderr
        return text[:max_chars]

    except requests.exceptions.Timeout:
        print(f"--- Scraping Error (Timeout): {url} ---", file=sys.stderr)
        return None
    except requests.exceptions.RequestException as e:
        print(f"--- Scraping Error (Request): {url} - {e} ---", file=sys.stderr)
        return None
    except Exception as e:
        print(f"--- Scraping Error (Parsing/Other): {url} - {e} ---", file=sys.stderr)
        # traceback.print_exc(file=sys.stderr) # Optional: print full traceback to stderr for debugging
        return None


# --- Combined Search and Scrape Tool (Refined Error Handling) ---

# Instantiate the BraveSearch client
if BraveSearch and BRAVE_API_KEY:
    try:
        brave_search_client = BraveSearch(api_key=BRAVE_API_KEY)
        print("BraveSearch client initialized.")
    except ValueError as e:
        print(f"Error initializing BraveSearch: {e}", file=sys.stderr)
        brave_search_client = None
else:
    brave_search_client = None
    if not BraveSearch:
        print("Warning: BraveSearch class not available.", file=sys.stderr)
    if not BRAVE_API_KEY:
         print("Warning: BRAVE_API_KEY not found.", file=sys.stderr)


@tool
def search_and_scrape_web(query: str, k: int = 3) -> dict:
    """
    Searches the web using Brave Search for a query, then scrapes the full text content
    from the top 'k' results (max 5). Use this tool ONLY when you need detailed, up-to-date information
    that is likely NOT in your internal knowledge base (e.g., recent news, specific technical details,
    current events). DO NOT use this for simple facts (like capitals), creative writing,
    or summarizing common knowledge you might already possess. Be specific with your query.

    Args:
        query (str): The specific search query string.
        k (int): The number of top results to scrape (default 3, max 5 advised).

    Returns:
        dict: A dictionary with a 'results' key. The value is a list of dictionaries,
              each containing 'url' and 'content' (the scraped text, up to ~4000 chars, or None if failed).

    Raises:
        ToolException: If the Brave API key is missing or if the Brave API search itself fails.
    """
    if not brave_search_client:
         raise ToolException("Brave search client not available (check API key and import). Cannot perform search.")

    print(f"--- TOOL EXECUTING: search_and_scrape_web(query='{query}', k={k}) ---", file=sys.stderr) # Print info to stderr
    num_to_scrape = min(k, 5)
    if num_to_scrape <= 0:
         # You could raise ToolException here too, or return an empty valid result
         # Raising might be cleaner for the agent executor
         raise ToolException("Number of results to scrape (k) must be positive.")

    try:
        # 1. Perform Brave search (can raise ToolException on API/network failure)
        initial_results = brave_search_client.search(query, count=num_to_scrape)
        # No need to check if initial_results is empty here, loop below handles it

        # 2. Scrape content for each result URL
        scraped_results = []
        for result in initial_results: # Loop is safe even if initial_results is empty
            url = result.get("url")
            if url:
                print(f"--- Attempting scrape: {url} ---", file=sys.stderr) # Print info to stderr
                scraped_content = _scrape_and_extract_text(url)
                scraped_results.append({
                    "url": url,
                    "content": scraped_content # Will be None if scraping failed
                })
            else:
                 print("--- Skipping result with no URL ---", file=sys.stderr)

        final_results = {"results": scraped_results}
        print(f"--- TOOL RETURNING {len(scraped_results)} scraped results ---", file=sys.stderr) # Print info to stderr
        return final_results # Success case returns the results

    # Let ToolException from brave_search_client.search propagate
    except Exception as e:
        # Catch *unexpected* errors during the orchestration/scraping loop
        print(f"--- TOOL ERROR (Orchestration/Scraping Loop): {e} ---", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # Re-raise as a ToolException so AgentExecutor knows the tool failed
        raise ToolException(f"An unexpected error occurred within the search/scrape tool: {e}")


# --- The Langchain Agent Class (Streaming Run Method) ---

class LangchainAgent:
    """
    Agent using Langchain, Ollama, and a search+scrape tool.
    Streams the final response to the console.
    """
    def __init__(self,
                 model_name: str = "qwen2.5:3b",
                 tools: List[Callable] = [search_and_scrape_web], # Default to the search tool
                 system_message: str = ( # System prompt remains directive
                     "You are a helpful assistant. Your primary goal is to answer the user directly "
                     "using your internal knowledge IF YOU ARE CONFIDENT in the answer. "
                     "You have access to a tool: `search_and_scrape_web`. "
                     "ONLY use this tool if the user asks for information that is:\n"
                     "1. Real-time or very recent.\n"
                     "2. Highly specific and likely outside your general knowledge.\n"
                     "3. Explicitly requested via a search.\n"
                     "DO NOT use the tool for:\n"
                     "- Simple, common knowledge questions.\n"
                     "- Creative writing tasks.\n"
                     "- Summarizing well-known topics unless asked for *new* info.\n"
                     "Think step-by-step: Can I answer this confidently from my knowledge? If YES, answer directly. If NO, and it fits the criteria, consider the tool. "
                     "If using the tool, briefly state you are searching, then provide the answer based *only* on the tool results."
                 ),
                 verbose: bool = False # Default verbose to False for cleaner streaming output
                 ):
        self.model_name = model_name
        self.tools = [t for t in tools if callable(t)] # Ensure only callables are included
        if not self.tools:
             print("Warning: No valid tools provided to the agent.", file=sys.stderr)
        self.verbose = verbose # Controls AgentExecutor logging, not the final stream

        # Check tool availability vs API key
        if search_and_scrape_web in self.tools and not brave_search_client:
            print("Warning: 'search_and_scrape_web' tool included but not functional (check API key/import). It will raise an error if called.", file=sys.stderr)

        try:
            self.llm = ChatOllama(model=model_name, temperature=0)
            self.llm.invoke("Respond with only 'OK'") # Connection check
            print(f"Successfully connected to Ollama model '{self.model_name}'.")
        except Exception as e:
            print(f"Error: Failed to initialize/connect to Ollama model '{self.model_name}'. Details: {e}", file=sys.stderr)
            sys.exit(1)

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}")
        ])

        # Ensure tools list is not empty before creating agent if needed
        if not self.tools:
             print("Error: Agent requires at least one tool to be functional with create_tool_calling_agent.", file=sys.stderr)
             # Decide how to handle: exit, or proceed without tool calling?
             # For now, let it potentially fail later if tool calling is mandatory
             # Or, conditionally create a different type of agent/chain if no tools?

        self.agent = create_tool_calling_agent(self.llm, self.tools, prompt)

        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=self.verbose, # Controls intermediate step logging
            handle_parsing_errors=True,
            max_iterations=5
        )

    def run(self, task: str) -> None: # Changed return type hint to None
        """
        Executes a task and streams the agent's final response to standard output.
        """
        print(f"\n--- Task Received ---\n{task}")
        print("\n--- Agent Response ---") # Header for the streamed output
        full_response = "" # Optionally accumulate if needed elsewhere

        try:
            # Use agent_executor.stream() which yields intermediate steps and final output chunks
            for chunk in self.agent_executor.stream({"input": task}):
                # Check if the chunk contains final output content
                # The key 'output' is commonly used for the final response chunks
                if output_chunk := chunk.get("output"):
                    # Print the chunk immediately to stdout without a newline
                    sys.stdout.write(output_chunk)
                    sys.stdout.flush() # Ensure it appears immediately
                    full_response += output_chunk # Accumulate if needed

        except Exception as e:
            # Print error information if streaming fails
            print(f"\n--- Error during Agent Execution: {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            # Optionally print a message to stdout as well
            print(f"\n[Agent Error: {e}]")

        finally:
            # Ensure a newline is printed at the very end of the response stream
            print()
        # No return value needed as output is printed directly
        # If accumulation is needed: return full_response


# --- Example Usage ---
if __name__ == "__main__":
    # Initial check for API key availability
    if not brave_search_client:
         print("\nWARNING: Brave search client is not initialized. The search tool will not work.", file=sys.stderr)
         # Decide if you want to exit or continue without search functionality
         # sys.exit(1) # Uncomment to exit if search is mandatory

    try:
        # Set verbose=False for cleaner streaming output, True for debugging steps
        langchain_agent = LangchainAgent(model_name="qwen2.5:3b", verbose=False)

        print("\n" + "="*50)
        task1 = "What is the capital of France?"
        langchain_agent.run(task1) # Call run, output is printed live
        print("\n" + "="*50) # Separator printed after streaming finishes

        task2 = "What are the latest developments regarding the Artemis program missions?"
        langchain_agent.run(task2)
        print("\n" + "="*50)

        task3 = "Write a short haiku about a web scraping robot."
        langchain_agent.run(task3)
        print("\n" + "="*50)

        task4 = "Are there any recent news articles discussing the plot or reception of the movie 'Dune: Part Two'?"
        langchain_agent.run(task4)
        print("\n" + "="*50)

    except SystemExit:
        print("Exiting due to configuration error.", file=sys.stderr)
    except Exception as e:
        print(f"\nAn unexpected error occurred in the main block: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)