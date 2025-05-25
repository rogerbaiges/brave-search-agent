import os
import json
import tempfile
from uuid import uuid4
from datetime import datetime

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import portalocker  # pip install portalocker

from tools import (
    general_web_search,
    extended_web_search,
    find_interesting_links,
    news_search,
    weather_search,
)
from optimized_langchain_agent import OptimizedLangchainAgent
from planner_agent import PlannerAgent

# ---------------------------------------------------------------------------
# 🌟 Helpers de concurrencia segura para conversations.json
# ---------------------------------------------------------------------------
BASE_DIR = os.getcwd()
CONV_PATH = os.path.join(BASE_DIR, "conversations.json")
LOCK_PATH = CONV_PATH + ".lock"  # Fichero de lock exclusivo


def read_conversations():
    """Carga el JSON completo de forma **atómica** y bajo lock de lectura."""
    if not os.path.exists(CONV_PATH):
        return {}

    # 🔒 Bloqueo compartido ("r") ‑ mientras esté abierto nadie podrá escribir
    with portalocker.Lock(LOCK_PATH, "r", timeout=10):
        with open(CONV_PATH, "r", encoding="utf-8") as f:
            text = f.read().strip()
    return json.loads(text) if text else {}


def write_conversations(data: dict):
    """Escribe el JSON de forma **atómica**:
    1. Bloqueo exclusivo.
    2. Volcado a fichero temporal.
    3. os.replace() => swap atómico.
    """
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    with portalocker.Lock(LOCK_PATH, "w", timeout=10):
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(CONV_PATH))
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONV_PATH)


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

# Agentes globales
search_agent = OptimizedLangchainAgent(
    tools=[general_web_search, find_interesting_links, news_search, weather_search, extended_web_search],
    optimizations_enabled=False,
)
planner_agent = PlannerAgent(verbose_agent=True)

# ---------------------------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------------------------


@app.route("/search", methods=["POST"])
def search():
    data = request.get_json()
    query = data.get("query")
    chat_history = data.get("chat_history", [])
    if not query:
        return jsonify({"error": "Missing query parameter"}), 400

    # Inyectar fecha y hora en prompt
    now = datetime.now()
    system_date = (
        f"Today is {now.strftime('%A, %d %B %Y')}, and the current time is {now.strftime('%H:%M')}."
    )

    prompt = (
        f"{system_date}\n"
        "Below is the conversation history between a user and an assistant. "
        "Use this context to answer coherently and relevantly in the user's language.\n"
        "--- Conversation History ---\n"
    )
    for msg in chat_history:
        role_prefix = "User" if msg["role"] == "user" else "Assistant"
        prompt += f"{role_prefix}: {msg['content']}\n"
    prompt += f"--- End of History ---\nNow, this is the user prompt.\nUser: {query}\n"

    # Streaming generator
    def generate():
        for token in search_agent.run_layout(prompt, user_original_query=query, empty_data_folders=False):
            yield token

    return Response(generate(), mimetype="text/plain")


@app.route("/plan", methods=["POST"])
def plan():
    data = request.get_json()
    query = data.get("query")
    chat_history = data.get("chat_history", [])
    if not query:
        return jsonify({"error": "Missing query parameter"}), 400

    system_msg = {
        "role": "system",
        "content": f"Today is {datetime.now().strftime('%A, %d %B %Y')}.",
    }
    chat_history_with_date = [system_msg] + chat_history

    def generate():
        iterator = iter(planner_agent.run(query, chat_history=chat_history_with_date))

        # ⚙️ Lógica para ignorar <think> inicial
        stripping = True
        buffer = ""
        for token in iterator:
            if stripping:
                buffer += token
                if "</think>" in buffer:
                    _, _, after = buffer.partition("</think>")
                    stripping = False
                    if after.strip():
                        yield after
                    buffer = ""
            else:
                yield token

    return Response(generate(), mimetype="text/plain")


# ------------- Conversaciones (JSON seguro) -------------


@app.route("/conversations", methods=["GET", "POST"])
def conversations():
    if request.method == "GET":
        return jsonify(read_conversations())
    # POST → sustituye TODO el JSON (sigue siendo usado por tu frontend)
    data = request.get_json() or {}
    write_conversations(data)
    return jsonify({"ok": True})


@app.route("/conversations/order", methods=["POST"])
def update_conversation_order():
    data = request.get_json() or {}
    order = data.get("order")  # Debe ser una lista de IDs en el nuevo orden
    if not order or not isinstance(order, list):
        return jsonify({"error": "Missing or invalid order"}), 400

    historico = read_conversations()
    for idx, chat_id in enumerate(order):
        if chat_id in historico:
            historico[chat_id]["order"] = idx
    write_conversations(historico)
    return jsonify({"ok": True})


@app.route("/conversation/new", methods=["POST"])
def new_conversation():
    body = request.get_json() or {}
    name = body.get("name", "Sin nombre")

    historico = read_conversations()
    # Calcula el siguiente valor de order
    if historico:
        max_order = max((c.get("order", 0) for c in historico.values()), default=0)
        new_order = max_order + 1
    else:
        new_order = 0
    new_id = str(uuid4())
    historico[new_id] = {"name": name, "messages": [], "order": new_order}
    write_conversations(historico)

    return jsonify({"id": new_id, "name": name})


@app.route("/conversation/add_message", methods=["POST"])
def add_message():
    body = request.get_json() or {}
    chat_id = body.get("id")
    message = body.get("message")
    if not chat_id or not message:
        return jsonify({"error": "Missing id or message"}), 400

    historico = read_conversations()
    if chat_id not in historico:
        return jsonify({"error": "Chat not found"}), 404

    historico[chat_id]["messages"].append(message)
    write_conversations(historico)
    return jsonify({"ok": True})


@app.route("/conversation/delete", methods=["POST"])
def delete_conversation():
    body = request.get_json() or {}
    chat_id = body.get("id")
    if not chat_id:
        return jsonify({"error": "Missing id"}), 400

    historico = read_conversations()
    if chat_id not in historico:
        return jsonify({"error": "Chat not found"}), 404

    del historico[chat_id]
    write_conversations(historico)
    return jsonify({"ok": True})


# -------- Imágenes --------


@app.route("/images_list")
def images_list():
    images_dir = os.path.join(BASE_DIR, "images")
    if not os.path.exists(images_dir):
        return jsonify({"images": []})
    files = [f for f in os.listdir(images_dir) if os.path.isfile(os.path.join(images_dir, f))]
    images = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))]
    return jsonify({"images": images})


@app.route("/images/<path:filename>", methods=["GET", "DELETE"])
def serve_image(filename):
    images_dir = os.path.join(BASE_DIR, "images")
    file_path = os.path.join(images_dir, filename)

    if request.method == "DELETE":
        if os.path.exists(file_path):
            os.remove(file_path)
            return "", 204
        return jsonify({"error": "File not found"}), 404

    return send_from_directory(images_dir, filename)


@app.route("/images_for_message/<chat_id>/<int:msg_index>")
def images_for_message(chat_id, msg_index):
    historico = read_conversations()
    chat = historico.get(chat_id, {})
    messages = chat.get("messages", [])
    if 0 <= msg_index < len(messages):
        images = messages[msg_index].get("images", [])
        full_paths = [f"/images/{img}" for img in images]
        return jsonify({"images": full_paths})
    return jsonify({"images": []})


# ---------------- Otros endpoints reutilizados ----------------


@app.route("/news", methods=["POST"])
def news():
    data = request.get_json()
    query = data.get("query")
    k = data.get("k", 5)
    freshness = data.get("freshness")
    if not query:
        return jsonify({"error": "Missing query parameter"}), 400
    try:
        result = news_search.invoke({"query": query, "k": k, "freshness": freshness})
        return jsonify({"news": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/links", methods=["POST"])
def links():
    data = request.get_json()
    query = data.get("query")
    k = data.get("k", 5)
    if not query:
        return jsonify({"error": "Missing query parameter"}), 400
    try:
        result = find_interesting_links.invoke({"query": query, "k": k})
        return jsonify({"links": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Si quieres eliminar threading por completo:
    #   app.run(debug=True, threaded=False)
    app.run(debug=True)
