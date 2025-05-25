# --- START OF FILE planner_agent.py ---
import sys
import os
# import shutil # Not currently used
import traceback
from typing import List, Callable, Iterator, Dict, Any
import time
from datetime import datetime, timedelta
import json

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage
from langchain_core.tools import BaseTool

# Tool imports from the corrected planner tools file
from planner_tools import active_planner_tools

# Model names and config import
from config import PLANNER_MODEL_NAME, VERBOSE # Use the planner model

class PlannerAgent:
    """
    Agent focused on planning complex, multi-step tasks using specialized tools.
    It leverages a reasoning-oriented LLM and tools for weather, routing, operational details,
    calendar events, and general web search as a fallback.
    Prioritizes logical coherence and uses status indicators during execution.
    """
    def __init__(self,
                 model_name: str = PLANNER_MODEL_NAME,
                 tools: List[BaseTool] = active_planner_tools,
                 # UPDATED System Prompt with stronger instructions
                 system_message: str = (
                    "You are an expert, methodical planning assistant. Your primary objective is to construct comprehensive and actionable plans in response to user requests (e.g., travel itineraries, event schedules, research outlines).\n"
                    "To achieve this, you will:\n"
                    "1.  Analyze the user's request to identify all information needs, constraints, and specific dates/times. Pay close attention to relative dates (e.g., 'next Saturday') and anchor them to the current date if provided in the conversation history.\n"
                    "2.  Strategically utilize the available specialized tools to gather the necessary data. **Refer to each tool's description (docstring) to understand its purpose, required arguments, expected output, and any specific formatting notes for its results.**\n" # Highlighted change
                    "3.  If specialized tools are insufficient or not applicable for a piece of information, use the `general_web_search` tool as a fallback.\n"
                    "4.  Sequentially call tools, analyze their outputs, and decide if further tool calls are needed to fully address the request.\n"
                    "5.  Synthesize all gathered information, including precise details from tool outputs (like URLs, specific weather data, route timings), into a single, coherent, well-structured, and detailed textual plan. This plan is your final output for this stage and will be passed to another AI for presentation.\n\n"
                    "**Core Directives for Your Operation:**\n"
                    "-   **Goal Completion & Accuracy:** Your paramount task is to ensure the generated plan fully and accurately addresses all aspects of the user's original request, including precise dates and times. Iterate with tools until all necessary information is gathered and validated against the request.\n"
                    "-   **Tool Argumentation:** Strictly adhere to the argument requirements specified in each tool's description. If critical information for a tool's arguments is missing from the user's request (e.g., specific dates or times when a tool requires them), you MUST ask the user for clarification before attempting to call that tool.\n"
                    "-   **Status Updates (Optional but Recommended):** For clarity during complex operations, you MAY insert brief status messages *before* a tool call, like `<Invoking get_weather_forecast_daily for Paris...>`.\n"
                    "-   **Output for Handoff:** Your final response should be the synthesized plan, rich in detail, facts, and any relevant links obtained from tools. Avoid conversational fluff, apologies, or self-commentary about your process. Focus on delivering complete, structured information.\n"
                    "-   **Error Handling:** If a tool call results in an error, report the error content. Then, assess if an alternative tool or approach can be used (e.g., simplifying a location name for geocoding), or if you need to inform the user that a part of their request cannot be fulfilled due to the tool error.\n\n"
                    "Begin by analyzing the user's request, paying close attention to any date/time specifics, and plan your tool usage by carefully reading each tool's description for guidance."
                 ),
                 verbose_agent: bool = VERBOSE,
                 max_iterations: int = 8
                 ):
        self.model_name = model_name
        self.verbose_agent = verbose_agent
        self.max_iterations = max_iterations

        self.tools = tools
        if not self.tools:
            if self.verbose_agent: print("--- Planner Agent Warning: No valid tools provided or loaded. Functionality will be limited. ---", file=sys.stderr)
            self.tool_map = {}
        else:
            # Check if tools have .name attribute (they should if decorated with @tool)
            self.tool_map = {}
            valid_tools_list = []
            for t in self.tools:
                if hasattr(t, 'name'):
                    self.tool_map[t.name] = t
                    valid_tools_list.append(t.name)
                else:
                     if self.verbose_agent: print(f"--- Planner Agent Warning: Provided tool {t} lacks a 'name' attribute. Skipping. ---", file=sys.stderr)
            if self.verbose_agent and valid_tools_list:
                print(f"--- Planner Agent: Tools configured: {valid_tools_list} ---", file=sys.stderr)


        self.llm_with_tools = None # Initialize to None
        try:
            self.llm = ChatOllama(model=model_name, temperature=0.1, request_timeout=120.0)
            if self.tool_map: # Only bind tools if the tool map is not empty
                self.llm_with_tools = self.llm.bind_tools(list(self.tool_map.values()))
                if self.verbose_agent: print(f"--- Planner Agent: Successfully initialized Ollama model '{self.model_name}' and bound tools. ---")
            else:
                self.llm_with_tools = self.llm # Use LLM without tools if map is empty
                if self.verbose_agent: print(f"--- Planner Agent: Initialized Ollama model '{self.model_name}' WITHOUT binding tools (none available or valid). ---")

        except Exception as e:
            print(f"--- Planner Agent CRITICAL ERROR: Error initializing/connecting to Ollama model '{self.model_name}'. Agent cannot function. Details: {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            # self.llm_with_tools remains None

        # Define the main prompt template
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("placeholder", "{chat_history}"),
        ])

    def _invoke_tool(self, tool_call: Dict[str, Any]) -> ToolMessage:
        """Helper function to safely invoke a tool and return a ToolMessage."""
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id", f"tool_call_{time.time_ns()}") # Ensure ID exists

        if not tool_name:
            return ToolMessage(content="Error: Tool call missing name.", tool_call_id=tool_call_id)
        if tool_name not in self.tool_map:
            return ToolMessage(content=f"Error: Tool '{tool_name}' not found or not active in agent.", tool_call_id=tool_call_id)

        selected_tool = self.tool_map[tool_name]
        tool_start_time = time.time()
        if self.verbose_agent: print(f"\n--- Planner Agent: Invoking tool '{tool_name}' with args: {tool_args} (Call ID: {tool_call_id}) ---", file=sys.stderr)

        try:
            # Use invoke with the args dictionary
            output = selected_tool.invoke(tool_args)
            # Ensure output is string
            output_content = str(output)

            # Simple truncation if needed (can be adjusted)
            if len(output_content) > 4000:
                 if self.verbose_agent: print(f"--- Planner Agent: Truncating tool output from {len(output_content)} chars. ---", file=sys.stderr)
                 output_content = output_content[:3950] + "... [output truncated]"

            if self.verbose_agent: print(f"--- Planner Agent: Tool '{tool_name}' completed in {time.time() - tool_start_time:.2f}s ---", file=sys.stderr)
            return ToolMessage(content=output_content, tool_call_id=tool_call_id)

        except Exception as e:
            # Catch The  ValidationErrors specifically if possible (though invoke might wrap it)
            error_msg = f"Error executing tool '{tool_name}': {e}"
            # Include traceback for easier debugging of tool errors
            detailed_error = f"{error_msg}\nTraceback:\n{traceback.format_exc()}"
            if self.verbose_agent:
                print(f"--- Planner Agent Tool Execution Error: {error_msg} ---", file=sys.stderr)
                # Optionally print full traceback only if verbose
                # print(f"Full Traceback:\n{traceback.format_exc()}", file=sys.stderr)

            # Return the error message *without* the full traceback to the LLM,
            # but keep the core error type/message.
            return ToolMessage(content=error_msg, tool_call_id=tool_call_id)


    def run(self, task: str, chat_history: List[BaseMessage] = None) -> Iterator[str]:
        """
        Executes a planning task, potentially involving multiple tool calls,
        and streams the final response including status updates.
        Manages conversation history.
        """
        # === Initial Check ===
        if not self.llm_with_tools: # Check if LLM failed to initialize in __init__
            yield "[Planner Agent Error: LLM not initialized. Cannot process task. Please check Ollama connection and model name.]"
            return

        if chat_history is None:
            chat_history = []

        if self.verbose_agent:
            print(f"\n--- Planner Task Received ---\n{task}")
            if chat_history: print(f"--- Using provided history ({len(chat_history)} messages) ---")
            print("\n--- Planner Agent Response ---")

        start_time = time.time()
        # Start with history and add current task as HumanMessage
        messages: List[BaseMessage] = chat_history + [HumanMessage(content=task)]

        # --- Agent Execution Loop ---
        try:
            for iteration in range(self.max_iterations):
                if self.verbose_agent: print(f"\n--- Planner Agent Iteration {iteration + 1}/{self.max_iterations} ---", file=sys.stderr)

                # Prepare messages for the LLM call using the template
                # The placeholder should contain all previous messages (system, human, ai, tool)
                current_prompt_messages = self.prompt_template.format_messages(chat_history=messages)

                if self.verbose_agent:
                    print(f"--- Planner Agent: Calling LLM with {len(current_prompt_messages)} messages. ---", file=sys.stderr)
                    # Optional: Log message details for debugging history
                    # for i, m in enumerate(current_prompt_messages):
                    #      print(f"    Msg {i}: Type={type(m).__name__}, Content='{str(m.content)[:150]}...'")


                # === LLM Call (Streaming) ===
                stream = self.llm_with_tools.stream(current_prompt_messages)

                ai_response_chunks: List[AIMessageChunk] = []
                accumulated_content = ""
                has_tool_calls_in_stream = False # Track if tool chunks appear

                # Consume the stream, yield content chunks, collect full AI message
                for chunk in stream:
                    if isinstance(chunk, AIMessageChunk):
                        ai_response_chunks.append(chunk)
                        if chunk.content:
                            accumulated_content += chunk.content
                            yield chunk.content # Stream text content immediately
                        # Check for tool call *chunks* during streaming
                        if chunk.tool_call_chunks:
                            has_tool_calls_in_stream = True
                            # If verbose, maybe log the chunk details
                            # if self.verbose_agent: print(f"--- Planner Agent: Received tool call chunk: {chunk.tool_call_chunks} ---", file=sys.stderr)
                    else:
                        # Log unexpected chunk types if necessary
                        if self.verbose_agent: print(f"--- Planner Agent Warning: Received unexpected chunk type: {type(chunk)} ---", file=sys.stderr)

                # === Reconstruct the full AIMessage from chunks ===
                if not ai_response_chunks:
                    yield "\n[Planner Agent Error: LLM response stream was empty or invalid.]"
                    if self.verbose_agent: print("--- Planner Agent Error: LLM stream yielded no AIMessageChunks. ---", file=sys.stderr)
                    return # Stop processing if the stream was bad

                # Combine chunks to get the final AI message state for this turn
                final_ai_message: AIMessageChunk = ai_response_chunks[0]
                for chunk_part in ai_response_chunks[1:]:
                    # Use the += operator defined for AIMessageChunk
                    final_ai_message = final_ai_message + chunk_part

                # Add the *complete* reconstructed AI response to history for the *next* iteration
                messages.append(final_ai_message)

                # === Tool Check and Execution (based on the *final* reconstructed message) ===
                tool_calls = final_ai_message.tool_calls # Get tool calls from the combined message

                # Debugging log
                # if self.verbose_agent:
                #     print(f"--- Planner Agent: Final AI Message Content='{final_ai_message.content[:100]}...', Tool Calls={tool_calls}, Had Tool Chunks={has_tool_calls_in_stream} ---", file=sys.stderr)


                if not tool_calls:
                    # LLM finished or decided no tools needed
                    if self.verbose_agent: print("--- Planner Agent: LLM finished processing or no tools requested in final message. ---", file=sys.stderr)
                    # Ensure a newline if content was streamed previously and loop is ending
                    if accumulated_content and not accumulated_content.endswith('\n'): yield "\n"
                    break # Exit the loop, we have the final answer

                else:
                    # LLM requested tools
                    if self.verbose_agent: print(f"--- Planner Agent: LLM requested {len(tool_calls)} tool(s) in final message: {[tc.get('name', 'Unnamed Tool') for tc in tool_calls]} ---", file=sys.stderr)

                    tool_messages_for_history = []
                    for tool_call in tool_calls:
                        # Ensure tool_call has the expected dictionary structure
                        if isinstance(tool_call, dict) and "name" in tool_call and "args" in tool_call and "id" in tool_call:
                            # Invoke the tool and get the ToolMessage result (includes content or error)
                            tool_result_message = self._invoke_tool(tool_call)
                            tool_messages_for_history.append(tool_result_message)
                        else:
                            # Handle malformed tool calls if they somehow occur
                            error_content = f"Error: Agent received malformed tool call structure from LLM: {tool_call}"
                            if self.verbose_agent: print(f"--- Planner Agent Error: {error_content} ---", file=sys.stderr)
                            # Try to create a ToolMessage with an error, using a placeholder ID if needed
                            tc_id = tool_call.get("id", f"malformed_tc_{time.time_ns()}") if isinstance(tool_call, dict) else f"malformed_tc_{time.time_ns()}"
                            tool_messages_for_history.append(ToolMessage(content=error_content, tool_call_id=tc_id))

                    # Add tool results to history for the next LLM iteration
                    messages.extend(tool_messages_for_history)
                    # Continue the loop to let the LLM process the tool results

            else: # Loop finished without break (max_iterations reached)
                if self.verbose_agent: print(f"--- Planner Agent: Reached max iterations ({self.max_iterations}). Returning current state. ---", file=sys.stderr)
                yield f"\n[Planner Agent Warning: Reached maximum iterations ({self.max_iterations}). The plan might be incomplete or stuck.]"

            # Final output after loop finishes (either by break or max_iterations)
            if self.verbose_agent: print(f"\n--- Planner Agent Finished Task. Total time: {time.time() - start_time:.2f}s ---", file=sys.stderr)

        except Exception as e:
            # Catch unexpected errors in the main loop/streaming
            print(f"\n--- CRITICAL Error during Planner Agent Execution (in run loop): {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            yield f"\n[Planner Agent Error: An unexpected error occurred during execution. Cannot continue. Details: {e}]"


# --- Example Usage ---
def main():
    try:
        # Instantiate the planner agent
        # Set verbose=True for detailed logging during tests
        planner = PlannerAgent(verbose_agent=True)

        separator = "\n" + "="*70 + "\n"

        # --- Test Case 1: Simple Planning (Girona/Barcelona) ---
        task1 = "Plan a day trip to Girona from Barcelona for next Saturday. Check the weather and suggest a possible train or car route."
        print(separator + f"Running task 1: {task1}" + separator)
        history1 = []
        for token in planner.run(task1, chat_history=history1):
            print(token, end="", flush=True)
        print(separator)
        # Ideally, you'd capture the full response and add to history for follow-up
        # full_response_1 = "".join(list(planner.run(task1, chat_history=history1)))
        # history1.append(HumanMessage(content=task1))
        # history1.append(AIMessage(content=full_response_1))
        # print(f"History 1 after task: {history1}")


        # --- Test Case 2: More Complex Planning (Paris/London) ---
        # Using a future date relative to now might be better than fixed date
        # Find next Saturday's date (example)
        today = datetime.now().date()
        days_until_saturday = (5 - today.weekday() + 7) % 7
        next_saturday = today + timedelta(days=days_until_saturday)
        next_sunday = next_saturday + timedelta(days=1)
        sat_str = next_saturday.strftime('%Y-%m-%d')
        sun_str = next_sunday.strftime('%Y-%m-%d')

        task15 = "I want to plan a weekend trip to Paris for the upcoming weekend. "
        print(separator + f"Calculating next Saturday ({sat_str}) and Sunday ({sun_str}) dates..." + separator)
        history15 = []
        for token in planner.run(task15, chat_history=history15):
            print(token, end="", flush=True)
        print(separator)

        task2 = (f"I want to plan a weekend trip to Paris for the upcoming weekend ({sat_str} to {sun_str}). "
                 f"Can you suggest an itinerary including travel from London? Check the weather for Paris on those dates, "
                 f"find opening hours for the Eiffel Tower, and add a placeholder event to my calendar for visiting it "
                 f"on Saturday afternoon (e.g., {sat_str} 15:00:00).")
        print(separator + f"Running task 2: {task2}" + separator)
        history2 = []
        for token in planner.run(task2, chat_history=history2):
             print(token, end="", flush=True)
        print(separator)

        # --- Test Case 3: Using Fallback Search ---
        task3 = "Find information about the annual 'La Mercè' festival in Barcelona. When does it usually happen and what are typical activities?"
        print(separator + f"Running task 3: {task3}" + separator)
        history3 = []
        for token in planner.run(task3, chat_history=history3):
             print(token, end="", flush=True)
        print(separator)

    except SystemExit:
        print("Exiting due to configuration or initialization error.", file=sys.stderr)
    except Exception as e:
        print(f"\nAn unexpected error occurred in the main block of planner_agent.py: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
    # Ensure .env file has necessary API keys:
    # OPEN_WEATHER_API_KEY=your_owm_key
    # OPEN_ROUTE_SERVICE_API_KEY=your_ors_key
    # BRAVE_API_KEY=your_brave_key (optional for general_web_search)
    # Ensure config.py defines PLANNER_MODEL_NAME and VERBOSE
    main()

# --- END OF FILE planner_agent.py ---