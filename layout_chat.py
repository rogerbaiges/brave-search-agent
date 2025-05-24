import sys
import base64
import io
from typing import List, Iterator, Union, Dict, Any

from PIL import Image # For image handling

# Langchain imports
from langchain_ollama.chat_models import ChatOllama
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, BaseMessage

# Model names and verbose setting import
from config import LAYOUT_MODEL, VERBOSE

# Removed: from optimized_langchain_agent import OptimizedLangchainAgent (no longer needed here)


class LayoutChat:
	"""
	A chat class that uses a layout-focused LLM (vision-capable) to
	enhance and reformat content, potentially incorporating images into
	the final presentation and taking inspiration from layout screenshots.
	"""
	def __init__(self,
				 layout_model_name: str = LAYOUT_MODEL,
				 verbose: bool = VERBOSE):
		self.layout_model_name = layout_model_name
		self.verbose = verbose
		self.chat_history: List[BaseMessage] = [] # Stores conversation history for LayoutChat

		try:
			self.llm = ChatOllama(model=self.layout_model_name, temperature=0.2)
			# Simple connection check (invoke with a short text)
			_ = self.llm.invoke("Connection test.")
			if self.verbose:
				print(f"Successfully connected to Ollama layout model '{self.layout_model_name}'.")
		except Exception as e:
			print(f"Error initializing/connecting to Ollama layout model '{self.layout_model_name}'. Details: {e}", file=sys.stderr)
			sys.exit(1)

		self.layout_system_prompt = (
			"You are an expert creative assistant specializing in transforming provided text and image data into exceptionally well-structured, visually appealing, and engaging markdown content. Your output is the final product for the user.\n\n"
			"**Primary Goal:** Reformat and enhance the given 'Main Content' to be clear, scannable, and aesthetically pleasing using markdown. Integrate context from 'Content Images' naturally, and draw stylistic inspiration from 'Layout Inspiration Screenshots' if provided.\n\n"
			"**Core Instructions:**\n"
			"1.  **Content Integrity:** Maintain all factual information from the 'Main Content'. Your role is presentation and enhancement, NOT new content generation or fact invention.\n"
			"2.  **Markdown Mastery:** Utilize a full range of markdown for formatting: headings (#, ##, ###), subheadings, bold (**text**), italics (_text_ or *text*), bullet points (- or *), numbered lists, blockquotes (>), code blocks (```), and tables (if appropriate for the data).\n"
			"3.  **Visual Flow and Readability:**\n"
			"    *   Break up long paragraphs into shorter, digestible ones.\n"
			"    *   Use lists extensively for enumerated items, steps, or key features.\n"
			"    *   Employ headings and subheadings to create a clear hierarchy.\n"
			"    *   Strategically use bolding and italics to emphasize key terms or takeaways.\n"
			"4.  **Image Integration (If 'Content Images' are provided):**\n"
			"    *   Weave descriptions or references to the 'Content Images' into the text where they are most relevant. You might say, 'As seen in the provided image of [subject]...' or 'The chart (see Content Image X) illustrates...'.\n"
			"    *   Do NOT invent image content. Only refer to what can be inferred from the fact that images were provided.\n"
			"5.  **Layout Inspiration (If 'Layout Inspiration Screenshots' are provided):**\n"
			"    *   Observe the style of headings, list formatting, use of whitespace, and overall structure in these screenshots.\n"
			"    *   Apply similar stylistic elements to your markdown output. DO NOT replicate the text content from these inspiration images; they are for visual/structural guidance only.\n"
			"6.  **Link Handling - CRITICAL:**\n"
			"    *   The 'Main Content' may contain pre-verified, real links in markdown format like `[Descriptive Text](URL)`. **PRESERVE THESE REAL LINKS EXACTLY AS THEY ARE PROVIDED AND INTEGRATE THEM SMOOTHLY.**\n"
			"    *   **ABSOLUTELY DO NOT invent, create, or generate any new URLs or links.**\n"
			"    *   **DO NOT use placeholder links, example domains (e.g., `example.com`, `yourwebsite.com`), or descriptive text that implies a link without providing a real URL from the input (e.g., `[Link to official site]`, `[More Details Here]`).**\n"
			"    *   If the 'Main Content' does not provide a specific URL for something, simply state the information without trying to create a link for it. It is better to have no link than a fake or placeholder link.\n"
			"7.  **Final Output Only:** Your entire response must be *only* the enhanced markdown content. Do not include any preambles, apologies, self-corrections, notes, or explanations of your process (e.g., 'Here is the reformatted content:', 'I have structured this as follows:'). Start directly with the formatted content (e.g., a heading or the first paragraph). Do not add any additional text before or after the markdown content (e.g., 'The provided content images and layout inspiration screenshots were used to guide the overall presentation and visual style').\n"
			"8.  **No Content Images/Layout Screenshots:** If no 'Content Images' or 'Layout Inspiration Screenshots' are provided, focus solely on reformatting and enhancing the 'Main Content' text using markdown best practices."
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


	def run(self,
			agent_output_str: str,
			content_images: List[Union[str, Image.Image]] = None,
			layout_inspiration_screenshots: List[Union[str, Image.Image]] = None
			) -> Iterator[str]:
		"""
		Receives pre-generated text output and optional images, then uses the
		LAYOUT_MODEL to enhance and reformat the text, incorporating image context
		and layout inspiration.

		Args:
			agent_output_str: The string output from a previous agent/model.
			content_images: A list of image file paths or PIL Image objects directly related to the content.
			layout_inspiration_screenshots: A list of image file paths or PIL Image objects for layout style guidance.

		Yields:
			str: Chunks of the formatted response from the LAYOUT_MODEL.
		"""
		if self.verbose:
			print(f"\n--- LayoutChat: Received Agent Output (length: {len(agent_output_str)}) ---")
			if content_images:
				print(f"--- LayoutChat: Received {len(content_images)} content image(s) ---")
			if layout_inspiration_screenshots:
				print(f"--- LayoutChat: Received {len(layout_inspiration_screenshots)} layout inspiration screenshot(s) ---")

		# 1. Prepare input for LAYOUT_MODEL
		if self.verbose: print(f"--- LayoutChat: Preparing input for {self.layout_model_name} ---")

		human_message_content: List[Dict[str, Any]] = [
			{
				"type": "text",
				"text": (
					f"Please reformat and enhance the following main content. "
					f"If 'content images' are provided (see below), integrate their context. "
					f"Use any 'layout inspiration screenshots' (also below) to guide the visual style. "
					f"Respond with the best format in order to answer my intitial query with an understandable, clear way for me."
					f"Only answer with the final markdown content, no additional text or explanations.\n\n"
					f"Main Content:\n---\n{agent_output_str}\n---"
					# f"{link_context_text}" # If you were to use the optional link extraction
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
						"type": "image_url",
						"image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
					})
					human_message_content.append({"type": "text", "text": f"[Content Image {i+1} provided for context]"})
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
			SystemMessage(content=self.layout_system_prompt)
		]
		# Add LayoutChat's own history
		messages_for_layout_llm.extend(self.chat_history)
		# Add the current complex human input
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

			# Add to LayoutChat's history
			history_human_input_summary = f"Reformatted text. Input length: {len(agent_output_str)}. "
			history_human_input_summary += f"Content images: {len(content_images) if content_images else 0}. "
			history_human_input_summary += f"Layout inspiration: {len(layout_inspiration_screenshots) if layout_inspiration_screenshots else 0}."

			self.chat_history.append(HumanMessage(content=history_human_input_summary))
			self.chat_history.append(AIMessage(content=final_response_str))

			# Limit history size (e.g., last 5 pairs / 10 messages)
			if len(self.chat_history) > 10:
				self.chat_history = self.chat_history[-10:]

		except Exception as e:
			error_message = f"[LayoutChat Error: Error during layout model streaming: {e}]"
			yield error_message
			if self.verbose:
				import traceback
				traceback.print_exc(file=sys.stderr)
			
			history_human_input_summary = f"Error processing text. Input length: {len(agent_output_str)}. "
			history_human_input_summary += f"Content images: {len(content_images) if content_images else 0}. "
			history_human_input_summary += f"Layout inspiration: {len(layout_inspiration_screenshots) if layout_inspiration_screenshots else 0}."
			self.chat_history.append(HumanMessage(content=history_human_input_summary))
			self.chat_history.append(AIMessage(content=error_message)) # Log error in history
			return

		if self.verbose: print("\n--- LayoutChat: Processing Complete ---")


if __name__ == "__main__":
	output_file = "output_layout.md" # Changed output file name

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
	layout_chat = LayoutChat(verbose=True)

	print(f"\n--- Input to LayoutChat ---")
	print("Agent Output String:")
	print(sample_agent_output)
	print(f"Content Images: {content_images_paths}")
	print(f"Layout Inspiration Screenshots: {layout_inspiration_paths}")
	print("---------------------------\n")

	response_iterator = layout_chat.run(
		agent_output_str=sample_agent_output,
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