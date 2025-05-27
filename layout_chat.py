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
from config import LAYOUT_MODEL, VERBOSE, IMAGES_DIR # Assuming config.py is correctly set up


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
"""You are an expert creative assistant transforming provided text and image data into exceptionally well-structured, visually appealing, engaging, and **modern HTML content**. Your output is the final product, designed for a **superior visual and textual experience**.

**Core Instructions:**
1.  **HTML Only Output:** Your entire response must be *only* the enhanced HTML content. Strictly NO `<style>` tags, inline `style` attributes, `<script>` tags, comments, preambles, or additional text.
2.  **Content Integrity:** Maintain all factual information from 'Main Content'. Do NOT invent content, facts, or answers; only use relevant provided information.
3.  **Semantic HTML & Dynamic Layouts:** Use *only* semantic HTML elements. Go beyond linear; strive for **varied, dynamic layouts** (e.g., card-like `<article>/<section>`, grid-like `<dl>`, side-by-side using semantic grouping like `<div>` or `<section>`) to make information intuitive and engaging. Utilize `<h1>`-`<h6>`, `<p>`, `<ul>`, `<ol>`, `<dl>`, `<strong>`, `<em>`, `<blockquote>`, `<pre><code>`, `<table>` (for tabular data), `<figure>` (with `<img>`, `alt`, `<figcaption>`), `<details>`/`<summary>`, `<a href>`, `<hr>`, `<abbr>`, `<mark>`, `<time>`.
4.  **Visual Flow & Readability:** Break long text into shorter paragraphs. Use lists for enumerations. Employ clear heading hierarchy. Structure content to guide the eye and facilitate quick understanding.
5.  **Image Integration (If 'Content Images' provided):** Insert images using `<figure>` (with descriptive `alt` for `<img>` and a relevant `<figcaption>`). Place images where most relevant to the text. Do NOT use text or information *within* images as content. Do NOT invent image content or use placeholders; reference ONLY provided images. Avoid repeating the same image multiple times in the output. Avoid including images of plots, posters, or other visualizations that are not directly related to the text content. If the image is not visually relevant to the text, do not include it in the output.
6.  **Layout Inspiration (If 'Layout Inspiration Screenshots' provided):** Use *solely* for high-level structural and organizational ideas; do NOT replicate visual styling (colors, fonts, specific spacing).
7.  **Link Handling (CRITICAL):** PRESERVE REAL, PROVIDED LINKS (`<a href="URL">Descriptive Text</a>`) EXACTLY as given in 'Main Content'. Do NOT invent, create, or generate any new, placeholder (e.g., `example.com`), or misleading links. Be meticulous with accuracy, ensuring correct URL and descriptive text from input.
""")



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
			user_original_query: str,
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
			print(f"--- LayoutChat: Original User Query: {user_original_query} ---")
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

		# Limit images
		layout_inspiration_screenshots = layout_inspiration_screenshots[:2] # Limit to first 2 screenshots
		content_images = content_images[:4] # Limit to first 4 images
		
		# Initialize human message content list
		human_message_content: List[Dict[str, Any]] = []

		# --- NEW ORDERING STARTS HERE ---

		# Add layout inspiration screenshots first
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

		# Add content images second
		if content_images:
			processed_content_images = 0
			human_message_content.append({"type": "text", "text": "\n\n--- Content Images (for integration) ---"})
			for i, image_input in enumerate(content_images):
				base64_image = self._encode_image(image_input)
				mime_type = self._get_image_mime_type(image_input)
				if base64_image:
					# Use image type for direct embedding in the prompt
					human_message_content.append({
						"type": "image",
						"source_type": "base64",
						"mime_type": mime_type,
						"data": base64_image
					})
					# Provide a web-reference hint for the LLM to use in HTML
					# Assuming IMAGES_DIR from config, or a similar path if images are served
					web_ref = os.path.basename(image_input) # Extract filename
					human_message_content.append({
						"type": "text",
						"text": (
							f"[Content Image {i+1}. Please embed with "
							f'<img src=\"src/assets/images/{web_ref}\">]'
						)
					})
					processed_content_images +=1
				else:
					if self.verbose: print(f"--- LayoutChat: Failed to encode content image {i+1} ---", file=sys.stderr)
					human_message_content.append({"type": "text", "text": f"[Note: Content Image {i+1} could not be processed.]"})
			if self.verbose and processed_content_images > 0: print(f"--- LayoutChat: Added {processed_content_images} content images to prompt ---")

		# Add the main text content last
		human_message_content.append(
			{
				"type": "text",
				"text": (
					f"Please reformat and enhance the following main content. "
					f"The original user query was: '{user_original_query}'. "
					f"Integrate context from 'content images' (if provided) and "
					f"use 'layout inspiration screenshots' (if provided) to guide the visual style. "
					f"Respond with the best format in order to answer my initial query with an understandable, clear way for me."
					f"Only answer with the final HTML content, no additional text or explanations.\n\n"
					f"Main Content:\n---\n{agent_output_str}\n---"
				)
			}
		)

		# --- NEW ORDERING ENDS HERE ---


		# Construct the full list of messages for the layout model
		messages_for_layout_llm: List[BaseMessage] = [
			SystemMessage(content=self.system_message)
		]
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

			if self.verbose:
				print(f"\n--- LayoutChat: Final response from {self.layout_model_name} (length: {len(final_response_str)}) ---")
				print(final_response_str)

		except Exception as e:
			error_message = f"[LayoutChat Error: Error during layout model streaming: {e}]"
			yield error_message
			if self.verbose:
				import traceback
				traceback.print_exc(file=sys.stderr)
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

	# IMPORTANT: For testing, ensure 'screenshot.png' exists in your current directory,
	# or provide a real path to an image.
	# The `IMAGES_DIR` from `config` is used as a hint for the LLM to generate the HTML path,
	# but `_encode_image` directly reads from the provided `content_images_paths`.
	content_images_paths = ["screenshot.png"] # Replace with actual path(s) to content-related images
	layout_inspiration_paths = [] # Replace with actual path(s) to layout inspiration images
	# Example with inspiration: layout_inspiration_paths = ["layout_inspiration_style1.png"]

	# Check if dummy/example images exist to avoid errors if not present
	import os
	content_images_paths = [p for p in content_images_paths if os.path.exists(p)]
	layout_inspiration_paths = [p for p in layout_inspiration_paths if os.path.exists(p)]


	print("--- Example Usage of LayoutChat ---")
	layout_chat = LayoutChat(verbose=True) # html_output was not a parameter in __init__

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