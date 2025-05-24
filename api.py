from flask import Flask, request, Response, jsonify, send_from_directory
from tools import general_web_search, extended_web_search, find_interesting_links, news_search, weather_search
from flask_cors import CORS
import json
import os
from optimized_langchain_agent import OptimizedLangchainAgent
from planner_agent import PlannerAgent

app = Flask(__name__)
CORS(app)

# Instancia global del agente, igual que en el ejemplo
global_langchain_agent = OptimizedLangchainAgent(
	tools=[general_web_search, find_interesting_links, news_search, weather_search, extended_web_search],
	optimizations_enabled=False,
)

# Instancia global del agente de planificación exhaustiva
planner_agent = PlannerAgent(verbose_agent=True)

@app.route('/search', methods=['POST'])
def search():
	data = request.get_json()
	query = data.get('query')
	chat_history = data.get('chat_history', [])
	if not query:
		return jsonify({'error': 'Missing query parameter'}), 400
	from datetime import datetime
	now = datetime.now()
	today_str = now.strftime('%A, %d %B %Y')
	time_str = now.strftime('%H:%M')
	system_date = f"Today is {today_str}, and the current time is {time_str}."
	prompt = (
		f"{system_date}\n"
		"Below is the conversation history between a user and an assistant. Use this context to answer coherently and relevantly in the user's language.\n"
		"--- Conversation History ---\n"
	)
	for msg in chat_history:
		if msg['role'] == 'user':
			prompt += f"User: {msg['content']}\n"
		elif msg['role'] == 'assistant':
			prompt += f"Assistant: {msg['content']}\n"
	prompt += ("--- End of History ---\n"
			   "Now, this is the user prompt.\n"
			   f"User: {query}\n")
	def generate():
		for token in global_langchain_agent.run_layout(prompt):
			yield token
	return Response(generate(), mimetype='text/plain')

# You can implement similar streaming for /news and /links if needed
# For now, keep them as normal endpoints
@app.route('/news', methods=['POST'])
def news():
	data = request.get_json()
	query = data.get('query')
	k = data.get('k', 5)
	freshness = data.get('freshness')
	if not query:
		return jsonify({'error': 'Missing query parameter'}), 400
	try:
		result = news_search.invoke({'query': query, 'k': k, 'freshness': freshness})
		return jsonify({'news': result})
	except Exception as e:
		return jsonify({'error': str(e)}), 500

@app.route('/links', methods=['POST'])
def links():
	data = request.get_json()
	query = data.get('query')
	k = data.get('k', 5)
	if not query:
		return jsonify({'error': 'Missing query parameter'}), 400
	try:
		result = find_interesting_links.invoke({'query': query, 'k': k})
		return jsonify({'links': result})
	except Exception as e:
		return jsonify({'error': str(e)}), 500

@app.route('/plan', methods=['POST'])
def plan():
	data = request.get_json()
	query = data.get('query')
	chat_history = data.get('chat_history', [])
	if not query:
		return jsonify({'error': 'Missing query parameter'}), 400
	from datetime import datetime
	today_str = datetime.now().strftime('%A, %d %B %Y')
	# Inyecta la fecha como primer mensaje del historial
	system_date_message = {'role': 'system', 'content': f'Today is {today_str}.'}
	chat_history_with_date = [system_date_message] + chat_history
	def generate():
		# Get the iterator from the agent ONCE
		agent_iterator = iter(planner_agent.run(query, chat_history=chat_history_with_date))
		
		# State flags
		# Ensures we only attempt to strip an initial think block at the very beginning
		initial_block_check_done = False 
		# True if we are currently inside an initial <think>...</think> block
		stripping_initial_think_block = False  
		
		buffer = "" # To accumulate tokens for checking <think> and </think>

		for token in agent_iterator:
			if not initial_block_check_done:
				# This phase is for handling the very start of the stream
				
				if not stripping_initial_think_block:
					# We are not yet inside a think block.
					# Check if the current token (plus any small preceding buffer) starts one.
					# Using lstrip on the combined content to handle leading whitespace before <think>.
					potential_start_content = (buffer + token).lstrip()
					
					if potential_start_content.startswith("<think>"):
						stripping_initial_think_block = True
						buffer += token # Accumulate the token that started/is part of <think>
						
						# Check if the block also ends within the currently buffered content
						if "</think>" in buffer:
							_, _, content_after_think = buffer.partition("</think>")
							# This initial think block is now fully processed
							initial_block_check_done = True 
							stripping_initial_think_block = False # No longer stripping
							buffer = "" # Clear buffer
							if content_after_think.strip():
								yield content_after_think # Yield content after the block
						# If </think> not yet found, continue to the next token (outer loop)
						# The buffer will hold the start of the <think> block.
						
					else:
						# The stream does not start with <think> (or leading whitespace then <think>)
						# Yield any content that was in buffer (e.g. if "<" was seen but not "<think>")
						# and the current token.
						if buffer: # Should typically be empty if we reach here unless "<" was partial
							yield buffer
						yield token
						initial_block_check_done = True # Initial check phase is over
						buffer = ""
				
				else: # stripping_initial_think_block is True
					# We are inside an initial <think> block, accumulating tokens until </think>
					buffer += token
					if "</think>" in buffer:
						_, _, content_after_think = buffer.partition("</think>")
						initial_block_check_done = True
						stripping_initial_think_block = False
						buffer = ""
						if content_after_think.strip():
							yield content_after_think
					# else, continue consuming the think block (next iteration of outer loop)
			
			else: # initial_block_check_done is True
				# The initial <think> block (if any) has been processed, or there wasn't one.
				# Yield all subsequent tokens directly.
				yield token
		
		# After the loop, if the stream ended while still in the initial check phase
		# and the buffer contains content that wasn't a <think> block.
		if not initial_block_check_done and buffer:
			if not buffer.lstrip().startswith("<think>"):
				yield buffer
			# If it was an unclosed <think> block, buffer is implicitly discarded (correct behavior)
			
	return Response(generate(), mimetype='text/plain')

@app.route('/images_list')
def images_list():
	# Devuelve la lista de archivos de la carpeta images
	images_dir = os.path.join(os.getcwd(), 'images')
	if not os.path.exists(images_dir):
		return jsonify({'images': []})
	files = [f for f in os.listdir(images_dir) if os.path.isfile(os.path.join(images_dir, f))]
	# Opcional: filtra solo imágenes
	images = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
	return jsonify({'images': images})

@app.route('/images/<path:filename>', methods=['GET', 'DELETE'])
def serve_image(filename):
	images_dir = os.path.join(os.getcwd(), 'images')
	file_path = os.path.join(images_dir, filename)
	if request.method == 'DELETE':
		try:
			if os.path.exists(file_path):
				os.remove(file_path)
				return '', 204
			else:
				return jsonify({'error': 'File not found'}), 404
		except Exception as e:
			return jsonify({'error': str(e)}), 500
	return send_from_directory(images_dir, filename)

if __name__ == '__main__':
	app.run(debug=True)
