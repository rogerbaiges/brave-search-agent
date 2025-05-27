import sys
import base64
import io
import os
from typing import List, Iterator, Union, Dict, Any

from PIL import Image # For image handling

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, BaseMessage

# Model names and verbose setting import
from config import LAYOUT_MODEL, VERBOSE, IMAGES_DIR

# Removed: from optimized_langchain_agent import OptimizedLangchainAgent (no longer needed here)


class LayoutChat:
	"""
	A chat class that uses a layout-focused LLM (vision-capable) to
	enhance and reformat content, potentially incorporating images into
	the final presentation and taking inspiration from layout screenshots.
	"""
	def __init__(self,
			layout_model_name: str = LAYOUT_MODEL,
			verbose: bool = VERBOSE,
		):
		self.layout_model_name = layout_model_name
		self.verbose = verbose
		# self.chat_history: List[BaseMessage] = [] # REMOVED: No longer needed as history is passed via agent_output_str and user_original_query

		try:
			self.llm = ChatOllama(model=self.layout_model_name, temperature=0.2)
			# Simple connection check (invoke with a short text)
			_ = self.llm.invoke("Connection test.")
			if self.verbose:
				print(f"Successfully connected to Ollama layout model '{self.layout_model_name}'.")
		except Exception as e:
			print(f"Error initializing/connecting to Ollama layout model '{self.layout_model_name}'. Details: {e}", file=sys.stderr)
			sys.exit(1)

		self.system_message: str = (
			"You are an elite intelligence agent. Your mission is to provide a comprehensive, detailed, and contextually rich report "
			"that *directly and fully answers the user's query*. This report will be used by a separate layout AI and will NOT be seen directly by the user. "
			"Therefore, your output should be a detailed compilation of information, *not a summarized answer*. "
			"Ensure ALL relevant information is gathered with COMPLETE, UNABRIDGED context from ALL necessary sources and their subpages. "
			"Your objective is to reach a conclusive state where the user's query is unequivocally addressed with supporting data, images, and further resources.\n\n"

			"**OPERATING PROTOCOL (CONTINUOUS RESEARCH AND ASSESSMENT LOOP):**\n\n"

			"1.  **ITERATIVE RESEARCH & ANALYSIS:**\n"
			"    *   **Strategic Planning:** Before any tool use, deeply analyze the user's query: What specific information is required? What are the key entities or concepts? What are the potential gaps? "
			"        Which of the *available tools* will provide the most complete, relevant, and unabridged context to answer the query? "
			"        Do not make redundant tool calls if similar information has already been retrieved. "
			"        **Crucially: After each tool call, rigorously assess the retrieved information against the user's query.** "
			"        Does it directly answer the question? Is it complete? Are there remaining, *unaddressed aspects of the user's original query*? If yes, continue to the next step; if no, proceed to the final report generation.\n"
			"    *   **Tool Selection & Execution:** Systematically use the *provided* tools: `general_web_search`, `extended_web_search`, `find_interesting_links`, `news_search`, `weather_search`, `extract_web_content`, `image_search`. "
			"        **Only use these specified tools.** You can make multiple tool calls in a single turn if they are distinct and contribute to different parts of the overall information gathering. "
			"        Maximize parallel tool usage where appropriate.\n"
			"    *   **Exhaustive Source Exploration (Crucial for Depth):** For EVERY promising source (main pages, articles) found that directly addresses the user's query or provides critical context:\n"
			"        *   **IMMEDIATELY** use `extended_web_search` or `extract_web_content` to retrieve its COMPLETE, UNABRIDGED content, preserving ALL surrounding context. "
			"        *   Then, consider using `extract_web_content` on ALL *relevant* subpages or linked URLs *found within that extracted content* that are pertinent to the user's query. "
			"        *   Iterate this process (search, extract, explore *relevant* sub-links) only until no more *new, relevant, distinct, or critical* information directly addressing the user's query can be gathered from that branch.\n"
			"    *   **Gap Filling:** Continuously assess and fill information and context gaps *specifically related to the user's query*. Iterate tool use as many times as necessary for comprehensive coverage *of the query*.\n\n"

			"2.  **INFORMATION STANDARDS:**\n"
			"    *   **FULL DETAIL REQUIRED - NO SUMMARIZATION:** Capture ALL data types (quantitative, qualitative, procedural, contextual, future projections) with their COMPLETE supporting context. Your output is raw, rich data for the layout AI.\n"
			"    *   **ALWAYS PROVIDE FULL & ACCURATE LINKS:** Every piece of information must be traceable to its exact source page/subpage URL. No generic links or placeholders. Information without a source link is unacceptable.\n"
			"    *   **TIME & RELEVANCE:** Be aware of the current date/time and the query's relevant time period. Ensure information is up-to-date and verify the relevance of older data.\n\n"

			"3.  **STRUCTURED INTELLIGENCE REPORT & ATTRIBUTION (FOR LAYOUT AI):**\n"
			"    *   **Report Format (for each relevant source/subpage):**\n"
			"        *   Source: [Title](URL_of_specific_page/subpage) - Publication Date - Author/Publisher. Clearly indicate subpages.\n"
			"        *   **Complete Content Extract:** [The ENTIRE relevant content with FULL CONTEXT. NO SUMMARIZATION.]\n"
			"        *   Source Depth Assessment: [Brief note on subpages/sections explored and why you stopped/continued exploration of this specific source, if applicable.]\n"
			"        *   Reliability Assessment: [Brief note on source credibility.]\n"
			"        *   Useful URLs for Further Exploration: [List relevant URLs from the source, if any.]\n"
			"    *   Include Cross-Source Analysis (identifying patterns, contradictions, consensus, gaps across all gathered content) and Intelligence Synthesis (integrating ALL gathered information with full source attribution, ensuring no context is lost or information is missing *for the user's query*).\n"
			"    *   **Precise Attribution:** Every fact and detail MUST be traced to its exact source page/subpage: [Specific Detail with Full Context](URL). Use descriptive link text.\n\n"

			"4.  **MANDATORY: FURTHER ACTIONS & SUGGESTIONS FOR USER:**\n"
			"    *   **ALWAYS** use the `find_interesting_links` tool to provide suggestions for the user on what to do next. Search for relevant links for EACH part of the report (adapting the query to the specific part of the report).\n"
			"    *   These links are ADDITIONAL resources for further exploration, not the primary sources of gathered information. They must be relevant and useful.\n"
			"    *   Examples: For list items, provide a relevant link per item. For explanations, link to related articles. For complex topics, link to specific subtopics, clearly indicating correspondence.\n"
			"    *   **CRITICAL:** NEVER provide generic links, placeholders, or example domains. Links MUST be specific, relevant to parts of the report, useful, and non-empty.\n\n"

			"5.  **MANDATORY: IMAGE COMPLEMENTATION:**\n"
			"    *   **ALWAYS** use the `image_search` tool to find relevant images for the topic (for the layout AI).\n"
			"    *   Call `image_search` **AFTER** ALL relevant information has been gathered and you are ready to produce the final report structure. \n"
			"    *   Its `query` parameter should be very specific and concise to find concrete images for EACH entity or concept mentioned in the report (make a distinct query for each entity/concept, not general topics).\n"
			"    *   **AVOID** repeating the same query for `image_search`. Search for a maximum of 1 image per entity or concept.\n\n"

			"**FINAL DIRECTIVE: Only when you have meticulously confirmed that you have gathered ALL necessary and relevant information to fully and completely answer the user's *original query*, including complementary images and suggested links, AND you have processed this information to ensure there are no further *unaddressed gaps related to the query*, then you should proceed to generate the final comprehensive report (strictly following the format in point 3) for the layout AI. Otherwise, YOU MUST CONTINUE USING *the provided* TOOLS to gather remaining information or complement existing data.**"
		)

	def _encode_image(self, image_input: Union[str, Image.Image]) -> str:
		"""Encodes an image to base64."""
		try:
			if isinstance(image_input, str): # Path to image
				image = Image.open(image_input)
			elif isinstance(image_input, Image.Image):
				image = image_input
			else:
				raise ValueError("Invalid image_input type. Must be str (path) or PIL.Image.Image.")

			buffered = io.BytesIO()
			image_format = image.format if image.format else 'PNG' # Default to PNG if format not discernible
			if image.mode == 'RGBA' and image_format == 'JPEG': # JPEG doesn't support alpha
				image = image.convert('RGB')
			image.save(buffered, format=image_format)
			return base64.b64encode(buffered.getvalue()).decode('utf-8')
		except FileNotFoundError:
			if self.verbose:
				print(f"Error encoding image: File not found - {image_input}", file=sys.stderr)
			return ""
		except Exception as e:
			if self.verbose:
				print(f"Error encoding image ({type(image_input).__name__}): {e}", file=sys.stderr)
			return ""

	def _get_image_mime_type(self, image_input: Union[str, Image.Image]) -> str:
		"""Determines the MIME type of an image."""
		try:
			if isinstance(image_input, str):
				image = Image.open(image_input)
			elif isinstance(image_input, Image.Image):
				image = image_input
			else:
				return "image/png" # Default

			img_format = image.format
			if img_format == "JPEG":
				return "image/jpeg"
			elif img_format == "PNG":
				return "image/png"
			elif img_format == "GIF":
				return "image/gif"
			elif img_format == "WEBP":
				return "image/webp"
			else: # Add more formats if needed or default
				return "image/png"
		except:
			return "image/png" # Default on error
		
	def _filter_agent_output(self, agent_output_str: str) -> str:
		"""
		Filters the agent output string to remove the content in <think> to </think> tags.
		"""
		start_tag = "<think>"
		end_tag = "</think>"
		start_index = agent_output_str.find(start_tag)
		end_index = agent_output_str.find(end_tag, start_index + len(start_tag))

		if start_index != -1 and end_index != -1:
			# Remove the content between <think> and </think>
			return agent_output_str[:start_index] + agent_output_str[end_index + len(end_tag):]
		return agent_output_str


	def run(self,
			agent_output_str: str,
			user_original_query: str, # Add this parameter
			content_images: List[Union[str, Image.Image]] = None,
			layout_inspiration_screenshots: List[Union[str, Image.Image]] = None
			) -> Iterator[str]:
		"""
		Receives pre-generated text output and optional images, then uses the
		LAYOUT_MODEL to enhance and reformat the text, incorporating image context
		and layout inspiration.

		Args:
			agent_output_str: The string output from a previous agent/model.
			user_original_query: The user's original query for context.
			content_images: A list of image file paths or PIL Image objects directly related to the content.
			layout_inspiration_screenshots: A list of image file paths or PIL Image objects for layout style guidance.

		Yields:
			str: Chunks of the formatted response from the LAYOUT_MODEL.
		"""
		if self.verbose:
			print(f"\n--- LayoutChat: Received Agent Output (length: {len(agent_output_str)}) ---")
			print(f"--- LayoutChat: Original User Query: {user_original_query} ---") # Log for clarity
			if content_images:
				print(f"--- LayoutChat: Received {len(content_images)} content image(s) ---")
			if layout_inspiration_screenshots:
				print(f"--- LayoutChat: Received {len(layout_inspiration_screenshots)} layout inspiration screenshot(s) ---")

		# 1. Prepare input for LAYOUT_MODEL
		if self.verbose: print(f"--- LayoutChat: Preparing input for {self.layout_model_name} ---")

		# Filter agent output to remove <think> tags if present
		agent_output_str = self._filter_agent_output(agent_output_str)
		if self.verbose:
			print(f"--- LayoutChat: Filtered Agent Output to remove <think> tags (length: {len(agent_output_str)}) ---")

		layout_inspiration_screenshots = layout_inspiration_screenshots[:3] # Limit to first 3 screenshots
		
		human_message_content: List[Dict[str, Any]] = [
			{
				"type": "text",
				"text": (
					f"Please reformat and enhance the following main content. "
					f"The original user query was: '{user_original_query}'. " # Explicitly provide original query
					f"If 'content images' are provided (see below), integrate their context. "
					f"Use any 'layout inspiration screenshots' (also below) to guide the visual style. "
					f"Respond with the best format in order to answer my initial query with an understandable, clear way for me."
					f"Only answer with the final HTML content, no additional text or explanations.\n\n"
					f"Main Content:\n---\n{agent_output_str}\n---"
				)
			}
		]

		# Add content images
		if content_images:
			processed_content_images = 0
			human_message_content.append({"type": "text", "text": "\n\n--- Content Images (for integration) ---"})
			for i, image_input in enumerate(content_images):
				base64_image = self._encode_image(image_input)
				mime_type = self._get_image_mime_type(image_input)
				if base64_image:
					human_message_content.append({
						"type": "image",
						"source_type": "base64",
						"mime_type": mime_type,
						"data": base64_image
					})
					web_ref = os.path.basename(image_input)  # or any public URL you like
					human_message_content.append({
						"type": "text",
						"text": (
							f"[Content Image {i+1}. Please embed with "
							f'<img src=\"src/assets/images/{web_ref}\" alt=\"Image {i+1}\">]'
						)
					})
					processed_content_images +=1
				else:
					if self.verbose: print(f"--- LayoutChat: Failed to encode content image {i+1} ---", file=sys.stderr)
					human_message_content.append({"type": "text", "text": f"[Note: Content Image {i+1} could not be processed.]"})
			if self.verbose and processed_content_images > 0: print(f"--- LayoutChat: Added {processed_content_images} content images to prompt ---")


		# Add layout inspiration screenshots
		if layout_inspiration_screenshots:
			processed_layout_screenshots = 0
			human_message_content.append({"type": "text", "text": "\n\n--- Layout Inspiration Screenshots (for visual style guidance only) ---"})
			for i, image_input in enumerate(layout_inspiration_screenshots):
				base64_image = self._encode_image(image_input)
				mime_type = self._get_image_mime_type(image_input)
				if base64_image:
					human_message_content.append({
						"type": "image_url",
						"image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
					})
					human_message_content.append({"type": "text", "text": f"[Layout Inspiration Screenshot {i+1} provided for style]"})
					processed_layout_screenshots += 1
				else:
					if self.verbose: print(f"--- LayoutChat: Failed to encode layout inspiration screenshot {i+1} ---", file=sys.stderr)
					human_message_content.append({"type": "text", "text": f"[Note: Layout Inspiration Screenshot {i+1} could not be processed.]"})
			if self.verbose and processed_layout_screenshots > 0: print(f"--- LayoutChat: Added {processed_layout_screenshots} layout inspiration screenshots to prompt ---")


		# Construct the full list of messages for the layout model
		messages_for_layout_llm: List[BaseMessage] = [
			SystemMessage(content=self.system_message)
		]
		# REMOVED: messages_for_layout_llm.extend(self.chat_history)
		messages_for_layout_llm.append(HumanMessage(content=human_message_content))


		# 2. Stream response from LAYOUT_MODEL
		if self.verbose: print(f"--- LayoutChat: Streaming final response from {self.layout_model_name} ---")
		full_layout_response_content = []
		try:
			for chunk in self.llm.stream(messages_for_layout_llm):
				if isinstance(chunk, AIMessageChunk) and chunk.content:
					yield chunk.content
					full_layout_response_content.append(chunk.content)

			final_response_str = "".join(full_layout_response_content)

			# REMOVED: History management as LayoutChat is now stateless per call
			# self.chat_history.append(HumanMessage(content=history_human_input_summary))
			# self.chat_history.append(AIMessage(content=final_response_str))
			# if len(self.chat_history) > 10:
			# 	self.chat_history = self.chat_history[-10:]

			if self.verbose:
				print(f"\n--- LayoutChat: Final response from {self.layout_model_name} (length: {len(final_response_str)}) ---")
				print(final_response_str)

		except Exception as e:
			error_message = f"[LayoutChat Error: Error during layout model streaming: {e}]"
			yield error_message
			if self.verbose:
				import traceback
				traceback.print_exc(file=sys.stderr)
			
			# REMOVED: History management as LayoutChat is now stateless per call
			# self.chat_history.append(HumanMessage(content=history_human_input_summary))
			# self.chat_history.append(AIMessage(content=error_message)) # Log error in history
			return

		if self.verbose: print("\n--- LayoutChat: Processing Complete ---")


if __name__ == "__main__":
	output_file = "output_layout.html" # Changed output file name

	# Example agent output string
	sample_agent_output = (
		"The capital of France is Paris. Paris is known for its art, fashion, gastronomy and culture. "
		"Its 19th-century cityscape is crisscrossed by wide boulevards and the River Seine. "
		"Beyond such landmarks as the Eiffel Tower and the 12th-century, Gothic Notre-Dame cathedral, "
		"the city is known for its cafe culture and designer boutiques along the Rue du Faubourg Saint-Honoré."
		"\n\nKey Landmarks:\n- Eiffel Tower\n- Louvre Museum\n- Notre-Dame Cathedral\n- Arc de Triomphe\n"
		"Paris is also a major global hub for finance, diplomacy, commerce, fashion, science, and the arts."
		" For more details, see [Official Paris Tourism](https://en.parisinfo.com)."
	)
	# Example user original query
	sample_user_query = "Tell me about Paris and its famous landmarks."

	# For testing, create dummy image files or use actual paths
	# e.g., create empty files:
	# open("content_image_paris.png", "a").close()
	# open("layout_inspiration_style1.png", "a").close()
	# Ensure these files exist if you uncomment the image lists below.
	# If not, the image processing will be skipped gracefully.

	content_images_paths = ["screenshot.png"] # Replace with actual path(s) to content-related images
	layout_inspiration_paths = [] # Replace with actual path(s) to layout inspiration images
	# Example with inspiration: layout_inspiration_paths = ["layout_inspiration_style1.png"]

	# Check if dummy/example images exist to avoid errors if not present
	import os
	content_images_paths = [p for p in content_images_paths if os.path.exists(p)]
	layout_inspiration_paths = [p for p in layout_inspiration_paths if os.path.exists(p)]


	print("--- Example Usage of LayoutChat ---")
	layout_chat = LayoutChat(verbose=True, html_output=True)

	print(f"\n--- Input to LayoutChat ---")
	print("Agent Output String:")
	print(sample_agent_output)
	print("Original User Query:")
	print(sample_user_query)
	print(f"Content Images: {content_images_paths}")
	print(f"Layout Inspiration Screenshots: {layout_inspiration_paths}")
	print("---------------------------\n")

	response_iterator = layout_chat.run(
		agent_output_str=sample_agent_output,
		user_original_query=sample_user_query, # Pass the original query
		content_images=content_images_paths,
		layout_inspiration_screenshots=layout_inspiration_paths
	)

	# Empty the output file before writing
	with open(output_file, "w", encoding="utf-8") as f: # Added encoding
		f.write("")

	print(f"\n--- LayoutChat Enhanced Output (streaming to console and {output_file}) ---")
	for chunk in response_iterator:
		print(chunk, end="", flush=True)
		# Save the final response to a file
		with open(output_file, "a", encoding="utf-8") as f: # Added encoding
			f.write(chunk)
	print() # Newline after streaming

	print(f"\n--- LayoutChat: Final enhanced response saved to {output_file} ---")

	# Example of a second run to show history usage (optional)
	# print("\n--- Second Run (testing history) ---")
	# another_sample_output = "This is a second, shorter text. It should be formatted nicely too."
	# response_iterator_2 = layout_chat.run(
	# 	agent_output_str=another_sample_output
	# )
	# print(f"\n--- LayoutChat Enhanced Output for second run ---")
	# for chunk in response_iterator_2:
	# 	print(chunk, end="", flush=True)
	# print()
	# print("--- End of Second Run ---")