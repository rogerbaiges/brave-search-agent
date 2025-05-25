# --- START OF FILE planner_agent.py ---
import sys
import os
# import shutil # Not currently used
import traceback
from typing import List, Callable, Iterator, Dict, Any
import time
from datetime import datetime, timedelta
import json
# from datetime import datetime, timedelta # Already imported above

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage, SystemMessage # Added SystemMessage
from langchain_core.tools import BaseTool

# Tool imports from the corrected planner tools file
from planner_tools import active_planner_tools

# Model names and config import
from config import PLANNER_MODEL_NAME, VERBOSE # Use the planner model

# --- Guidance Profiles (Could be in a separate file like guidance_profiles.py) ---
GUIDANCE_PROFILES = {
    "TravelPlanning": """
[TASK GUIDANCE FOR: TRAVEL PLANNING]
Focus Points:
-   Destinations & Exact Dates: Confirm and use precisely. Resolve locations robustly.
-   Transportation: Use `plan_route_ors`. Consider flights for long distances. Offer viable options.
-   Accommodation (Conceptual): Note the need. Actual booking out of scope for current tools.
-   Weather: Always call `get_weather_forecast_daily` for relevant dates and locations.
-   Itinerary Points: Use `get_operational_details` for POIs, `add_calendar_event` for key items.
-   Proactive: Suggest 1-2 relevant POIs. Offer calendar adds.
-   Output: Structure as a day-by-day HTML itinerary if applicable.
[END TRAVEL GUIDANCE]
""",
    "ShoppingComparison": """
[TASK GUIDANCE FOR: SHOPPING COMPARISON]
Focus Points:
-   Products: Identify products clearly.
-   Comparison Criteria: Determine or ask for price, features, reviews.
-   Information Sourcing: Use `general_web_search` and `extended_web_search` for product details and reviews from reliable sources.
-   Output Structure: Present as an HTML comparison table or structured list highlighting pros/cons for each criterion.
[END SHOPPING GUIDANCE]
""",
    "EventScheduling": """
[TASK GUIDANCE FOR: EVENT SCHEDULING]
Focus Points:
-   Event Core Details: Confirm event name, purpose, specific date(s), start AND end times (CRITICAL for `add_calendar_event`).
-   Location Details: If physical, use `get_operational_details`. If travel needed, use `plan_route_ors`.
-   Calendar Integration: Always offer `add_calendar_event` once all details are firm. Ensure the HTML output contains the clickable link correctly.
[END EVENT GUIDANCE]
""",
    "ResearchAndSummarize": """
[TASK GUIDANCE FOR: RESEARCH & SUMMARIZE]
Focus Points:
-   Understand Core Question: Clarify if ambiguous.
-   Tool Prioritization: Use `general_web_search` for broad overview, `extended_web_search` for depth on specific results, `news_search` for current events.
-   Information Synthesis: Combine information from multiple sources if necessary, providing a comprehensive answer in HTML.
-   Citation: Always provide source URLs as HTML links.
[END RESEARCH GUIDANCE]
""",
    "DefaultGuidance": """
[TASK GUIDANCE: GENERAL PLANNING]
Focus on fully understanding the user's primary goal.
Methodically use available tools to gather all necessary information.
Synthesize findings into a clear, structured HTML response that addresses the user's request.
[END GENERAL GUIDANCE]
"""
}
# --- End of Guidance Profiles ---

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
                 system_message_template: str = ( # This remains the main system prompt
                    "You are an expert, methodical, and proactive planning assistant. Your primary objective is to construct comprehensive, actionable, and insightful plans in response to user requests (e.g., travel itineraries, event schedules, research outlines), **outputting your final plan directly as well-structured HTML.**\n"
                    "CURRENT DATE CONTEXT: Today is {current_date_verbose}. The upcoming weekend is {upcoming_saturday_date} (Saturday) and {upcoming_sunday_date} (Sunday).\n\n"
                    "To achieve your objective, you will:\n"
                    "1.  Thoroughly analyze the user's request to identify all explicit and implicit information needs, constraints, and specific dates/times. Pay close attention to relative dates (e.g., 'next Saturday', 'tomorrow') and accurately anchor them using the CURRENT DATE CONTEXT provided above. Additional task-specific guidance may be provided in the conversation history.\n"
                    "2.  Strategically utilize the available specialized tools to gather necessary data. Refer to each tool's description (docstring) AND any task-specific guidance to understand its purpose, required arguments, and expected output.\n"
                    "3.  If specialized tools are insufficient or not applicable for a piece of information, use the `general_web_search` tool as a fallback.\n"
                    "4.  Sequentially call tools, analyze their outputs, and decide if further tool calls are needed to fully address the request and potentially enhance the plan (see Proactive Assistance and task-specific guidance).\n"
                    "5.  **Synthesize all gathered information into a single, coherent, well-structured, and detailed HTML document. This HTML is your final output. Use semantic HTML tags like `<h1>`, `<p>`, `<ul>`, `<li>`, `<table>`, `<a>`, etc., appropriately. For example, structure different parts of the plan with headings, use lists for itineraries or options, and tables for comparative data if suitable. Ensure all links are properly formatted as `<a href=\"URL\">Descriptive Text</a>`.**\n\n"
                    "**Core Directives for Your Operation:**\n"
                    "-   **Proactive Assistance & Anticipation:** Go beyond the literal request, informed by any task-specific guidance. If planning a trip, proactively consider and suggest checking weather (if not asked), adding key events to a calendar (if appropriate), or briefly mentioning 1-2 highly relevant points of interest. Integrate these suggestions naturally into your HTML plan.\n"
                    "-   **Goal Completion & Accuracy:** Your paramount task is to ensure the generated HTML plan fully and accurately addresses all aspects of the user's original request, including precise dates and times based on the CURRENT DATE CONTEXT.\n"
                    "-   **Tool Argumentation:** Strictly adhere to the argument requirements specified in each tool's description. If critical information for a tool's arguments is missing, you MUST ask the user for clarification before attempting to call that tool.\n"
                    "-   **HTML Link Formatting:** When tools provide URLs (e.g., calendar links from `add_calendar_event`, search result URLs from `general_web_search`), you MUST embed these as proper HTML anchor tags in your output: `<a href=\"THE_URL_FROM_TOOL\" target=\"_blank\">Relevant Link Text</a>`. For the `add_calendar_event` tool, use link text like 'Add to Google Calendar'.\n"
                    "-   **Status Updates (Optional but Recommended):** You MAY insert brief status messages *before* a tool call, like `<!-- <Invoking get_weather_forecast_daily for Paris...> -->`. **Note: If you use status updates, wrap them in HTML comments `<!-- ... -->` so they don't render in the final HTML output.**\n"
                    "-   **Final HTML Output Only:** Your entire response MUST be only the HTML document. Do not include any preambles (like 'Here is the HTML plan:'), apologies, or self-commentary outside of HTML comments. Start directly with an HTML tag (e.g., `<!DOCTYPE html><html><head>...</head><body><h1>...` or just the `<body>` content like `<h1>...` if a full document is not required by the frontend).\n"
                    "-   **Error Handling:** If a tool call results in an error, report the error content within a `<p class=\"error\">Tool Error: ...</p>` tag or similar descriptive HTML structure. Then, assess if an alternative tool or approach can be used, or if you need to inform the user (within the HTML plan) that a part of their request cannot be fulfilled.\n\n"
                    "Begin by analyzing the user's request, utilizing the CURRENT DATE CONTEXT, and plan your tool usage. Your final deliverable is a complete HTML plan."
                 ),
                 verbose_agent: bool = VERBOSE,
                 max_iterations: int = 8
                 ):
        self.model_name = model_name
        self.verbose_agent = verbose_agent
        self.max_iterations = max_iterations

        now = datetime.now()
        current_date_verbose = now.strftime('%A, %B %d, %Y')
        days_until_saturday = (5 - now.weekday() + 7) % 7
        upcoming_saturday = now + timedelta(days=days_until_saturday)
        upcoming_sunday = upcoming_saturday + timedelta(days=1)
        upcoming_saturday_date = upcoming_saturday.strftime('%Y-%m-%d')
        upcoming_sunday_date = upcoming_sunday.strftime('%Y-%m-%d')

        self.system_message_formatted = system_message_template.format(
            current_date_verbose=current_date_verbose,
            upcoming_saturday_date=upcoming_saturday_date,
            upcoming_sunday_date=upcoming_sunday_date
        )

        self.tools = tools
        self.tool_map = {t.name: t for t in self.tools if hasattr(t, 'name')}
        if len(self.tool_map) != len(tools) and self.verbose_agent:
            print(f"--- Planner Agent Warning: Some provided tools lacked a 'name' attribute and were skipped. ---", file=sys.stderr)
        if self.verbose_agent and self.tool_map:
            print(f"--- Planner Agent: Tools configured: {list(self.tool_map.keys())} ---", file=sys.stderr)
        elif self.verbose_agent:
            print("--- Planner Agent Warning: No valid tools configured. ---", file=sys.stderr)

        self.llm = None
        self.llm_with_tools = None
        try:
            self.llm = ChatOllama(model=model_name, temperature=0.1, request_timeout=120.0)
            if self.tool_map:
                self.llm_with_tools = self.llm.bind_tools(list(self.tool_map.values()))
            else:
                self.llm_with_tools = self.llm # Will run without tool calling capability if no tools
            if self.verbose_agent: print(f"--- Planner Agent: Successfully initialized Ollama model '{self.model_name}'. Tools bound: {bool(self.tool_map)} ---")
        except Exception as e:
            print(f"--- Planner Agent CRITICAL ERROR: Initializing model '{self.model_name}': {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", self.system_message_formatted), # Use the pre-formatted system message
            ("placeholder", "{chat_history}"),
        ])

    @staticmethod
    def select_planning_guidance(user_query: str, llm_instance: ChatOllama, available_categories: List[str]) -> str:
        """
        Uses an LLM to analyze the user query and select the most appropriate
        planning guidance profile.
        """
        if not llm_instance: # Handle case where LLM might not be initialized
            if VERBOSE: print("--- select_planning_guidance: LLM instance not available. Using default guidance. ---", file=sys.stderr)
            return GUIDANCE_PROFILES["DefaultGuidance"]

        categories_str = ", ".join(available_categories)
        # Using a simpler model for classification might be faster, but using self.llm for now
        classification_prompt_template = ChatPromptTemplate.from_messages([
            SystemMessage(
                content=f"You are an assistant that classifies a user's planning query into one of the following categories: [{categories_str}]. "
                        f"Respond with ONLY the category name that best fits the query. For example, if the query is about organizing a holiday, respond 'TravelPlanning'."
            ),
            HumanMessage(content=f"User query: \"{user_query}\"")
        ])
        
        try:
            # Ensure messages are correctly formatted for invoke/stream
            formatted_prompt = classification_prompt_template.format_messages()
            response = llm_instance.invoke(formatted_prompt) # Use the base LLM for this simple task
            determined_category = response.content.strip()
            
            if determined_category in GUIDANCE_PROFILES:
                if VERBOSE: print(f"--- Guidance Selection LLM chose: {determined_category} for query: '{user_query[:50]}...' ---", file=sys.stderr)
                return GUIDANCE_PROFILES[determined_category]
            else:
                if VERBOSE: print(f"--- Guidance Selection LLM returned an unknown or poorly formatted category: '{determined_category}'. Using default guidance. ---", file=sys.stderr)
                return GUIDANCE_PROFILES["DefaultGuidance"]
        except Exception as e:
            if VERBOSE: print(f"--- Error during LLM-based guidance selection: {e}. Using default guidance. ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return GUIDANCE_PROFILES["DefaultGuidance"]

    def _invoke_tool(self, tool_call: Dict[str, Any]) -> ToolMessage:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id", f"tool_call_{time.time_ns()}")

        if not tool_name:
            return ToolMessage(content="Error: Tool call missing name.", tool_call_id=tool_call_id)
        if tool_name not in self.tool_map:
            return ToolMessage(content=f"Error: Tool '{tool_name}' not found or not active in agent.", tool_call_id=tool_call_id)

        selected_tool = self.tool_map[tool_name]
        tool_start_time = time.time()
        if self.verbose_agent: print(f"\n--- Planner Agent: Invoking tool '{tool_name}' with args: {tool_args} (Call ID: {tool_call_id}) ---", file=sys.stderr)

        try:
            output = selected_tool.invoke(tool_args)
            output_content = str(output)
            if len(output_content) > 4000: # Truncation
                 if self.verbose_agent: print(f"--- Planner Agent: Truncating tool output from {len(output_content)} chars. ---", file=sys.stderr)
                 output_content = output_content[:3950] + "... [output truncated]"
            if self.verbose_agent: print(f"--- Planner Agent: Tool '{tool_name}' completed in {time.time() - tool_start_time:.2f}s ---", file=sys.stderr)
            return ToolMessage(content=output_content, tool_call_id=tool_call_id)
        except Exception as e:
            error_msg = f"Error executing tool '{tool_name}': {e}"
            if self.verbose_agent: print(f"--- Planner Agent Tool Execution Error: {error_msg} ---", file=sys.stderr)
            return ToolMessage(content=error_msg, tool_call_id=tool_call_id)

    def run(self, task: str, chat_history: List[BaseMessage] = None) -> Iterator[str]:
        if not self.llm_with_tools:
            yield "[Planner Agent Error: LLM with tools not initialized. Cannot process task.]"
            return
        if not self.llm: # Check if base LLM for guidance selection is available
            yield "[Planner Agent Error: Base LLM for guidance selection not initialized. Proceeding with default guidance logic.]"
            # Fallback to simpler logic or just use the default prompt without extra guidance.
            # For now, let's let it proceed, but the select_planning_guidance will use default.

        effective_chat_history = list(chat_history) if chat_history is not None else []

        if self.verbose_agent:
            print(f"\n--- Planner Task Received ---\n{task}")
            if effective_chat_history: print(f"--- Using provided history ({len(effective_chat_history)} messages) ---")
        
        # --- LLM-powered guidance selection ---
        # Use self.llm (the base instance) for this classification task
        available_cats = list(GUIDANCE_PROFILES.keys())
        task_specific_guidance_str = PlannerAgent.select_planning_guidance(task, self.llm, available_cats)
        
        if self.verbose_agent:
            print(f"--- Planner Agent: Selected task guidance block (first 100 chars): {task_specific_guidance_str[:100].replace(os.linesep, ' ')}... ---", file=sys.stderr)

        # Prepare initial messages for the main loop
        messages: List[BaseMessage] = []
        if effective_chat_history: # If there's existing history from the user/API call
            messages.extend(effective_chat_history)
        
        # Inject guidance as an AIMessage simulating an internal thought or context update
        # This message comes *before* the current human task in the sequence for the LLM's consideration
        guidance_message_content = (
            f"<InternalContextUpdate>\n"
            f"Applying specific focus for the upcoming task based on its nature.\n"
            f"{task_specific_guidance_str}\n"
            f"Now, addressing the user's request: '{task}'\n"
            f"</InternalContextUpdate>"
        )
        messages.append(AIMessage(content=guidance_message_content))
        messages.append(HumanMessage(content=task)) # Add the current user task

        start_time = time.time()
        try:
            for iteration in range(self.max_iterations):
                if self.verbose_agent: print(f"\n--- Planner Agent Iteration {iteration + 1}/{self.max_iterations} ---", file=sys.stderr)

                # The self.prompt_template already contains the formatted system message (with dates)
                # We pass the 'messages' list (which now includes history, guidance, and current task)
                # to fill the "{chat_history}" placeholder in the template.
                current_prompt_input_dict = {"chat_history": messages}
                
                if self.verbose_agent:
                    print(f"--- Planner Agent: Calling LLM. Content for 'chat_history' placeholder (length {len(messages)}). Last few items: ---", file=sys.stderr)
                    for m_idx, m in enumerate(messages[-3:]): # Log last 3 messages for context
                         print(f"    HistItem {- (len(messages[-3:]) - m_idx)}: Type={type(m).__name__}, Content='{str(m.content)[:120].replace(os.linesep, ' ')}...'")
                
                # Create the chain for this iteration
                # The prompt template will prepend the system message
                chain_for_iteration = self.prompt_template | self.llm_with_tools
                stream = chain_for_iteration.stream(current_prompt_input_dict)

                ai_response_chunks: List[AIMessageChunk] = []
                accumulated_content = ""
                
                for chunk in stream:
                    if isinstance(chunk, AIMessageChunk):
                        ai_response_chunks.append(chunk)
                        if chunk.content:
                            accumulated_content += chunk.content
                            yield chunk.content 
                    # tool_call_chunks are handled when reconstructing final_ai_message
                    # else:
                        # if self.verbose_agent: print(f"--- Planner Agent Warning: Received unexpected chunk type: {type(chunk)} ---", file=sys.stderr)

                if not ai_response_chunks:
                    yield "\n[Planner Agent Error: LLM response stream was empty or invalid.]"
                    if self.verbose_agent: print("--- Planner Agent Error: LLM stream yielded no AIMessageChunks. ---", file=sys.stderr)
                    return

                final_ai_message: AIMessageChunk = ai_response_chunks[0]
                for chunk_part in ai_response_chunks[1:]:
                    final_ai_message = final_ai_message + chunk_part
                
                messages.append(final_ai_message) # Add LLM's full response to messages for next iteration

                tool_calls = final_ai_message.tool_calls
                if not tool_calls:
                    if self.verbose_agent: print("--- Planner Agent: LLM finished processing or no tools requested. ---", file=sys.stderr)
                    if accumulated_content and not accumulated_content.endswith('\n'): yield "\n"
                    break
                else:
                    if self.verbose_agent: print(f"--- Planner Agent: LLM requested {len(tool_calls)} tool(s): {[tc.get('name') for tc in tool_calls]} ---", file=sys.stderr)
                    tool_messages_for_history = []
                    for tool_call in tool_calls:
                        if isinstance(tool_call, dict) and "name" in tool_call and "args" in tool_call and "id" in tool_call:
                            tool_result_message = self._invoke_tool(tool_call)
                            tool_messages_for_history.append(tool_result_message)
                        else:
                            error_content = f"Error: Malformed tool call: {tool_call}"
                            if self.verbose_agent: print(f"--- Planner Agent Error: {error_content} ---", file=sys.stderr)
                            tc_id = tool_call.get("id", f"malformed_tc_{time.time_ns()}") if isinstance(tool_call, dict) else f"malformed_tc_{time.time_ns()}"
                            tool_messages_for_history.append(ToolMessage(content=error_content, tool_call_id=tc_id))
                    messages.extend(tool_messages_for_history)

            else: # Max iterations reached
                if self.verbose_agent: print(f"--- Planner Agent: Reached max iterations ({self.max_iterations}). ---", file=sys.stderr)
                yield f"\n[Planner Agent Warning: Reached maximum iterations. The plan might be incomplete.]"

            if self.verbose_agent: print(f"\n--- Planner Agent Finished Task. Total time: {time.time() - start_time:.2f}s ---", file=sys.stderr)

        except Exception as e:
            print(f"\n--- CRITICAL Error during Planner Agent Execution: {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            yield f"\n[Planner Agent Error: An unexpected error occurred. Details: {e}]"

# --- Example Usage (main function) remains identical to your last provided version ---
def main():
    try:
        planner = PlannerAgent(verbose_agent=True)
        separator = "\n" + "="*70 + "\n"

        task1 = "Plan a day trip to Girona from Barcelona for next Saturday. Check the weather and suggest a possible train or car route."
        print(separator + f"Running task 1: {task1}" + separator)
        history1 = []
        for token in planner.run(task1, chat_history=history1):
            print(token, end="", flush=True)
        print(separator)

        today = datetime.now().date()
        days_until_saturday = (5 - today.weekday() + 7) % 7
        next_saturday = today + timedelta(days=days_until_saturday)
        next_sunday = next_saturday + timedelta(days=1)
        sat_str = next_saturday.strftime('%Y-%m-%d')
        sun_str = next_sunday.strftime('%Y-%m-%d')

        task15 = "I want to plan a weekend trip to Paris for the upcoming weekend. "
        print(separator + f"Querying for next weekend dates (Task 1.5): {task15}" + separator) # Clarified task print
        # This task is simple, LLM should use its date context.
        # We don't need to pass sat_str/sun_str to it for this query.
        history15 = []
        for token in planner.run(task15, chat_history=history15):
            print(token, end="", flush=True)
        print(separator)


        task2 = (f"I want to plan a weekend trip to Paris for the upcoming weekend ({sat_str} to {sun_str}). "
                 f"Can you suggest an itinerary including travel from London? Check the weather for Paris on those dates, "
                 f"find opening hours for the Eiffel Tower, and add an event to my calendar for visiting it " # Simplified "add a placeholder"
                 f"on Saturday afternoon (e.g., {sat_str} 15:00:00).")
        print(separator + f"Running task 2: {task2}" + separator)
        history2 = []
        for token in planner.run(task2, chat_history=history2):
             print(token, end="", flush=True)
        print(separator)

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
    main()

# --- END OF FILE planner_agent.py ---     