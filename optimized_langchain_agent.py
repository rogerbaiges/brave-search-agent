import sys
import os
import shutil
import traceback
from typing import List, Callable, Iterator, Dict, Any, Optional
import time
import json

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, BaseMessage, SystemMessage
from langchain_core.tools import BaseTool # Use BaseTool for better type hinting if tools are classes

# Tool imports
from tools import general_web_search, extended_web_search, find_interesting_links, news_search, weather_search, extract_web_content, image_search

# Model names import
from config import MAIN_MODEL, VERBOSE, IMAGES_DIR, SCREENSHOTS_DIR

# LayoutChat import
from layout_chat import LayoutChat


class OptimizedLangchainAgent:
	"""
	Optimized Agent using Langchain, Ollama, and search tools.
	Supports iterative tool calls and maintains a clean history.
	Includes performance improvements for faster processing of search results.
	"""
	def __init__(self,
				 model_name: str = MAIN_MODEL,
				 tools: List[Callable] = [general_web_search, extended_web_search, find_interesting_links, news_search, weather_search, extract_web_content, image_search],
				 verbose_agent: bool = VERBOSE,
				 optimizations_enabled: bool = False,
				 max_iterations: int = 5 # Add a safety break for tool loops
				 ):
		self.model_name = model_name
		self.verbose_agent = verbose_agent
		self.optimizations_enabled = optimizations_enabled
		self.max_iterations = max_iterations
		self.system_message: str = (
			"You are an elite intelligence agent. Your mission: exhaustively research user queries, extracting EVERY piece of relevant information with COMPLETE, UNABRIDGED context from ALL sources and their subpages. "
			"**CRITICAL: NO SUMMARIZATION of relevant information. Provide full, original content. Your output feeds a formatting AI, so prioritize completeness and raw data.**\n\n"

			"**OPERATING PROTOCOL (CONTINUOUS RESEARCH LOOP):**\n\n"

			"1.  **COMPREHENSIVE & ITERATIVE RESEARCH (THE LOOP):**\n"
			"    *   **Strategic Planning:** At each step, before making any tool call or deciding to finalize, engage in a deep analytical thought process. Ask yourself: "
			"        -   'What specific information does the user's query *fully* require?' "
			"        -   'Have I explored *all* primary and secondary sources (including subpages/related links from initial results) exhaustively?' "
			"        -   'Are there *any* remaining information gaps, ambiguities, or areas where deeper context is needed?' "
			"        -   'Which tool, or sequence of tools, will best address these gaps or deepen my understanding for *complete, unabridged* context?' "
			"        -   'Is the current set of information truly *exhaustive* as per the high standards of this protocol?' "
			"        -   'If not, I MUST continue using tools to gather more information.' "
			"    *   **Wide & Deep Tool Use:** Systematically use ALL relevant tools. Start broad (`general_web_search`, `news_search`), then drill down (`extended_web_search`, `extract_web_content`, `find_interesting_links`). Employ multiple search strategies, keywords, and tool combinations iteratively until the topic is exhaustively covered from diverse angles.\n"
			"    *   **Exhaustive Source Exploration (Crucial Iteration):** For EVERY promising source (main pages, articles, documents) found by `general_web_search` or `news_search`:\n"
			"        *   **IMMEDIATELY** use `extended_web_search` or `extract_web_content` to retrieve its COMPLETE, UNABRIDGED content. Preserve ALL surrounding context (e.g., preceding/following paragraphs, explanations, background, implications, data, quotes).\n"
			"        *   **Then, for any URLs identified within the extracted content or from initial search results that seem to be subpages, related articles, documentation, or appendices of the primary source, use `find_interesting_links` on the primary page to identify them, and subsequently `extract_web_content` on those newly found links.** This ensures you systematically explore ALL relevant linked content within a promising domain.\n"
			"        *   Relentlessly Iterate: Continue this process of searching, extracting, and exploring sub-links until you are certain there is *no more* relevant, complete, unabridged information to be gathered for the user's query.\n"
			"    *   **Relentless Iteration & Gap Analysis:** Continuously assess information and context gaps. If content lacks detail or full context, conduct follow-up searches or deeper extractions. Iterate tool use as many times as necessary. Ask: Is information fully explored? What's important? What's next for complete coverage?\n\n"

			"2.  **INFORMATION STANDARDS & CONTEXTUAL AWARENESS:**\n"
			"    *   **No Summarization - Full Detail Required:** Capture ALL quantitative data (numbers, stats, methods, limitations), qualitative insights (expert opinions with reasoning, full analysis), procedural information (how things work, processes, steps), contextual background (history, related events, implications), and future projections (trends, rationale) - all with their complete supporting context.\n"
			"    *   **Time & Relevance:** Be aware of the current date/time and the query's relevant time period. Ensure information is up-to-date. Verify the relevance of older data.\n\n"

			"3.  **STRUCTURED INTELLIGENCE REPORT & ATTRIBUTION:**\n"
			"    *   **Report Format:**\n"
			"        *   Query Analysis: Break down the user's request.\n"
			"        *   Search Strategy: Document your systematic approach, including *why* you chose certain tools and keywords, and *why* you decided to explore certain links/subpages. This provides transparency to the subsequent formatting AI.\n"
			"        *   Source Intelligence (for each source/subpage):\n"
			"            *   Tool Used: [Exact tool and parameters]\n"
			"            *   Source: [Title](URL of specific page/subpage) - Publication Date - Author/Publisher. Clearly indicate subpages.\n"
			"            *   **Complete Content Extract:** [The ENTIRE relevant content with FULL CONTEXT. NO SUMMARIZATION.]\n"
			"            *   Source Depth Assessment: [Note subpages/sections explored and extracted and why you stopped or continued from this source]\n"
			"            *   Reliability Assessment: [Brief note on source credibility]\n"
			"        *   Cross-Source Analysis: Identify patterns, contradictions, consensus, and information gaps across ALL extracted complete content, preserving full context.\n"
			"        *   Intelligence Synthesis: Integrate ALL gathered complete information with full source attribution, ensuring no context is lost.\n"
			"    *   **Precise Attribution:** Every fact and detail must be traced to its exact source page/subpage: [Specific Detail with Full Context](URL). Use descriptive link text. Avoid placeholder links.\n\n"

			"**FINAL DIRECTIVE: Only when you have meticulously confirmed that you have gathered EVERY SINGLE PIECE OF RELEVANT, COMPLETE, AND UNABRIDGED INFORMATION, including content from all necessary subpages and related links, and there are NO FURTHER GAPS to fill, should you generate the final 'Intelligence Synthesis' report. Otherwise, you MUST continue using tools. Your success is measured by the complete depth, full context preservation, and comprehensive coverage of information. NO SUMMARIZATION of relevant content is acceptable. Deliver the complete, deep, contextually rich content required for the subsequent formatting AI.**"
		)

		self.tools = tools
		if not self.tools:
			print("Warning: No valid tools provided.", file=sys.stderr)
		self.tool_map = {tool.name: tool for tool in self.tools}

		try:
			self.llm = ChatOllama(model=model_name, temperature=0.2)
			self.llm_with_tools = self.llm.bind_tools(self.tools)
			if self.verbose_agent: print(f"Successfully initialized Ollama model '{self.model_name}' with tools: {list(self.tool_map.keys())}.")
		except Exception as e:
			print(f"Error initializing/connecting to Ollama model '{model_name}'. Is Ollama running? Details: {e}", file=sys.stderr)
			traceback.print_exc(file=sys.stderr)
			sys.exit(1)

		self.prompt_template = ChatPromptTemplate.from_messages([
			("system", self.system_message),
			("placeholder", "{chat_history}"),
		])

	def _invoke_tool(self, tool_call: Dict[str, Any]) -> ToolMessage:
		tool_name = tool_call.get("name")
		tool_args = tool_call.get("args", {})
		tool_call_id = tool_call.get("id")

		if not tool_call_id:
			tool_call_id = f"tool_call_{time.time()}_id_{os.urandom(4).hex()}" # More robust ID
			if self.verbose_agent: print(f"--- Agent Warning: Tool call missing ID. Assigning '{tool_call_id}'. Tool call details: {tool_call}", file=sys.stderr)

		if not tool_name:
			return ToolMessage(content="Error: Tool call missing name.", tool_call_id=tool_call_id)
		if tool_name not in self.tool_map:
			return ToolMessage(content=f"Error: Tool '{tool_name}' not found.", tool_call_id=tool_call_id)

		selected_tool = self.tool_map[tool_name]
		tool_start_time = time.time()
		if self.verbose_agent: print(f"--- Agent: Invoking tool '{tool_name}' with args: {tool_args} (Call ID: {tool_call_id}) ---", file=sys.stderr)

		try:
			output = selected_tool.invoke(tool_args)

			# --- START NEW/MODIFIED LOGIC FOR TOOL OUTPUT PROCESSING ---
			output_content: str = "" # Initialize for clarity

			if tool_name == "image_search":
				# Special handling for image_search:
				# Provide a minimal message to the LLM, but log full output for debugging
				if self.verbose_agent:
					print(f"--- Agent: Suppressing full output for '{tool_name}'. Full result: {output} ---", file=sys.stderr)
				
				# Construct a concise message for the LLM
				num_images = len(output.get("images", [])) if isinstance(output, dict) else 0
				output_content = f"True. images for the query {tool_args.get('query', '')} have been downloadad and the formatting AI will use them. DO NOT CALL `image_search` with the same query again (including similar queries that refer to the same entity or contept). Instead, move on to other entities/concepts or stop calling `image_search`."
			else:
				# Existing logic for other tools: convert output to string/JSON and potentially truncate
				if not isinstance(output, str):
					try:
						if isinstance(output, (dict, list)):
							output_content = json.dumps(output, indent=2)
						else:
							output_content = str(output)
					except TypeError:
						output_content = str(output)
				else:
					output_content = output

			# Truncate large outputs for efficiency, only if optimizations_enabled is True
			if self.optimizations_enabled and len(output_content) > 1500:
				original_len = len(output_content)
				output_content = output_content[:1500] + f"... [truncated from {original_len} chars for efficiency]"
				if self.verbose_agent: print(f"--- Agent: Truncated tool output from {original_len} to 1500 chars. ---", file=sys.stderr)


			if self.verbose_agent: print(f"--- Agent: Tool '{tool_name}' completed in {time.time() - tool_start_time:.2f}s ---", file=sys.stderr)
			return ToolMessage(content=output_content, tool_call_id=tool_call_id)

		except Exception as e:
			error_msg = f"Error executing tool '{tool_name}': {e}"
			if self.verbose_agent: print(f"--- Agent Error: {error_msg} ---", file=sys.stderr)
			traceback.print_exc(file=sys.stderr)
			return ToolMessage(content=error_msg, tool_call_id=tool_call_id)

	def run(self, task: str, empty_data_folders: bool = True, data_folders: list[str] = [IMAGES_DIR, SCREENSHOTS_DIR]) -> Iterator[str]:
		if empty_data_folders and data_folders:
			if self.verbose_agent: print(f"--- Agent: Clearing data folders: {data_folders} ---", file=sys.stderr)
			for folder in data_folders:
				# Ensure the folder exists or create it before clearing
				# This is important because tools might expect these folders.
				os.makedirs(folder, exist_ok=True)
				if os.path.isdir(folder): # Check again after makedirs, though it should be
					for filename in os.listdir(folder):
						file_path = os.path.join(folder, filename)
						try:
							if os.path.isfile(file_path) or os.path.islink(file_path):
								os.unlink(file_path)
							elif os.path.isdir(file_path):
								shutil.rmtree(file_path) # rmtree needed if subdirs were created by tools
								os.makedirs(folder, exist_ok=True) # Recreate the folder after rmtree
						except Exception as e:
							print(f"Error clearing file/folder {file_path}: {e}", file=sys.stderr)
				else: # Should not happen if makedirs succeeded
					print(f"Warning: Folder '{folder}' path issue after attempting creation. Skipping clearing.", file=sys.stderr)
		elif data_folders: # Not emptying, but ensure they exist if tools need them
			for folder in data_folders:
				os.makedirs(folder, exist_ok=True)


		if self.verbose_agent:
			print(f"\n--- Task Received ---\n{task}")
			print("\n--- Agent Response ---")
		start_time = time.time()

		messages: List[BaseMessage] = [HumanMessage(content=task)]

		try:
			for iteration in range(self.max_iterations):
				if self.verbose_agent: print(f"\n--- Agent Iteration {iteration + 1}/{self.max_iterations} ---", file=sys.stderr)

				prompt_value = self.prompt_template.invoke({"chat_history": messages[:-1]})
				formatted_messages = prompt_value.to_messages() + messages

				if self.verbose_agent:
					print(f"--- Agent: Calling LLM with {len(formatted_messages)} messages. ---", file=sys.stderr)

				stream = self.llm_with_tools.stream(formatted_messages)
				ai_response_chunks: List[AIMessageChunk] = []
				full_response_content = ""

				for chunk in stream:
					if isinstance(chunk, AIMessageChunk):
						ai_response_chunks.append(chunk)
						if chunk.content:
							full_response_content += chunk.content
					else:
						if self.verbose_agent: print(f"--- Agent Warning: Received unexpected chunk type: {type(chunk)} ---", file=sys.stderr)

				if not ai_response_chunks:
					yield "[Agent Error: LLM response stream was empty or did not contain AI message chunks]"
					if self.verbose_agent: print("--- Agent Error: LLM stream yielded no AIMessageChunks. ---", file=sys.stderr)
					return

				final_ai_message: AIMessageChunk = ai_response_chunks[0]
				for chunk in ai_response_chunks[1:]:
					final_ai_message += chunk
				messages.append(final_ai_message)

				tool_calls = final_ai_message.tool_calls
				if not tool_calls:
					if self.verbose_agent: print("--- Agent: LLM decided no tools needed or finished processing. Streaming final answer. ---", file=sys.stderr)
					for chunk_item in ai_response_chunks: # Iterate over original chunks for streaming
						if chunk_item.content:
							yield chunk_item.content
					if full_response_content.strip(): print()
					break
				else:
					if self.verbose_agent: print(f"--- Agent: LLM requested {len(tool_calls)} tool(s): {[tc.get('name', 'Unnamed Tool') for tc in tool_calls]} ---", file=sys.stderr)
					tool_messages = []
					for tool_call in tool_calls:
						# IMPORTANT: Ensure tool_call has 'id' for ToolMessage. Langchain guarantees this for _tool_calls but direct access might not.
						# A simple check: if 'id' is missing, generate one.
						if isinstance(tool_call, dict) and "name" in tool_call and "args" in tool_call and "id" in tool_call:
							tool_result_message = self._invoke_tool(tool_call)
							tool_messages.append(tool_result_message)
						else:
							error_content = f"Error: Received malformed tool call from LLM: {tool_call}"
							if self.verbose_agent: print(f"--- Agent Error: {error_content} ---", file=sys.stderr)
							# Create a tool message with a generated ID if the original was malformed
							tc_id = tool_call.get("id", f"malformed_tc_{time.time_ns()}") if isinstance(tool_call, dict) else f"malformed_tc_{time.time_ns()}"
							tool_messages.append(ToolMessage(content=error_content, tool_call_id=tc_id))
					messages.extend(tool_messages)
			else:
				if self.verbose_agent: print(f"--- Agent: Reached max iterations ({self.max_iterations}). Returning current state. ---", file=sys.stderr)
				if full_response_content:
					yield full_response_content
					yield f"\n[Agent Warning: Reached maximum iterations ({self.max_iterations}). The response might be incomplete or waiting for tool results.]"
				else:
					yield f"[Agent Error: Reached maximum iterations ({self.max_iterations}) without a final answer or text response. The last step might have been tool calls.]"

			if self.verbose_agent: print(f"\n--- Agent Finished. Total time: {time.time() - start_time:.2f}s ---", file=sys.stderr)

		except Exception as e:
			print(f"\n--- Error during Agent Execution (in run loop): {e} ---", file=sys.stderr)
			traceback.print_exc(file=sys.stderr)
			yield f"\n[Agent Error: An unexpected error occurred during execution. Details: {e}]"

	def _get_image_files_in_dir(self, dir_path: str) -> set[str]:
		"""Helper to get a set of full paths to image files in a directory."""
		image_files = set()
		# Ensure directory exists before trying to list files
		# os.makedirs(dir_path, exist_ok=True) # Already done before calling this for initial state

		if not os.path.isdir(dir_path):
			if self.verbose_agent:
				print(f"--- Agent Info: Directory not found for image listing: {dir_path} ---", file=sys.stderr)
			return image_files
		try:
			for filename in os.listdir(dir_path):
				file_path = os.path.join(dir_path, filename)
				if os.path.isfile(file_path) and \
				   filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
					image_files.add(file_path)
		except Exception as e:
			if self.verbose_agent:
				print(f"--- Agent Warning: Error listing images in {dir_path}: {e} ---", file=sys.stderr)
		return image_files

	def run_layout(self,
				   task: str,
				   user_original_query: str, # Add this parameter
				   empty_data_folders: bool = True,
				   data_folders: list[str] = [IMAGES_DIR, SCREENSHOTS_DIR],
				   layout_inspiration_image_paths: Optional[List[str]] = None,
				   ) -> Iterator[str]:
		if self.verbose_agent:
			print(f"\n--- Task Received for Run with Layout ---\n{task}")
			print(f"--- Original User Query: {user_original_query} ---") # Log for clarity
			if layout_inspiration_image_paths:
				print(f"--- Layout Inspiration Images Parameter: {layout_inspiration_image_paths} ---")
			print(f"--- Data folders for self.run: {data_folders}, Empty them: {empty_data_folders} ---")


		# 1. Ensure IMAGES_DIR and SCREENSHOTS_DIR exist for reliable state capture
		os.makedirs(IMAGES_DIR, exist_ok=True)
		os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

		# Capture initial state of IMAGES_DIR and SCREENSHOTS_DIR *before* self.run
		initial_content_img_files = self._get_image_files_in_dir(IMAGES_DIR)
		if SCREENSHOTS_DIR != IMAGES_DIR:
			initial_screenshot_files = self._get_image_files_in_dir(SCREENSHOTS_DIR)
		else:
			initial_screenshot_files = initial_content_img_files # Same directory, same initial files

		if self.verbose_agent:
			print(f"--- Initial content images in {IMAGES_DIR}: {len(initial_content_img_files)} ---", file=sys.stderr)
			print(f"--- Initial screenshot images in {SCREENSHOTS_DIR}: {len(initial_screenshot_files)} ---", file=sys.stderr)

		# 2. Get the initial response from the agent's run method
		agent_response_parts = []
		try:
			# self.run will handle clearing/creating folders in `data_folders` list
			for chunk in self.run(task, empty_data_folders, data_folders):
				agent_response_parts.append(chunk)
		except Exception as e:
			yield f"[Agent Error in run_layout during self.run: {e}]"
			traceback.print_exc(file=sys.stderr)
			return
		
		agent_output_str = "".join(agent_response_parts).strip()

		if not agent_output_str and self.verbose_agent:
			print("--- Agent Warning: self.run() produced an empty string output. ---", file=sys.stderr)
		elif self.verbose_agent:
			print(f"\n--- Agent Raw Output (to LayoutChat) ---\n{agent_output_str}\n----------------------------------")

		# 3. Determine newly generated content images from IMAGES_DIR
		current_content_img_files = self._get_image_files_in_dir(IMAGES_DIR)
		# Check if IMAGES_DIR was part of the data_folders that self.run would have cleared
		was_images_dir_cleared = empty_data_folders and \
								 any(os.path.normpath(p) == os.path.normpath(IMAGES_DIR) for p in data_folders)
		
		if was_images_dir_cleared:
			newly_generated_content_images = list(current_content_img_files)
		else:
			newly_generated_content_images = list(current_content_img_files - initial_content_img_files)

		if self.verbose_agent:
			if newly_generated_content_images:
				print(f"--- Found {len(newly_generated_content_images)} new content image(s) in {IMAGES_DIR} for LayoutChat. ---", file=sys.stderr)
			else:
				print(f"--- No new content images found/selected in {IMAGES_DIR} for LayoutChat. ---", file=sys.stderr)

		# 4. Determine layout inspiration images
		final_layout_inspiration_images: List[str] = []
		if layout_inspiration_image_paths: # User provided specific paths
			final_layout_inspiration_images = layout_inspiration_image_paths
			if self.verbose_agent:
				print(f"--- Using {len(final_layout_inspiration_images)} externally provided layout inspiration image(s). ---", file=sys.stderr)
		else: # No external paths, so look for new screenshots in SCREENSHOTS_DIR
			current_screenshot_files = set()
			if SCREENSHOTS_DIR != IMAGES_DIR:
				current_screenshot_files = self._get_image_files_in_dir(SCREENSHOTS_DIR)
			elif os.path.isdir(SCREENSHOTS_DIR): # SCREENSHOTS_DIR == IMAGES_DIR
				current_screenshot_files = current_content_img_files # Use already fetched list

			was_screenshots_dir_cleared = empty_data_folders and \
										  any(os.path.normpath(p) == os.path.normpath(SCREENSHOTS_DIR) for p in data_folders)

			if was_screenshots_dir_cleared:
				newly_generated_screenshots = list(current_screenshot_files)
			else:
				newly_generated_screenshots = list(current_screenshot_files - initial_screenshot_files)
			
			final_layout_inspiration_images = newly_generated_screenshots
			if self.verbose_agent:
				if final_layout_inspiration_images:
					print(f"--- Found {len(final_layout_inspiration_images)} new screenshot(s) in {SCREENSHOTS_DIR} for layout inspiration. ---", file=sys.stderr)
				else:
					print(f"--- No new screenshots found/selected in {SCREENSHOTS_DIR} (and no external paths provided) for layout inspiration. ---", file=sys.stderr)

		# 5. Initialize LayoutChat and stream its formatted response
		try:
			if self.verbose_agent: print("\n--- Initializing LayoutChat for Enhanced Formatting ---", file=sys.stderr)
			layout_chat_instance = LayoutChat(verbose=self.verbose_agent)

			if self.verbose_agent: print("--- Calling LayoutChat.run() for final formatted response ---", file=sys.stderr)

			yield "<html_token>" # For frontend to know this is a layout chat response in HTML format
				
			for chunk in layout_chat_instance.run(
				agent_output_str=agent_output_str,
				user_original_query=user_original_query, # Pass the original query here
				content_images=newly_generated_content_images,
				layout_inspiration_screenshots=final_layout_inspiration_images
			):
				yield chunk
			
			yield "</html_token>" # For frontend to know this is the end of layout chat response

			if agent_output_str.strip() or newly_generated_content_images or final_layout_inspiration_images : print() # Add a newline after layout chat if there was input
		
		except SystemExit as e:
			yield f"[Agent Error: LayoutChat initialization failed critically. Details: {e}]"
			if self.verbose_agent: print("--- Agent Error: LayoutChat could not be initialized. ---", file=sys.stderr)
		except Exception as e:
			yield f"[Agent Error in run_layout during LayoutChat execution: {e}]"
			if self.verbose_agent:
				print(f"\n--- Error during LayoutChat Execution (from run_layout): {e} ---", file=sys.stderr)
				traceback.print_exc(file=sys.stderr)
			return
		
		if self.verbose_agent: print("\n--- Agent Run with Layout Finished ---", file=sys.stderr)


# --- Example Usage ---
def main():
	try:
		os.makedirs(IMAGES_DIR, exist_ok=True)
		os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

		dummy_inspiration_path = os.path.join(SCREENSHOTS_DIR, "layout_inspiration_dummy.png")
		dummy_content_image_path_before = os.path.join(IMAGES_DIR, "content_image_before.png")

		try:
			from PIL import Image, ImageDraw
			# Create a dummy inspiration image
			img_insp = Image.new('RGB', (100, 30), color = (200, 200, 200))
			d_insp = ImageDraw.Draw(img_insp)
			d_insp.text((10,10), "Insp. Style", fill=(0,0,0))
			img_insp.save(dummy_inspiration_path)
			print(f"Created dummy inspiration image: {dummy_inspiration_path}")

			# Create a dummy content image that exists *before* run_layout if not emptying
			img_content_before = Image.new('RGB', (100, 30), color = (220, 200, 200))
			d_content_before = ImageDraw.Draw(img_content_before)
			d_content_before.text((10,10), "Old Content", fill=(0,0,0))
			img_content_before.save(dummy_content_image_path_before)
			print(f"Created dummy pre-existing content image: {dummy_content_image_path_before}")

		except ImportError:
			print("PIL not installed, cannot create dummy images. Some test aspects might not work as expected.", file=sys.stderr)
			dummy_inspiration_path = None
			dummy_content_image_path_before = None
		except Exception as e:
			print(f"Error creating dummy images: {e}", file=sys.stderr)
			dummy_inspiration_path = None
			dummy_content_image_path_before = None


		langchain_agent = OptimizedLangchainAgent(
			verbose_agent=True
		)
		separator = "\n" + "="*60

		# Test 1: Empty data folders = True, use generated screenshots for inspiration
		print(separator)
		print("TEST 1: empty_data_folders=True, no explicit inspiration_paths (should use new screenshots from SCREENSHOTS_DIR if any)")
		task_for_layout_1 = "What are the latest developments regarding the Artemis program missions? Find relevant news and save some images."
		user_original_query_1 = "Artemis program updates" # Original query for LayoutChat context
		
		# Manually ensure dummy_inspiration_path is "new" if empty_data_folders=True
		# by deleting it if it exists from a previous run, so it can be "re-created"
		# This is a bit artificial for testing; normally tools create these.
		if os.path.exists(dummy_inspiration_path): os.remove(dummy_inspiration_path)
		if dummy_inspiration_path: # Re-create it to simulate it being new
			try:
				from PIL import Image, ImageDraw
				img_insp = Image.new('RGB', (100, 30), color = (200, 200, 200))
				d_insp = ImageDraw.Draw(img_insp)
				d_insp.text((10,10), "New Insp.", fill=(0,0,0))
				img_insp.save(dummy_inspiration_path)
			except: pass


		output_file = "output_layout.html"
		with open(output_file, "w", encoding="utf-8") as f:
			f.write("")

		print(f"Running task (layout test 1): {task_for_layout_1}")
		for token in langchain_agent.run_layout(
			task_for_layout_1,
			user_original_query=user_original_query_1, # Pass here
			empty_data_folders=True, # Will clear IMAGES_DIR and SCREENSHOTS_DIR
			layout_inspiration_image_paths=None # Rely on new files in SCREENSHOTS_DIR
		):
			print(token, end="", flush=True)

			with open(output_file, "a", encoding="utf-8") as f:
				f.write(token)

		print(separator)


		# Test 2: Empty data folders = False, provide explicit inspiration paths
		print(separator)
		print("TEST 2: empty_data_folders=False, explicit inspiration_paths")
		task_for_layout_2 = "Tell me about the Perseverance rover on Mars. Find general info and images."
		user_original_query_2 = "Perseverance rover details" # Original query for LayoutChat context

		output_file = "output_layout_2.html"
		with open(output_file, "w", encoding="utf-8") as f:
			f.write("")
		
		# Ensure dummy_inspiration_path exists for this test
		explicit_inspiration = []
		if dummy_inspiration_path and os.path.exists(dummy_inspiration_path):
			explicit_inspiration = [dummy_inspiration_path]
		elif dummy_inspiration_path: # try to create it if it was deleted and PIL is available
			try:
				from PIL import Image, ImageDraw
				img_insp = Image.new('RGB', (100, 30), color = (200, 200, 200))
				d_insp = ImageDraw.Draw(img_insp)
				d_insp.text((10,10), "Explicit Insp.", fill=(0,0,0))
				img_insp.save(dummy_inspiration_path)
				explicit_inspiration = [dummy_inspiration_path]
				print(f"Re-created dummy inspiration image for Test 2: {dummy_inspiration_path}")
			except Exception as e:
				print(f"Could not create dummy inspiration for test 2: {e}")


		print(f"Running task (layout test 2): {task_for_layout_2}")
		for token in langchain_agent.run_layout(
			task_for_layout_2,
			user_original_query=user_original_query_2, # Pass here
			empty_data_folders=False, # Should preserve content_image_before.png
			layout_inspiration_image_paths=explicit_inspiration
		):
			print(token, end="", flush=True)
			with open(output_file, "a", encoding="utf-8") as f:
				f.write(token)
		print(separator)

		# Clean up dummy images
		if dummy_inspiration_path and os.path.exists(dummy_inspiration_path):
			try: os.remove(dummy_inspiration_path)
			except OSError as e: print(f"Error removing {dummy_inspiration_path}: {e}", file=sys.stderr)
		if dummy_content_image_path_before and os.path.exists(dummy_content_image_path_before):
			try: os.remove(dummy_content_image_path_before)
			except OSError as e: print(f"Error removing {dummy_content_image_path_before}: {e}", file=sys.stderr)


	except SystemExit:
		print("Exiting due to configuration error.", file=sys.stderr)
	except Exception as e:
		print(f"\nAn unexpected error occurred in the main block: {e}", file=sys.stderr)
		traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
	main()