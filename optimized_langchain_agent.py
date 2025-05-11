import sys
import traceback
from typing import List, Callable, Iterator
import time
import json

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage

# Tool imports
from tools import brave_tool, search_and_scrape_web, find_interesting_links

# Model names import
from config import MAIN_MODEL, LAYOUT_MODEL, VERBOSE

class OptimizedLangchainAgent:
    """
    Optimized Agent using Langchain, Ollama, and search tools.
    Includes performance improvements for faster processing of search results.
    """
    def __init__(self,
                 model_name: str = MAIN_MODEL,
                 layout_model: str = LAYOUT_MODEL,
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
                 verbose_agent: bool = VERBOSE
                 ):
        """Initializes the agent with optimized parameters."""
        self.model_name = model_name
        self.tools = [t for t in tools if callable(t)]
        if not self.tools:
            print("Warning: No valid tools provided.", file=sys.stderr)
        self.verbose_agent = verbose_agent
        self.tool_map = {tool.name: tool for tool in self.tools}

        try:
            # Initialize LLM with optimized parameters
            self.llm = ChatOllama(model=model_name, temperature=0.2)
            # Bind tools for easy use later
            self.llm_with_tools = self.llm.bind_tools(self.tools)
            _ = self.llm.invoke("OK")  # Simple connection check
            if self.verbose_agent: print(f"Successfully connected to Ollama model '{self.model_name}'.")
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

    # def _truncate_tool_results(self, messages: List[BaseMessage]) -> List[BaseMessage]:
    #     """Helper to truncate tool results to improve processing speed."""
    #     truncated_messages = []
    #     for msg in messages:
    #         if isinstance(msg, ToolMessage):
    #             # Try to extract just the essential information from tool results
    #             try:
    #                 content = msg.content
    #                 # If it's JSON-like and very long, try to extract just key portions
    #                 if isinstance(content, str) and len(content) > 1000 and (content.startswith('{') or content.startswith('[')):
    #                     # Keep just the beginning portion that likely contains the most relevant info
    #                     truncated_content = content[:1000] + "... [truncated for efficiency]"
    #                     new_msg = ToolMessage(content=truncated_content, tool_call_id=msg.tool_call_id)
    #                     truncated_messages.append(new_msg)
    #                 else:
    #                     truncated_messages.append(msg)
    #             except:
    #                 # If any issues, keep original message
    #                 truncated_messages.append(msg)
    #         else:
    #             truncated_messages.append(msg)
    #     return truncated_messages

    def run(self, task: str) -> Iterator[str]:
        """
        Executes a task with optimized processing for faster responses.
        Always attempts to find interesting links for most queries.
        """
        if self.verbose_agent:
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
                if self.verbose_agent: print("--- Agent: Decided to use tools ---", file=sys.stderr)
                tool_messages = []
                for tool_call in first_response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_start = time.time()
                    if self.verbose_agent: print(f"--- Agent: Calling tool '{tool_name}' ---", file=sys.stderr)
                    if tool_name in self.tool_map:
                        selected_tool = self.tool_map[tool_name]
                        tool_output = selected_tool.invoke(tool_call)
                        tool_messages.append(tool_output)
                        tool_used = True
                        if self.verbose_agent: print(f"--- Agent: Tool '{tool_name}' completed in {time.time() - tool_start:.2f}s ---", file=sys.stderr)
                    else:
                        error_msg = f"Tool '{tool_name}' not found."
                        if self.verbose_agent: print(f"--- Agent Error: {error_msg} ---", file=sys.stderr)
                        tool_messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call["id"]))
                messages.extend(tool_messages)
                
                # Check if find_interesting_links was NOT called but task is informational
                # This ensures we always try to include relevant links
                link_tool_called = any(tc["name"] == "find_interesting_links" for tc in first_response.tool_calls)
                
                if not link_tool_called and tool_used and "find_interesting_links" in self.tool_map:
                    if self.verbose_agent: print("--- Agent: Automatically finding interesting links ---", file=sys.stderr)
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
                        if self.verbose_agent: print(f"--- Agent: Auto link finding failed: {e} ---", file=sys.stderr)

                # === Optimization: Apply truncation to tool results ===
                # optimized_messages = self._truncate_tool_results(messages)
                optimized_messages = messages
                
                # === Second LLM Call with special prompt for processing tool results ===
                process_start = time.time()
                if self.verbose_agent: print("--- Agent: Processing search results and links ---", file=sys.stderr)
                final_formatted_messages = self._format_messages(task, optimized_messages, is_tool_processing=True)
                # Stream the response
                if self.verbose_agent: print("--- Agent: Streaming final response ---", file=sys.stderr)
                for chunk in self.llm.stream(final_formatted_messages):
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        yield chunk.content
                
                if self.verbose_agent: print(f"--- Processing completed in {time.time() - process_start:.2f}s ---", file=sys.stderr)
            else:
                # === Even for direct answers, try to find relevant links ===
                if self.verbose_agent: print("--- Agent: Answering directly but still finding links ---", file=sys.stderr)
                
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
                            if self.verbose_agent: print(f"--- Agent: Link processing error: {e} ---", file=sys.stderr)
                            # Don't show error to user - just continue
                    except Exception as e:
                        if self.verbose_agent: print(f"--- Agent: Link finding failed: {e} ---", file=sys.stderr)
                        # Don't show error to user - just continue

            if self.verbose_agent: print(f"--- Total time: {time.time() - start_time:.2f}s ---", file=sys.stderr)

        except Exception as e:
            print(f"\n--- Error during Agent Execution: {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            yield f"\n[Agent Error: {e}]"


# --- Example Usage ---
def main():
    try:
        langchain_agent = OptimizedLangchainAgent()

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