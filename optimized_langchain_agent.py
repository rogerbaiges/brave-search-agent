import sys
import os
import shutil
import traceback
from typing import List, Callable, Iterator, Dict, Any, Optional
import time
import json

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage, BaseMessage, SystemMessage

# Tool imports
from tools import general_web_search, find_interesting_links, news_search, weather_search, extract_web_content

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
				 tools: List[Callable] = [general_web_search, find_interesting_links, news_search, weather_search, extract_web_content],
				 verbose_agent: bool = VERBOSE,
				 optimizations_enabled: bool = False,
				 max_iterations: int = 8 # Add a safety break for tool loops
				 ):
		self.model_name = model_name
		self.verbose_agent = verbose_agent
		self.optimizations_enabled = optimizations_enabled
		self.max_iterations = max_iterations
		# self.system_message: str = (
		# 	"You are a specialized research agent. To answer the user's query, use ONLY these tools for external data: "
		# 	"`general_web_search`, `extract_web_content`, `news_search`, `weather_search`, and `find_interesting_links`. Work your way through the answer by using them intelligently.\n"
		# 	"Use `general_web_search` for obtaining links and their descriptions, then use `extract_web_content` to get detailed content from the links you find relevant. Make ALL `extract_web_content` calls AT ONCE, right after obtaining the links from `general_web_search`.\n"
		# 	"You SHOULD call the `extended_web_search` and `extract_web_content` tools when `general_web_search` or `news_search` have not provided enough information to answer the query in order to delve deeper into the topic.\n"
		# 	"`news_search` for current events, and `weather_search` for forecasts. "
		# 	"Also, `find_interesting_links` should be used to identify and present additional, relevant links directly to the user for further exploration.\n"
		# 	"**VERY IMPORTANT**: ALWAYS provide the link with [website](<url>) for each piece of information you found using 'general_web_search', 'extended_web_search', 'news_search', or 'extract_web_content'.\n"
		# 	"You can make multiple tool calls at the same time, but do not repeat the same tool call with the same parameters.\n"
		# 	"ALWAYS keep researching (trying different tools, search queries, and parameters) UNTIL you have enough information to answer the user's query. \n"
		# 	"At each iteration, summarize the relevant information you found so far, keeping all the important entities, links and data you have gathered.\n"
		# 	"Pay attention to the timeliness of the information, making sure that it matches the timeframe of the query. You can use the `freshness` parameter in some tools to specify the recency of the information you need.\n"
		# 	"Your output should be long, with all the information found (properly cited with links) and without summarization. Never mention the tools used or your internal reasoning process directly in the output.\n"
		# )
		self.system_message: str = (
			"You are an expert research agent. Your primary mission is to gather comprehensive, detailed, and contextually rich information to **fully answer the user's original query**. "
			"This information will be used by a separate layout/formatting AI; therefore, your output should be a detailed compilation of facts and content, **not a summarized answer**. "
			"Never mention the tools you use or your internal reasoning process in your final output.\n\n"

			"**RESEARCH PROTOCOL (Iterative Information Gathering):**\n"
			"1.  **Strategic Tool Use:** Systematically use the following tools to address the user's query: "
			"`general_web_search`, `extract_web_content`, `news_search`, `weather_search`, and `find_interesting_links`. "
			"Make multiple tool calls in a single turn if they address distinct information needs. Do not repeat tool calls with the same parameters.\n"
			"2.  **Deep Dive for Full Context:**\n"
			"    *   Use `general_web_search` to find relevant links and initial descriptions. For any promising link that appears to directly answer the user's query or provide crucial context, "
			"        **immediately** use `extract_web_content` to retrieve its complete textual content. You can call multiple `extract_web_content` tools at once after a `general_web_search`.\n"
			"    *   If initial searches (`general_web_search` or `news_search`) do not yield sufficient detail, consider using `extract_web_content` on *relevant subpages or linked URLs* found within previously extracted content "
			"        to deepen your understanding and gather all necessary context for the user's query. Iterate this process until no further new, relevant information can be gathered from a source.\n"
			"3.  **Timeliness & Specificity:** Pay close attention to the timeliness of information required by the query. Use the `freshness` parameter in relevant tools when current information is essential.\n"
			"4.  **Complementary Resources:** **Always** use `find_interesting_links` to identify and present additional, relevant links related to your findings for further exploration by the user. "
			"    These links are supplementary resources and should *not* be used to retrieve more content via `extract_web_content`.\n"
			"5.  **Image Generation Note:** Be aware that `general_web_search` and `news_search` tools will automatically save related images for the layout AI. Your focus is gathering comprehensive textual information; the layout AI will handle visual presentation.\n\n"

			"**REPORTING STANDARDS (for Layout AI Consumption):**\n"
			" *   **Comprehensive & Unsummarized:** Your output must be long, containing **all gathered information** relevant to the query without any summarization. Include all quantitative, qualitative, and contextual details from your research.\n"
			" *   **Precise Attribution:** Every piece of information must be explicitly cited with its original source link in the format `[Descriptive Text](URL)`. Ensure all links are real, non-empty, and directly correspond to the information provided.\n"
			" *   **Query Fulfillment:** Continue researching and gathering information until you have meticulously confirmed that you have collected **ALL necessary and relevant information to fully and completely answer the user's original query**, and there are no remaining unaddressed gaps. Only then, provide the final comprehensive report.\n\n"

			"The **ONLY** valid tool calls for you are: `general_web_search`, `extract_web_content`, `news_search`, `weather_search`, `find_interesting_links`."
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

				formatted_messages = self.prompt_template.invoke({"chat_history": messages}).to_messages()

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