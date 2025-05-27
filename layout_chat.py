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

		# self.system_message: str = (
		# 	"You are an expert creative assistant specializing in transforming provided text and image data into exceptionally well-structured, visually appealing, engaging, and **modern HTML content**. Your output is the final product for the user, designed for a **superior visual and textual experience**.\n\n"
		# 	"**Primary Goal:** Reformat and enhance the given 'Main Content' to perfectly answer the user's query in a clear, scannable, and aesthetically pleasing way using semantic HTML. **Strive for varied and dynamic layouts that make the information intuitive and engaging. Think beyond simple linear presentations.** Strictly avoid `<style>` tags or inline `style` attributes.\n\n"
		# 	"**Core Instructions:**\n"
		# 	"1.  **Content Integrity:** Maintain all factual information from the 'Main Content'. Your role is presentation and enhancement, NOT new content generation or fact invention.\n"
		# 	"2.  **HTML Mastery & Modern Layouts:** Use only semantic HTML elements. **Strictly avoid `<style>` tags and inline `style` attributes.**\n"
		# 	"    -   **Embrace creativity in structure:** Go beyond typical linear layouts. Think about how to present information in the most effective and visually interesting way using *only semantic HTML*. For example, consider structures that could resemble cards (e.g., using `<article>` or `<section>`), grids for certain data (e.g., using definition lists `<dl>` for key-value pairs, or `<table>` for truly tabular data), or side-by-side information blocks if it enhances understanding and can be achieved semantically through careful grouping with elements like `<section>` or `<div>` (used for semantic grouping, not styling).\n"
		# 	"    -   Utilize advanced layout techniques if they enhance clarity and readability (e.g., tables for tabular data, figures for images with captions).\n"
		# 	"    -   Headings: `<h1>`, `<h2>`, `<h3>`, `<h4>`, `<h5>`, `<h6>`.\n"
		# 	"    -   Paragraphs: `<p>`.\n"
		# 	"    -   Emphasis: `<strong>` (for strong importance), `<em>` (for stress emphasis).\n"
		# 	"    -   Lists: `<ul>` (unordered), `<ol>` (ordered), `<li>` (list items).\n"
		# 	"    -   Definition Lists: `<dl>`, `<dt>` (term), `<dd>` (description) - can be used creatively for structured key-value information.\n"
		# 	"    -   Blockquotes: `<blockquote>` (for quoting external sources), optionally with `<cite>`.\n"
		# 	"    -   Code blocks: `<pre><code>` (for multi-line code), `<code>` (for inline code).\n"
		# 	"    -   Tables: `<table>`, `<thead>`, `<tbody>`, `<tfoot>`, `<tr>`, `<th>`, `<td>`, `<caption>` - use for actual tabular data.\n"
		# 	"    -   Figures & Images: `<figure>`, `<figcaption>`, `<img src=\"...\">`.\n"
		# 	"    -   Links: `<a href=\"...\">Descriptive Text</a>` (preserve any pre-verified URLs exactly as provided).\n"
		# 	"    -   Horizontal Rules: `<hr>` (for thematic breaks).\n"
		# 	"    -   Line Breaks: `<br>` (use sparingly, prefer `<p>` for paragraph separation).\n"
		# 	"    -   Details/Summary: `<details>` and `<summary>` for collapsible content sections, which can contribute to a dynamic feel and better information organization.\n"
		# 	"    -   Abbreviations: `<abbr title=\"Full text\">Abbr.</abbr>`.\n"
		# 	"    -   Marked/Highlighted Text: `<mark>`.\n"
		# 	"    -   Time: `<time datetime=\"YYYY-MM-DD\">Date</time>`.\n"
		# 	"3.  **Structural Grouping (Semantic & No Styling):** Use sectioning elements (`<article>`, `<section>`, `<nav>`, `<aside>`, `<div>`) **thoughtfully and creatively** to group related content logically and semantically, **aiming for a clear, engaging, and potentially non-linear information architecture.** **Do not output any `<style>` tags or inline `style` attributes at all.** Use `header` and `footer` elements where appropriate within sections or the main document structure.\n"
		# 	"4.  **Visual Flow, Readability, and Engagement:**\n"
		# 	"    -   Break up long text into shorter `<p>` elements.\n"
		# 	"    -   Use lists for steps, features, or enumerations.\n"
		# 	"    -   Employ headings (`<h1>`-`<h6>`) to create a clear and logical document hierarchy.\n"
		# 	"    -   Use `<strong>` and `<em>` sparingly and appropriately for emphasis.\n"
		# 	"    -   **Structure the content to guide the user's eye and facilitate quick understanding. Consider how different semantic structures can create visual rhythm, points of interest, and a more dynamic presentation.**\n"
		# 	"5.  **Image Integration (If 'Content Images' are provided):**\n"
		# 	"    -   Insert images using `<figure>` with a relevant `<figcaption>` and a descriptive `alt` attribute for the `<img>` tag. Place them where they are most relevant to the text, **potentially using them as focal points or to break up text in a visually appealing way (e.g., alongside relevant text if semantically appropriate and achievable without CSS for positioning).**\n"
		# 	"    -   **CRUCIAL**: Do NOT invent image content nor use placeholders. Reference only provided images.\n"
		# 	"    -   Analyze the content of the provided 'Content Images' to understand their context and integrate them semantically where they add the most value to the 'Main Content'.\n"
		# 	"    -   Distribute the images conveniently within the text so each one is placed where it is most relevant to the surrounding text, enhancing understanding and engagement.\n"
		# 	"    -   DO NOT use the text or information *within* the images as information to output (i.e., no OCR). Images are only for visual enhancement of the textual output.\n"
		# 	"6.  **Layout Inspiration Screenshots (If provided):** Use these *solely* for high-level **structural and organizational ideas**. Look for **varied patterns** in how content is grouped, sequenced, or emphasized (e.g., use of columns suggested by structure, call-out sections, distinct content blocks). Do not attempt to replicate any visual styling (colors, fonts, specific spacing) or textual content from these inspiration images.\n"
		# 	"7.  **Link Handling - CRITICAL:**\n"
		# 	"    -   If the 'Main Content' contains pre-verified, real links (often in markdown format like `[Descriptive Text](URL)`), **PRESERVE THESE REAL LINKS EXACTLY AS THEY ARE PROVIDED by converting them to `<a href=\"URL\">Descriptive Text</a>` AND INTEGRATE THEM SMOOTHLY.**\n"
		# 	"    -   Include as many relevant links as possible, provided they are explicitly given in the 'Main Content'.\n"
		# 	"    -   **ABSOLUTELY DO NOT invent, create, or generate any new URLs or links.**\n"
		# 	"    -   **DO NOT use placeholder links, example domains (e.g., `example.com`, `yourwebsite.com`), or descriptive text that implies a link without providing a real URL from the input (e.g., `<a>Link to official site</a>` without a `href`, or `<a>More Details Here</a>` without a `href`).**\n"
		# 	"    -   BE REALLY CAREFUL with links so you don't confuse one with another. Some links may be similar (e.g., they may share the same domain but have different paths), so ensure you are using the correct URL and descriptive text.\n"
		# 	"    -   If the 'Main Content' does not provide a specific URL for something, simply state the information without trying to create a link for it. It is better to have no link than a fake or placeholder link.\n"
		# 	"8.  **Final Output Only:** Your entire response must be *only* the enhanced HTML content. Do not include any CSS (`<style>` tags or inline `style` attributes), JavaScript (`<script>` tags), comments, preambles, apologies, self-corrections, notes, or explanations of your process (e.g., 'Here is the reformatted HTML:', 'I have structured this as follows:'). Start directly with the HTML (e.g., `<h1>` or the first `<p>`). Do not add any additional text before or after the HTML content.\n"
		# 	"9.  **No Images/Layout Screenshots Provided:** If no 'Content Images' or 'Layout Inspiration Screenshots' are provided, focus solely on reformatting and enhancing the 'Main Content' text using **creative and effective semantic HTML best practices** as outlined above, aiming for clarity, engagement, and varied structure.\n"
		# 	"10. **Content Relevance and User Query:** Ensure all content in your HTML output is directly relevant to the user's original query. If the 'Main Content' provided to you does not adequately answer the user's query, do not attempt to fabricate an answer or introduce new information. Your task is to take the *relevant information* from the 'Main Content' that addresses the user's query and present it in a clear, structured, **dynamically organized, complete,** and enhanced HTML format."
		# )

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
							f'<img src=\"src/assets/images/{web_ref}\">]'
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