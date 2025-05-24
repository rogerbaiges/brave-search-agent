from flask import Flask, request, Response, jsonify, send_from_directory
from tools import web_search, news_search, find_interesting_links
from flask_cors import CORS
import json
import os
from optimized_langchain_agent import OptimizedLangchainAgent
from planner_agent import PlannerAgent

app = Flask(__name__)
CORS(app)

# Instancia global del agente, igual que en el ejemplo
global_langchain_agent = OptimizedLangchainAgent(
    tools=[web_search, find_interesting_links, news_search],
    optimizations_enabled=False,
    verbose_agent=True
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
        for token in global_langchain_agent.run(prompt):
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
        started = False
        for token in planner_agent.run(query, chat_history=chat_history_with_date):
            if not started:
                # Skip initial <think> ... </think> block if present
                if token.strip().startswith("<think>"):
                    # Consume tokens until </think> is found
                    buffer = token
                    if "</think>" in buffer:
                        # Remove up to and including </think>
                        after_think = buffer.split("</think>", 1)[1]
                        if after_think.strip():
                            yield after_think
                        started = True
                        continue
                    for token in planner_agent.run(query, chat_history=chat_history_with_date):
                        buffer += token
                        if "</think>" in buffer:
                            after_think = buffer.split("</think>", 1)[1]
                            if after_think.strip():
                                yield after_think
                            started = True
                            break
                    continue
                else:
                    started = True
            yield token
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
