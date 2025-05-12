import sys
import os
import shutil
import traceback
from typing import List, Callable, Iterator, Dict, Any
import time
import json

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage
from langchain_core.tools import BaseTool # Use BaseTool for better type hinting if tools are classes

# Tool imports
from tools import web_search, extended_web_search, find_interesting_links, news_search # Ensure these are correctly defined/imported

# Model names import
from config import MAIN_MODEL, VERBOSE

class OptimizedLangchainAgent:
	"""
	Optimized Agent using Langchain, Ollama, and search tools.
	Supports iterative tool calls and maintains a clean history.
	Includes performance improvements for faster processing of search results.
	"""
	def __init__(self,
				 model_name: str = MAIN_MODEL,
				 tools: List[Callable] = [web_search, extended_web_search, find_interesting_links, news_search],
				 system_message: str = (
					 "You are a helpful AI assistant. Your goal is to answer the user's questions accurately and helpfully. "
					 "You have access to tools for searching the web, finding news, and discovering relevant links. "
					 "Use your internal knowledge ONLY for information that is static and cannot have changed since your last training data. "
					 "For any current events, recent information, or topics where information might change, you MUST use the available tools. "
					 "Analyze the user's request carefully: identify the core question, any time constraints (e.g., 'latest', 'recent'), and the specific information needed. "
					 "Choose the most appropriate tool(s) for the task based on their descriptions. "
					 "You can make multiple tool calls in sequence if needed. If the results from one tool are insufficient, analyze them and decide if another tool call (or the same tool with different arguments) is necessary. "
					 "After gathering information using tools, synthesize the results clearly and concisely to directly answer the user's question. "
					 "ALWAYS cite the information source or provide relevant links ([Title](URL)) found by your tools to support your answer and allow the user to explore further. Do not just list links; explain how they are relevant to the answer. "
					 "Structure your final response to be easily understandable."
				 ),
				 verbose_agent: bool = VERBOSE,
				 optimizations_enabled: bool = False,
				 max_iterations: int = 5 # Add a safety break for tool loops
				 ):
		self.model_name = model_name
		self.verbose_agent = verbose_agent
		self.optimizations_enabled = optimizations_enabled
		self.max_iterations = max_iterations

		self.tools = tools
		if not self.tools:
			print("Warning: No valid tools provided.", file=sys.stderr)
		self.tool_map = {tool.name: tool for tool in self.tools}

		try:
			self.llm = ChatOllama(model=model_name, temperature=0.2)
			# Bind tools for the LLM to be aware of their schemas
			self.llm_with_tools = self.llm.bind_tools(self.tools)
			# Simple connection check (optional, but good practice)
			# self.llm.invoke("Respond with OK")
			if self.verbose_agent: print(f"Successfully initialized Ollama model '{self.model_name}' with tools: {list(self.tool_map.keys())}.")
		except Exception as e:
			print(f"Error initializing/connecting to Ollama model '{self.model_name}'. Is Ollama running? Details: {e}", file=sys.stderr)
			traceback.print_exc(file=sys.stderr)
			sys.exit(1)

		# Define the main prompt template
		self.prompt_template = ChatPromptTemplate.from_messages([
			("system", system_message),
			("placeholder", "{chat_history}"),
			# Human input is implicitly added last in the messages list
		])

	def _invoke_tool(self, tool_call: Dict[str, Any]) -> ToolMessage:
		"""Helper function to safely invoke a tool and return a ToolMessage."""
		tool_name = tool_call.get("name")
		tool_args = tool_call.get("args", {})
		tool_call_id = tool_call.get("id") # Crucial for associating result with call

		# Ensure tool_call_id is present, generate one if missing (though Langchain usually provides it)
		if not tool_call_id:
			tool_call_id = f"tool_call_{time.time_ns()}" # Fallback ID
			if self.verbose_agent: print(f"--- Agent Warning: Tool call missing ID. Assigning '{tool_call_id}'. Tool call details: {tool_call}", file=sys.stderr)


		if not tool_name:
			return ToolMessage(content="Error: Tool call missing name.", tool_call_id=tool_call_id)
		if tool_name not in self.tool_map:
			return ToolMessage(content=f"Error: Tool '{tool_name}' not found.", tool_call_id=tool_call_id)

		selected_tool = self.tool_map[tool_name]
		tool_start_time = time.time()
		if self.verbose_agent: print(f"--- Agent: Invoking tool '{tool_name}' with args: {tool_args} (Call ID: {tool_call_id}) ---", file=sys.stderr)

		try:
			# Langchain tools expect a dictionary 'input' key or handle args directly
			# We pass the 'args' dictionary from the LLM tool call directly
			output = selected_tool.invoke(tool_args)

			# Ensure output is string serializable for ToolMessage
			if not isinstance(output, str):
				try:
					# Try pretty printing JSON if it looks like JSON
					if isinstance(output, (dict, list)):
						output_content = json.dumps(output, indent=2)
					else:
						output_content = json.dumps(output)
				except TypeError:
					output_content = str(output) # Fallback to basic string conversion
			else:
				output_content = output

			# --- Optimization: Apply truncation ---
			if self.optimizations_enabled and len(output_content) > 1500: # Example length threshold
				output_content = output_content[:1500] + "... [truncated for efficiency]"

			if self.verbose_agent: print(f"--- Agent: Tool '{tool_name}' completed in {time.time() - tool_start_time:.2f}s ---", file=sys.stderr)
			return ToolMessage(content=output_content, tool_call_id=tool_call_id)

		except Exception as e:
			error_msg = f"Error executing tool '{tool_name}': {e}"
			if self.verbose_agent: print(f"--- Agent Error: {error_msg} ---", file=sys.stderr)
			# It's important to print the traceback for debugging tool errors
			traceback.print_exc(file=sys.stderr)
			return ToolMessage(content=error_msg, tool_call_id=tool_call_id)

	def run(self, task: str, empty_data_folders: bool = True, data_folders: list[str] = ["images", "screenshots"]) -> Iterator[str]:
		"""
		Executes a task, potentially involving multiple tool calls, and streams the final response.
		"""
		if empty_data_folders and data_folders:
			# Clear the specified data inside the folders
			if self.verbose_agent: print(f"--- Agent: Clearing data folders: {data_folders} ---", file=sys.stderr)
			# Check if the folders exist before attempting to clear them
			for folder in data_folders:
				if os.path.exists(folder):
					# Clear the folder contents
					for filename in os.listdir(folder):
						file_path = os.path.join(folder, filename)
						try:
							if os.path.isfile(file_path) or os.path.islink(file_path):
								os.unlink(file_path)
							elif os.path.isdir(file_path):
								shutil.rmtree(file_path)
						except Exception as e:
							print(f"Error clearing file {file_path}: {e}", file=sys.stderr)
				else:
					print(f"Warning: Folder '{folder}' does not exist. Skipping clearing.", file=sys.stderr)
		# Check if the task is empty
						 
		if self.verbose_agent:
			print(f"\n--- Task Received ---\n{task}")
			print("\n--- Agent Response ---")
		start_time = time.time()

		# Initialize chat history with the user's task
		messages: List[BaseMessage] = [HumanMessage(content=task)]

		try:
			for iteration in range(self.max_iterations):
				if self.verbose_agent: print(f"\n--- Agent Iteration {iteration + 1}/{self.max_iterations} ---", file=sys.stderr)

				# Prepare messages for the LLM call
				# Create the prompt value from the template + history *excluding* the last human message
				prompt_value = self.prompt_template.invoke({"chat_history": messages[:-1]})
				# Combine the template's output messages (system prompt) with the actual history
				formatted_messages = prompt_value.to_messages() + messages # Pass the full history

				if self.verbose_agent:
					print(f"--- Agent: Calling LLM with {len(formatted_messages)} messages. ---", file=sys.stderr)
					# Optional: Log message types for debugging history format
					# print(f"--- Message History Types: {[type(m).__name__ for m in formatted_messages]} ---", file=sys.stderr)


				# === LLM Call (Streaming) ===
				stream = self.llm_with_tools.stream(formatted_messages)
				ai_response_chunks: List[AIMessageChunk] = []
				full_response_content = "" # Store full text content for potential non-streaming use

				# Consume the stream and collect chunks
				for chunk in stream:
					if isinstance(chunk, AIMessageChunk):
						ai_response_chunks.append(chunk)
						if chunk.content:
							full_response_content += chunk.content # Keep track of text
					else:
						# Log unexpected chunk types if necessary
						if self.verbose_agent: print(f"--- Agent Warning: Received unexpected chunk type: {type(chunk)} ---", file=sys.stderr)


				# === Reconstruct the full AIMessage ===
				if not ai_response_chunks:
					yield "[Agent Error: LLM response stream was empty or did not contain AI message chunks]"
					if self.verbose_agent: print("--- Agent Error: LLM stream yielded no AIMessageChunks. ---", file=sys.stderr)
					return # Exit if no valid AI chunks were received

				# Combine chunks using the '+' operator
				final_ai_message: AIMessageChunk = ai_response_chunks[0]
				for chunk in ai_response_chunks[1:]:
					final_ai_message += chunk

				# Add the reconstructed AI response to history
				# Although it's technically a chunk, the combined chunk holds all necessary info (content, tool_calls, id)
				# and behaves like a full AIMessage in the history for the *next* LLM call.
				messages.append(final_ai_message)

				# === Tool Check and Execution ===
				# Tool calls are aggregated in the combined chunk
				tool_calls = final_ai_message.tool_calls
				if not tool_calls:
					if self.verbose_agent: print("--- Agent: LLM decided no tools needed or finished processing. Streaming final answer. ---", file=sys.stderr)
					# This is the final answer. Stream its content chunk by chunk as received.
					for chunk in ai_response_chunks:
						if chunk.content:
							yield chunk.content
					print() # Add a newline after streaming finishes
					break # Exit the loop as we have the final answer

				else:
					if self.verbose_agent: print(f"--- Agent: LLM requested {len(tool_calls)} tool(s): {[tc.get('name', 'Unnamed Tool') for tc in tool_calls]} ---", file=sys.stderr)

					tool_messages = []
					for tool_call in tool_calls:
						# Ensure tool_call has the expected dictionary structure
						if isinstance(tool_call, dict) and "name" in tool_call and "args" in tool_call and "id" in tool_call:
							tool_result_message = self._invoke_tool(tool_call)
							tool_messages.append(tool_result_message)
						else:
							# Handle malformed tool calls if they occur
							error_content = f"Error: Received malformed tool call from LLM: {tool_call}"
							if self.verbose_agent: print(f"--- Agent Error: {error_content} ---", file=sys.stderr)
							# Try to create a ToolMessage with an error, using a placeholder ID if needed
							tc_id = tool_call.get("id", f"malformed_tc_{time.time_ns()}") if isinstance(tool_call, dict) else f"malformed_tc_{time.time_ns()}"
							tool_messages.append(ToolMessage(content=error_content, tool_call_id=tc_id))


					# Add tool results to history for the next iteration
					messages.extend(tool_messages)
					# Continue the loop to let the LLM process the tool results

			else: # Loop finished without break (max_iterations reached)
				if self.verbose_agent: print(f"--- Agent: Reached max iterations ({self.max_iterations}). Returning current state. ---", file=sys.stderr)
				# Attempt to stream the last accumulated content, even if tools were pending
				if full_response_content:
					yield full_response_content
					yield f"\n[Agent Warning: Reached maximum iterations ({self.max_iterations}). The response might be incomplete or waiting for tool results.]"
				else:
					# If the last AI response had no text content but maybe tool calls
					yield f"[Agent Error: Reached maximum iterations ({self.max_iterations}) without a final answer or text response. The last step might have been tool calls.]"


			if self.verbose_agent: print(f"\n--- Agent Finished. Total time: {time.time() - start_time:.2f}s ---", file=sys.stderr)

		except Exception as e:
			# Log the specific point of failure if possible
			print(f"\n--- Error during Agent Execution (in run loop): {e} ---", file=sys.stderr)
			traceback.print_exc(file=sys.stderr)
			yield f"\n[Agent Error: An unexpected error occurred during execution. Details: {e}]"


# --- Example Usage ---
def main():
	try:
		langchain_agent = OptimizedLangchainAgent(
			tools=[extended_web_search, find_interesting_links, news_search],
		)

		separator = "\n" + "="*60

		# print(separator)
		# task1 = "What is the capital of France?" # Should use internal knowledge
		# print(f"Running task: {task1}")
		# for token in langchain_agent.run(task1):
		#     print(token, end="", flush=True)
		# print(separator)

		# print(separator)
		# task2 = "What are the latest developments regarding the Artemis program missions? Find relevant news and some general info links." # Should use tools
		# print(f"Running task: {task2}")
		# for token in langchain_agent.run(task2):
		#     print(token, end="", flush=True)
		# print(separator)

		# print(separator)
		# task3 = "Are there any recent news articles discussing the plot or reception of the movie 'Dune: Part Two'?" # Should use news_search
		# print(f"Running task: {task3}")
		# for token in langchain_agent.run(task3):
		# 	print(token, end="", flush=True)
		# print(separator)

		print(separator)
		task4 = "what is the weather like in Barcelona right now?" # Needs a tool
		print(f"Running task: {task4}")
		for token in langchain_agent.run(task4):
		    print(token, end="", flush=True)
		print(separator)

		# print(separator)
		# task5 = "Find recent news about AI regulations in Europe, then find interesting links discussing the potential impact on startups."
		# print(f"Running task: {task5}")
		# for token in langchain_agent.run(task5):
		#     print(token, end="", flush=True)
		# print(separator)


	except SystemExit:
		print("Exiting due to configuration error.", file=sys.stderr)
	except Exception as e:
		print(f"\nAn unexpected error occurred in the main block: {e}", file=sys.stderr)
		traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
	main()

