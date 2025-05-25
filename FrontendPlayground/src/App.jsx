import { useState, useEffect, useRef } from 'react'
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Bot, Send, Paperclip, Plus, Menu, Trash2, Search, Sparkles, MessageSquare, Edit3, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { v4 as uuidv4 } from 'uuid'

// Helper function for streaming fetch
async function callBackendStream({ endpoint, body, onToken }) {
  const response = await fetch(`http://localhost:5000/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let done = false;
  let buffer = '';
  while (!done) {
    const { value, done: doneReading } = await reader.read();
    done = doneReading;
    if (value) {
      buffer += decoder.decode(value, { stream: true });
      onToken(buffer);
    }
  }
  onToken(buffer, true); // Final call
}

export default function BravePlayground() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [threadId, setThreadId] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [imagesCleared, setImagesCleared] = useState(false);
  const [planningEnabled, setPlanningEnabled] = useState(false);
  const messagesEndRef = useRef(null)

  // --- NUEVOS ESTADOS PARA GESTIÓN DE CHATS ---
  const [historico, setHistorico] = useState({});
  const [chatId, setChatId] = useState(null);
  const [chatName, setChatName] = useState('Nueva conversación');
  const [showNewChatModal, setShowNewChatModal] = useState(false);
  const [showRenameModal, setShowRenameModal] = useState(false);
  const [newChatName, setNewChatName] = useState('');
  const [renameChatId, setRenameChatId] = useState(null);
  const [renameChatName, setRenameChatName] = useState('');

  /* --------------------------------------------------------------------
   *  EFFECTS
   * ------------------------------------------------------------------*/
  // 1️⃣  Evita memorias de viewport móviles incorrectas (100vh quita el navbar)
  useEffect(() => {
    const setVh = () => {
      const vh = window.innerHeight * 0.01;
      document.documentElement.style.setProperty('--vh', `${vh}px`);
    };
    setVh();
    window.addEventListener('resize', setVh);
    return () => window.removeEventListener('resize', setVh);
  }, []);

  // 2️⃣  Limpieza de imágenes residuales al arrancar ✨
  useEffect(() => {
    fetch('http://localhost:5000/images_list')
      .then(res => res.json())
      .then(data => {
        if (data.images && data.images.length) {
          Promise.all(
            data.images.map(img =>
              fetch(`http://localhost:5000/images/${img}`, { method: 'DELETE' })
            )
          ).then(() => setImagesCleared(true));
        } else {
          setImagesCleared(true);
        }
      });
  }, []);

  // 3️⃣  Mantener scroll al fondo en cada render
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 4️⃣  Traer histórico de conversaciones al montar
  useEffect(() => {
    fetch('http://localhost:5000/conversations')
      .then(res => res.json())
      .then(data => {
        setHistorico(data);
        const ids = Object.keys(data);
        if (ids.length) setChatId(ids[0]);
      });
  }, []);

  // 5️⃣  Cuando cambia chatId ⇒ cargar mensajes y nombre
  useEffect(() => {
    if (chatId && historico[chatId]) {
      setMessages(historico[chatId].messages || []);
      setChatName(historico[chatId].name || 'Nueva conversación');
    } else if (chatId) {
      setMessages([]);
      setChatName('Nueva conversación');
    }
  }, [chatId, historico]);

  /* --------------------------------------------------------------------
   *  HANDLERS DE CONVERSACIÓN (crear / renombrar / borrar)
   * ------------------------------------------------------------------*/
  function openNewChatModal() {
    setNewChatName('');
    setShowNewChatModal(true);
  }

  async function createChat() {
    const name = newChatName.trim() || 'Sin nombre';
    const res = await fetch('http://localhost:5000/conversation/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    setHistorico(prev => ({
      ...prev,
      [data.id]: { name: data.name, messages: [] },
    }));
    setChatId(data.id);
    setShowNewChatModal(false);
    setChatName(data.name);
    setMessages([]);
  }

  function openRenameModal(id, name) {
    setRenameChatId(id);
    setRenameChatName(name);
    setShowRenameModal(true);
  }

  function saveRenameChat() {
    setHistorico(prev => ({
      ...prev,
      [renameChatId]: {
        ...prev[renameChatId],
        name: renameChatName.trim() || 'Sin nombre',
      },
    }));
    if (chatId === renameChatId) setChatName(renameChatName.trim() || 'Sin nombre');
    setShowRenameModal(false);
  }

  async function deleteChat(id) {
    await fetch('http://localhost:5000/conversation/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    });
    setHistorico(prev => {
      const nuevo = { ...prev };
      delete nuevo[id];
      return nuevo;
    });
    if (chatId === id) {
      const ids = Object.keys(historico).filter(cid => cid !== id);
      setChatId(ids.length ? ids[ids.length - 1] : null);
      setMessages([]);
      setChatName('Nueva conversación');
    }
  }

  /* --------------------------------------------------------------------
   *  STREAMING & RENDER MENSAJES
   * ------------------------------------------------------------------*/
  // 👉 Track imágenes existentes para asociar solo las nuevas a la respuesta
  const imagenesPreviasRef = useRef([]);
  useEffect(() => {
    fetch('http://localhost:5000/images_list')
      .then(res => res.json())
      .then(data => {
        imagenesPreviasRef.current = data.images || [];
      });
  }, []);

  const handleSend = async () => {
    if (!input.trim()) return;

    // Añadir mensaje usuario al estado & backend
    const userMsg = {
      role: 'user',
      content: input,
      images: [],
      timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    if (chatId) {
      fetch('http://localhost:5000/conversation/add_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: chatId, message: userMsg }),
      });
    }

    // Placeholder asistente (streaming)
    setMessages(prev => [
      ...prev,
      { role: 'assistant', content: '', images: [], timestamp: new Date().toISOString() },
    ]);
    const assistantIndex = messages.length + 1;
    const chatHistory = messages.map(m => ({ role: m.role, content: m.content }));

    setInput('');
    setLoading(true);
    let firstTokenReceived = false;

    try {
      await callBackendStream({
        endpoint: planningEnabled ? 'plan' : 'search',
        body: { query: userMsg.content, chat_history: chatHistory },
        onToken: async (token, done) => {
          // Añadimos tokens progresivamente
          setMessages(prev => {
            const updated = [...prev];
            const prevContent = updated[assistantIndex]?.content || '';
            updated[assistantIndex] = {
              ...updated[assistantIndex],
              role: 'assistant',
              content: prevContent + token.replace(prevContent, ''),
            };
            return updated;
          });

          // Quitamos spinner al primer token
          if (!firstTokenReceived && token && !done) {
            setLoading(false);
            firstTokenReceived = true;
          }

          // Si hemos terminado: añadimos imágenes nuevas y persistimos resultado
          if (done) {
            const res = await fetch('http://localhost:5000/images_list');
            const data = await res.json();
            const nuevas = (data.images || []).filter(
              img => !imagenesPreviasRef.current.includes(img),
            );
            imagenesPreviasRef.current = data.images || [];

            setMessages(prev => {
              const updated = [...prev];
              if (updated[assistantIndex]) {
                updated[assistantIndex] = {
                  ...updated[assistantIndex],
                  images: nuevas,
                };
              }
              return updated;
            });

            if (chatId) {
              const assistantMsg = {
                role: 'assistant',
                content: (messages[assistantIndex]?.content || '') + token,
                images: nuevas,
                timestamp: new Date().toISOString(),
              };
              fetch('http://localhost:5000/conversation/add_message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: chatId, message: assistantMsg }),
              });
            }
          }
        },
      });
    } catch (error) {
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: 'Lo siento, se produjo un error.',
          images: [],
          timestamp: new Date().toISOString(),
        },
      ]);
      setLoading(false);
    }
  };

  /* --------------------------------------------------------------------
   *  RENDER MARKDOWN + BLOQUES HTML EMBEBIDOS
   * ------------------------------------------------------------------*/
  function renderMessageContent(message) {
    let cleanContent = message.content
      .replace(/```html\s*/gi, '')
      .replace(/```/g, '');

    // Eliminar cualquier bloque <style>...</style>
    cleanContent = cleanContent.replace(/<style[\s\S]*?>[\s\S]*?<\/style>/gi, '');

    const markdownComponents = {
      a: ({ node, ...props }) => (
        <a {...props} className="underline text-orange-300 hover:text-orange-500 transition-colors duration-200" target="_blank" rel="noopener noreferrer" />
      ),
      li: ({ node, ...props }) => <li {...props} className="mb-2 pl-2 list-disc list-inside" />, 
      p: ({ node, ...props }) => <p {...props} className="mb-2" />, 
      strong: ({ node, ...props }) => <strong {...props} className="text-orange-400" />, 
      em: ({ node, ...props }) => <em {...props} className="italic text-orange-200" />, 
      ul: ({ node, ...props }) => <ul {...props} className="mb-2 pl-4" />, 
      ol: ({ node, ...props }) => <ol {...props} className="mb-2 pl-4 list-decimal list-inside" />, 
      code: ({ node, ...props }) => <code {...props} className="bg-gray-900 text-orange-300 px-1 rounded" />, 
    };

    const start = cleanContent.indexOf('<html_token>');
    const end = cleanContent.indexOf('</html_token>');

    if (start !== -1) {
      const before = cleanContent.slice(0, start);
      const html = end !== -1
        ? cleanContent.slice(start + 12, end)
        : cleanContent.slice(start + 12);
      const after = end !== -1 ? cleanContent.slice(end + 13) : '';

      return (
        <>
          {before && (
            <ReactMarkdown
              children={before}
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
              components={markdownComponents}
            />
          )}
          <div
            className="bg-gray-800 text-orange-100 border border-orange-400 rounded-lg p-4 mb-2"
            style={{ wordBreak: 'break-word' }}
          >
            <div className="html-token-block" dangerouslySetInnerHTML={{ __html: html }} />
          </div>
          {after && (
            <ReactMarkdown
              children={after}
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
              components={markdownComponents}
            />
          )}
        </>
      );
    } else {
      return (
        <ReactMarkdown
          children={cleanContent}
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
          components={markdownComponents}
        />
      );
    }
  }

  /* --------------------------------------------------------------------
   *  COMPONENTE LOGO PEQUEÑO
   * ------------------------------------------------------------------*/
  const BraveLogo = () => (
    <div className="flex items-center">
      <div className="relative">
        <img src="/src/assets/Brave-AI-logo.png" alt="Brave Logo" className="w-8 h-8" />
        <div className="absolute -top-1 -right-1 w-3 h-3 bg-orange-300 rounded-full animate-pulse" />
      </div>
    </div>
  );

  /* --------------------------------------------------------------------
   *  JSX PRINCIPAL
   * ------------------------------------------------------------------*/
  return (
    <>
      {/* Background blobs sutiles */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-orange-500/5 rounded-full animate-pulse" />
        <div
          className="absolute top-1/2 -left-20 w-40 h-40 bg-orange-400/10 rounded-full animate-bounce"
          style={{ animationDuration: '3s' }}
        />
        <div
          className="absolute bottom-20 right-1/4 w-20 h-20 bg-orange-300/5 rounded-full animate-ping"
          style={{ animationDuration: '4s' }}
        />
      </div>

      {/* MODALS ----------------------------------------------------------------*/}
      {showNewChatModal && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/60 backdrop-blur-sm z-50 animate-in fade-in duration-200">
          <div className="bg-gray-800/95 backdrop-blur-xl border border-gray-700/50 p-8 rounded-2xl shadow-2xl flex flex-col gap-6 min-w-[400px] max-w-md mx-4 animate-in zoom-in-95 duration-200">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-orange-500/20 rounded-lg">
                <MessageSquare className="w-5 h-5 text-orange-400" />
              </div>
              <h2 className="text-xl font-bold text-white">Nueva Conversación</h2>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">Nombre de la conversación</label>
                <input
                  className="w-full p-3 rounded-xl bg-gray-900/50 border border-gray-600/50 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-500/50 focus:border-orange-400 transition-all duration-200"
                  value={newChatName}
                  onChange={e => setNewChatName(e.target.value)}
                  autoFocus
                  placeholder="Ejemplo: Investigación sobre IA"
                />
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowNewChatModal(false)}
                className="px-6 py-2.5 bg-gray-700/50 hover:bg-gray-600/50 rounded-xl text-gray-300 font-medium transition-all duration-200 hover:scale-105"
              >
                Cancelar
              </button>
              <button
                onClick={createChat}
                className="px-6 py-2.5 bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 rounded-xl text-white font-medium transition-all duration-200 hover:scale-105 shadow-lg"
              >
                Crear
              </button>
            </div>
          </div>
        </div>
      )}

      {showRenameModal && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/60 backdrop-blur-sm z-50 animate-in fade-in duration-200">
          <div className="bg-gray-800/95 backdrop-blur-xl border border-gray-700/50 p-8 rounded-2xl shadow-2xl flex flex-col gap-6 min-w-[400px] max-w-md mx-4 animate-in zoom-in-95 duration-200">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-orange-500/20 rounded-lg">
                <Edit3 className="w-5 h-5 text-orange-400" />
              </div>
              <h2 className="text-xl font-bold text-white">Renombrar Conversación</h2>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">Nuevo nombre</label>
                <input
                  className="w-full p-3 rounded-xl bg-gray-900/50 border border-gray-600/50 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-500/50 focus:border-orange-400 transition-all duration-200"
                  value={renameChatName}
                  onChange={e => setRenameChatName(e.target.value)}
                  autoFocus
                />
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowRenameModal(false)}
                className="px-6 py-2.5 bg-gray-700/50 hover:bg-gray-600/50 rounded-xl text-gray-300 font-medium transition-all duration-200 hover:scale-105"
              >
                Cancelar
              </button>
              <button
                onClick={saveRenameChat}
                className="px-6 py-2.5 bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 rounded-xl text-white font-medium transition-all duration-200 hover:scale-105 shadow-lg"
              >
                Guardar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* LAYOUT PRINCIPAL ----------------------------------------------------------------*/}
      <div className="flex flex-col md:flex-row h-[calc(var(--vh)*100)] bg-gradient-to-br from-gray-900 via-gray-900 to-gray-800 text-white overflow-hidden">
        {/* ➡️ SIDEBAR DESKTOP */}
        <div className="hidden md:flex md:flex-col md:w-80 bg-gray-800/50 backdrop-blur-xl border-r border-gray-700/50 relative">
          <div className="absolute inset-0 bg-gradient-to-b from-gray-800/20 to-transparent pointer-events-none" />

          {/* Header logo + título */}
          <div className="relative p-6 border-b border-gray-700/30">
            <div className="flex items-center gap-3 mb-6">
              <BraveLogo />
              <div>
                <h1 className="text-2xl font-bold bg-gradient-to-r from-orange-400 to-orange-600 bg-clip-text text-transparent">
                  Brave Search
                </h1>
                <p className="text-xs text-gray-400">Búsqueda inteligente con IA</p>
              </div>
            </div>

            {/* Toggle planning */}
            <div className="flex items-center justify-between p-4 bg-gray-900/30 rounded-xl border border-gray-700/30">
              <div className="flex items-center gap-3">
                <div
                  className={`p-2 rounded-lg transition-colors duration-200 ${planningEnabled ? 'bg-orange-500/20' : 'bg-gray-700/50'}`}
                >
                  <Sparkles className={`w-4 h-4 ${planningEnabled ? 'text-orange-400' : 'text-gray-400'}`} />
                </div>
                <div>
                  <p className="text-sm font-medium text-white">Planning Mode</p>
                  <p className="text-xs text-gray-400">Análisis avanzado</p>
                </div>
              </div>
              <button
                className={`relative w-12 h-6 rounded-full transition-all duration-300 ${planningEnabled ? 'bg-orange-500' : 'bg-gray-600'}`}
                onClick={() => setPlanningEnabled(v => !v)}
              >
                <div
                  className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform duration-300 ${planningEnabled ? 'transform translate-x-6' : 'left-0.5'}`}
                />
              </button>
            </div>
          </div>

          {/* Conversaciones */}
          <div className="flex-1 overflow-auto p-4 relative">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-300">Conversaciones</h2>
              <span className="text-xs text-gray-500 bg-gray-700/30 px-2 py-1 rounded-full">
                {Object.keys(historico).length}
              </span>
            </div>
            <div className="space-y-2">
              {Object.entries(historico).map(([id, chat]) => (
                <div
                  key={id}
                  className={`group relative p-3 rounded-xl cursor-pointer transition-all duration-200 hover:bg-gray-700/30 ${
                    id === chatId ? 'bg-gradient-to-r from-orange-500/10 to-orange-400/5 border border-orange-500/20' : 'hover:scale-[1.02]'
                  }`}
                  onClick={() => setChatId(id)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <div className={`p-1.5 rounded-lg ${id === chatId ? 'bg-orange-500/20' : 'bg-gray-700/50'}`}>
                        <MessageSquare className={`w-3 h-3 ${id === chatId ? 'text-orange-400' : 'text-gray-400'}`} />
                      </div>
                      <span
                        className={`text-sm truncate ${id === chatId ? 'text-orange-100 font-medium' : 'text-gray-300'}`}
                      >
                        {chat.name || 'Sin nombre'}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                      <button
                        className="p-1.5 text-gray-400 hover:text-orange-400 hover:bg-orange-500/10 rounded-lg transition-all duration-200"
                        onClick={e => {
                          e.stopPropagation();
                          openRenameModal(id, chat.name);
                        }}
                        title="Renombrar"
                      >
                        <Edit3 size={12} />
                      </button>
                      <button
                        className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all duration-200"
                        onClick={e => {
                          e.stopPropagation();
                          deleteChat(id);
                        }}
                        title="Eliminar"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                  {id === chatId && (
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-orange-400 to-orange-600 rounded-r" />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Botón crear chat */}
          <div className="p-4 border-t border-gray-700/30">
            <button
              onClick={openNewChatModal}
              className="w-full p-3 bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 rounded-xl text-white font-medium transition-all duration-200 hover:scale-105 shadow-lg flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" />
              Nueva Conversación
            </button>
          </div>
        </div>

        {/* ➡️ SIDEBAR MÓVIL (overlay) */}
        {sidebarOpen && (
          <div className="fixed inset-0 z-50 flex md:hidden">
            <div className="w-72 bg-gray-800/95 backdrop-blur-xl border-r border-gray-700/50 p-4 overflow-y-auto">
              <div className="flex items-center gap-2 mb-6">
                <BraveLogo />
                <h1 className="text-xl font-bold bg-gradient-to-r from-orange-400 to-orange-600 bg-clip-text text-transparent">
                  Brave Search
                </h1>
              </div>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-gray-300">Conversaciones</h2>
                <button className="text-gray-400 hover:text-orange-400" onClick={() => setSidebarOpen(false)}>
                  <X size={16} />
                </button>
              </div>
              <div className="space-y-2">
                {Object.entries(historico).map(([id, chat]) => (
                  <div
                    key={id}
                    className={`p-3 rounded-xl cursor-pointer transition-all duration-200 hover:bg-gray-700/30 ${id === chatId ? 'bg-gray-700/50' : ''}`}
                    onClick={() => {
                      setChatId(id);
                      setSidebarOpen(false);
                    }}
                  >
                    {chat.name || 'Sin nombre'}
                  </div>
                ))}
              </div>

              <button
                onClick={() => {
                  openNewChatModal();
                  setSidebarOpen(false);
                }}
                className="mt-6 w-full p-3 bg-gradient-to-r from-orange-500 to-orange-600 rounded-xl text-white font-medium flex items-center justify-center gap-2 hover:scale-105 transition-all duration-200"
              >
                <Plus size={16} /> Nueva conversación
              </button>
            </div>
            {/* Clic fuera para cerrar */}
            <div className="flex-1" onClick={() => setSidebarOpen(false)} />
          </div>
        )}

        {/* ➡️ ÁREA PRINCIPAL DE MENSAJES */}
        <div className="flex-1 flex flex-col relative overflow-hidden">
          {/* Decorative background elements */}
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute top-0 left-1/4 w-96 h-96 bg-gradient-to-br from-orange-500/3 to-transparent rounded-full blur-3xl" />
            <div className="absolute bottom-0 right-1/4 w-80 h-80 bg-gradient-to-tl from-orange-400/4 to-transparent rounded-full blur-3xl" />
            <div className="absolute top-1/2 left-0 w-px h-32 bg-gradient-to-b from-transparent via-orange-500/20 to-transparent" />
            <div className="absolute top-1/3 right-0 w-px h-24 bg-gradient-to-b from-transparent via-orange-400/15 to-transparent" />
          </div>

          {/* Header móvil con glassmorphism */}
          <div className="md:hidden flex items-center p-4 bg-gray-900/80 backdrop-blur-xl border-b border-gray-700/30 flex-shrink-0 h-16 relative">
            <div className="absolute inset-0 bg-gradient-to-r from-gray-800/20 to-gray-700/10" />
            <Button 
              variant="outline" 
              size="icon" 
              className="relative bg-orange-500/10 hover:bg-orange-500/20 border-orange-400/30 backdrop-blur-sm mr-3 transition-all duration-300 hover:scale-105" 
              onClick={() => setSidebarOpen(true)}
            >
              <Menu className="w-4 h-4 text-orange-300" />
            </Button>
            <div className="relative flex items-center gap-3">
              <BraveLogo />
              <div className="flex flex-col">
                <h1 className="text-lg font-bold text-white truncate leading-tight">{chatName}</h1>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                  <span className="text-xs text-gray-400">En línea</span>
                </div>
              </div>
            </div>
          </div>

          {/* Mensajes con scroll suave y efectos mejorados */}
          <div 
            ref={messagesEndRef} 
            className="flex-1 p-4 space-y-6 min-h-0 bg-gradient-to-b from-gray-900/95 to-gray-900 flex flex-col overflow-y-auto scroll-smooth relative pb-48"
            style={{
              scrollbarWidth: 'thin',
              scrollbarColor: '#fb7185 transparent'
            }}
          >
            <style jsx>{`
              ::-webkit-scrollbar {
                width: 6px;
              }
              ::-webkit-scrollbar-track {
                background: transparent;
              }
              ::-webkit-scrollbar-thumb {
                background: linear-gradient(to bottom, #fb7185, #f97316);
                border-radius: 3px;
              }
              ::-webkit-scrollbar-thumb:hover {
                background: linear-gradient(to bottom, #f97316, #fb7185);
              }
            `}</style>

            {messages.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center min-h-[60vh] relative">
                {/* Animated background grid */}
                <div className="absolute inset-0 opacity-5">
                  <div className="absolute inset-0" style={{
                    backgroundImage: `radial-gradient(circle at 25px 25px, #fb7185 2px, transparent 0)`,
                    backgroundSize: '50px 50px',
                    animation: 'float 20s ease-in-out infinite'
                  }} />
                </div>
                
                {/* Logo with enhanced effects */}
                <div className="relative mb-8 group">
                  <div className="absolute inset-0 bg-gradient-conic from-orange-400 via-orange-500 to-orange-600 rounded-full blur-xl opacity-30 animate-spin-slow" />
                  <div className="relative bg-gray-900/80 backdrop-blur-xl p-6 rounded-3xl border border-gray-700/50 shadow-2xl group-hover:scale-105 transition-all duration-500">
                    <img
                      src="/src/assets/Brave-AI-logo.png"
                      alt="Brave AI Logo"
                      className="w-24 h-24 drop-shadow-2xl"
                      style={{ objectFit: 'contain' }}
                    />
                  </div>
                </div>

                {/* Welcome text with typing effect */}
                <div className="text-center mb-8 space-y-4">
                  <div className="text-4xl font-bold bg-gradient-to-r from-orange-400 via-orange-500 to-orange-600 bg-clip-text text-transparent animate-in slide-in-from-bottom-4 duration-1000">
                    Bienvenido a Brave Search
                  </div>
                  <div className="text-xl text-orange-100/80 animate-in slide-in-from-bottom-4 duration-1000 delay-300">
                    Tu asistente de búsqueda inteligente
                  </div>
                  <div className="flex items-center justify-center gap-2 text-sm text-gray-400 animate-in fade-in duration-1000 delay-500">
                    <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                    <span>Listo para ayudarte</span>
                  </div>
                </div>

                {/* Enhanced input with floating elements */}
                <div className="w-full max-w-2xl relative">
                  {/* Floating particles */}
                  <div className="absolute -top-4 -left-4 w-2 h-2 bg-orange-400/60 rounded-full animate-bounce" style={{ animationDelay: '0s', animationDuration: '3s' }} />
                  <div className="absolute -top-2 -right-6 w-1.5 h-1.5 bg-orange-500/60 rounded-full animate-bounce" style={{ animationDelay: '1s', animationDuration: '3s' }} />
                  <div className="absolute -bottom-3 left-8 w-1 h-1 bg-orange-300/60 rounded-full animate-bounce" style={{ animationDelay: '2s', animationDuration: '3s' }} />
                  
                  <div className="relative flex items-center rounded-3xl border border-gray-600/50 bg-gray-900/80 backdrop-blur-xl px-6 py-4 shadow-2xl focus-within:ring-2 focus-within:ring-orange-500/50 focus-within:border-orange-400/50 transition-all duration-300 hover:shadow-orange-500/10 group">
                    <div className="absolute inset-0 bg-gradient-to-r from-gray-800/20 to-gray-700/10 rounded-3xl" />
                    
                    <input
                      value={input}
                      onChange={e => setInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          handleSend();
                        }
                      }}
                      placeholder="¿Qué te gustaría saber hoy?"
                      className="flex-1 bg-transparent outline-none text-white placeholder-gray-400 text-lg py-3 relative z-10"
                    />
                    
                    <div className="flex items-center gap-3 relative z-10">
                      <button
                        className={`relative rounded-2xl border transition-all duration-300 flex items-center justify-center group/btn ${
                          planningEnabled 
                            ? 'bg-gradient-to-r from-orange-500 to-orange-600 border-orange-400 shadow-lg shadow-orange-500/25' 
                            : 'bg-gray-700/50 border-gray-500/50 hover:bg-orange-600/20 hover:border-orange-400/50'
                        }`}
                        onClick={() => setPlanningEnabled(v => !v)}
                        style={{ minWidth: 48, minHeight: 48 }}
                        title={planningEnabled ? 'Planning enabled' : 'Enable planning'}
                      >
                        <div className="absolute inset-0 rounded-2xl bg-gradient-to-r from-orange-400/20 to-orange-600/20 opacity-0 group-hover/btn:opacity-100 transition-opacity duration-300" />
                        <img
                          src="/src/assets/planner_logo.png"
                          alt="Planning"
                          className="relative z-10 transition-all duration-300 group-hover/btn:scale-110"
                          style={{
                            maxHeight: 28,
                            maxWidth: 28,
                            filter: planningEnabled ? 'brightness(0) invert(1)' : 'none',
                          }}
                        />
                        {planningEnabled && (
                          <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-400 rounded-full animate-pulse" />
                        )}
                      </button>
                      
                      <Button 
                        onClick={handleSend} 
                        className="bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white rounded-2xl p-3 shadow-lg shadow-orange-500/25 transition-all duration-300 hover:scale-110 hover:shadow-orange-500/40 group/send"
                        style={{ minWidth: 48, minHeight: 48 }}
                      >
                        <Send className="w-5 h-5 transition-transform duration-300 group-hover/send:translate-x-0.5" />
                      </Button>
                    </div>
                  </div>
                  
                  {/* Suggestion chips */}
                  <div className="flex flex-wrap gap-2 mt-6 justify-center animate-in fade-in duration-1000 delay-700">
                    {['Investiga sobre IA', 'Noticias actuales', 'Explícame conceptos', 'Encuentra recursos'].map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => setInput(suggestion)}
                        className="px-4 py-2 bg-gray-800/50 hover:bg-orange-500/20 border border-gray-600/30 hover:border-orange-400/50 rounded-full text-sm text-gray-300 hover:text-orange-200 transition-all duration-300 hover:scale-105 backdrop-blur-sm"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <>
                {messages.map((message, index) => {
                  if (loading && index === messages.length - 1 && message.role === 'assistant' && !message.content) {
                    return null;
                  }
                  return (
                    <div 
                      key={index} 
                      className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'} animate-in slide-in-from-bottom-2 duration-500`}
                      style={{ animationDelay: `${index * 100}ms` }}
                    >
                      <div className={`relative group ${message.role === 'user' ? 'max-w-xl' : 'max-w-4xl'}`}>
                        {/* Message bubble with enhanced styling */}
                        <div
                          className={`relative p-6 mb-2 rounded-2xl shadow-xl whitespace-pre-line break-words transition-all duration-300 hover:scale-[1.01] ${
                            message.role === 'user'
                              ? 'bg-gradient-to-br from-orange-500 via-orange-500 to-orange-600 text-white shadow-orange-500/20'
                              : 'bg-gray-800/80 backdrop-blur-xl text-orange-100 border border-gray-700/50 shadow-gray-900/50'
                          }`}
                        >
                          {/* Subtle glow effect */}
                          <div className={`absolute inset-0 rounded-2xl ${
                            message.role === 'user' 
                              ? 'bg-gradient-to-br from-orange-400/20 to-orange-600/20' 
                              : 'bg-gradient-to-br from-gray-700/10 to-gray-800/10'
                          } opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
                          
                          {/* Bot icon with animation */}
                          {message.role === 'assistant' && (
                            <div className="flex items-center gap-3 mb-4">
                              <div className="relative p-2 bg-orange-500/20 rounded-xl">
                                <Bot className="w-5 h-5 text-orange-400" />
                                <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-400 rounded-full animate-pulse" />
                              </div>
                              <div className="flex flex-col">
                                <span className="text-sm font-medium text-orange-300">Brave Assistant</span>
                                <span className="text-xs text-gray-400">Asistente de IA</span>
                              </div>
                            </div>
                          )}
                          
                          {/* Message content */}
                          <div className="relative z-10">
                            {message.role === 'assistant' ? (
                              <>
                                {renderMessageContent(message)}
                                {message.images && message.images.length > 0 && (
                                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-4">
                                    {message.images.map((img, idx) => (
                                      <div key={idx} className="relative group/img overflow-hidden rounded-xl border border-orange-300/30 shadow-lg hover:shadow-orange-500/20 transition-all duration-300">
                                        <img
                                          src={`http://localhost:5000/images/${img}`}
                                          alt="Imagen del chat"
                                          className="w-full h-32 object-cover transition-transform duration-300 group-hover/img:scale-105"
                                        />
                                        <div className="absolute inset-0 bg-gradient-to-t from-black/20 to-transparent opacity-0 group-hover/img:opacity-100 transition-opacity duration-300" />
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </>
                            ) : (
                              <>
                                {typeof message.content === 'string' ? <p className="text-lg leading-relaxed">{message.content}</p> : message.content}
                                {message.images && message.images.length > 0 && (
                                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-4">
                                    {message.images.map((img, idx) => (
                                      <div key={idx} className="relative group/img overflow-hidden rounded-xl border border-orange-300/30 shadow-lg">
                                        <img
                                          src={`http://localhost:5000/images/${img}`}
                                          alt="Imagen del chat"
                                          className="w-full h-32 object-cover transition-transform duration-300 group-hover/img:scale-105"
                                        />
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                          
                          {/* Timestamp */}
                          <div className={`text-xs mt-3 opacity-60 ${message.role === 'user' ? 'text-orange-100' : 'text-gray-400'}`}>
                            {new Date(message.timestamp).toLocaleTimeString()}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </>
            )}

            {/* Loading indicator with enhanced animation */}
            {loading && (
              <div className="flex justify-start animate-in slide-in-from-bottom-2 duration-300">
                <div className="relative group">
                  <div className="max-w-2xl p-6 mb-2 rounded-2xl shadow-xl bg-gray-800/80 backdrop-blur-xl text-orange-100 border border-gray-700/50 flex items-center space-x-4">
                    <div className="relative p-2 bg-orange-500/20 rounded-xl">
                      <Bot className="w-5 h-5 text-orange-400 animate-pulse" />
                      <div className="absolute -top-1 -right-1 w-3 h-3 bg-orange-400 rounded-full animate-ping" />
                    </div>
                    <div className="flex flex-col">
                      <span className="text-orange-300 font-medium">
                        {planningEnabled ? '🧠 Analizando y planificando...' : '🔍 Buscando información...'}
                      </span>
                      <div className="flex items-center gap-1 mt-1">
                        <div className="w-2 h-2 bg-orange-400 rounded-full animate-bounce" />
                        <div className="w-2 h-2 bg-orange-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                        <div className="w-2 h-2 bg-orange-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Input fijo en posición absoluta solo si hay mensajes */}
          {messages.length > 0 && (
            <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, zIndex: 30, display: 'flex', justifyContent: 'center', pointerEvents: 'none' }}>
              <div className="relative flex items-center rounded-3xl border border-gray-600/50 bg-gray-900/80 backdrop-blur-xl px-6 py-4 shadow-2xl focus-within:ring-2 focus-within:ring-orange-500/50 focus-within:border-orange-400/50 transition-all duration-300 hover:shadow-orange-500/10 group min-w-[300px] max-w-[1200px] w-full" style={{ pointerEvents: 'auto', margin: '1.5rem 0' }}>
                <div className="absolute inset-0 bg-gradient-to-r from-gray-800/20 to-gray-700/10 rounded-3xl"/>
                <input
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder={messages.length === 0 ? "¿Qué te gustaría saber hoy?" : "Continúa la conversación..."}
                  className="flex-1 bg-transparent outline-none text-white placeholder-gray-400 text-base py-3 relative z-10"
                />
                <div className="flex items-center gap-3 relative z-10">
                  <button
                    className={`relative rounded-2xl border transition-all duration-300 flex items-center justify-center group/btn ${
                      planningEnabled 
                        ? 'bg-gradient-to-r from-orange-500 to-orange-600 border-orange-400 shadow-lg shadow-orange-500/25' 
                        : 'bg-gray-700/50 border-gray-500/50 hover:bg-orange-600/20 hover:border-orange-400/50'
                    }`}
                    onClick={() => setPlanningEnabled(v => !v)}
                    style={{ minWidth: 44, minHeight: 44 }}
                    title={planningEnabled ? 'Planning enabled' : 'Enable planning'}
                  >
                    <img
                      src="/src/assets/planner_logo.png"
                      alt="Planning"
                      className="transition-all duration-300 group-hover/btn:scale-110"
                      style={{
                        maxHeight: 24,
                        maxWidth: 24,
                        filter: planningEnabled ? 'brightness(0) invert(1)' : 'none',
                      }}
                    />
                    {planningEnabled && (
                      <div className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-green-400 rounded-full animate-pulse" />
                    )}
                  </button>
                  <Button 
                    onClick={handleSend} 
                    className="bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white rounded-2xl p-2.5 shadow-lg shadow-orange-500/25 transition-all duration-300 hover:scale-110 hover:shadow-orange-500/40 group/send"
                    style={{ minWidth: 44, minHeight: 44 }}
                  >
                    <Send className="w-4 h-4 transition-transform duration-300 group-hover/send:translate-x-0.5" />
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
