import { useState, useEffect, useRef } from 'react'
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Bot, Send, Paperclip, Plus, Menu } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { Switch } from "@/components/ui/switch"

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

  useEffect(() => {
    // Elimina todas las imágenes del backend al cargar la app
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
    const setVh = () => {
      const vh = window.innerHeight * 0.01
      document.documentElement.style.setProperty('--vh', `${vh}px`)
    }
    setVh()
    window.addEventListener('resize', setVh)
    return () => window.removeEventListener('resize', setVh)
  }, [])

  // Optionally, you can keep the new_connection logic if you use threads
  // useEffect(() => { new_connection() }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollTop = messagesEndRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const handleSend = async () => {
    if (input.trim()) {
      setMessages(prev => [...prev, { role: 'user', content: input }])
      const userMessage = input
      setInput('')
      // Add a placeholder for the assistant's streaming response
      setMessages(prev => [...prev, { role: 'assistant', content: '' }])
      const assistantIndex = messages.length + 1
      // Construir el chatHistory para el backend (todos los mensajes previos menos el placeholder)
      const chatHistory = messages.map(m => ({ role: m.role, content: m.content }))
      setLoading(true)
      try {
        await callBackendStream({
          endpoint: planningEnabled ? 'plan' : 'search',
          body: { query: userMessage, chat_history: chatHistory },
          onToken: (token, done) => {
            setMessages(prev => {
              const updated = [...prev]
              const prevContent = updated[assistantIndex]?.content || ''
              updated[assistantIndex] = {
                role: 'assistant',
                content: prevContent + (token.replace(prevContent, ''))
              }
              return updated
            })
            if (done) setLoading(false)
          }
        })
      } catch (error) {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, there was an error.' }])
        setLoading(false)
      }
    }
  }
  
  return (
    // Usamos la variable --vh para calcular la altura real del viewport
    <div className="flex flex-col md:flex-row h-[100dvh] bg-gray-900 text-white overflow-y-auto">

      {/* Sidebar para escritorio */}
      <div className="hidden md:flex md:flex-col md:w-64 bg-gray-800 p-4 border-r border-gray-600">
        <div className="flex items-center mb-4">
          <img 
            className="w-8 h-8 mr-2" 
            src="https://www.svgrepo.com/show/353506/brave.svg" 
            alt="Brave Logo" 
          />
          <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-orange-500">
            Brave Search
          </h1>
        </div>
        {/* Chip de Planning */}
        <div className="flex items-center mb-4">
          <button
            className={`px-3 py-1 rounded-full text-xs font-semibold border transition-colors duration-200 mr-2 ${planningEnabled ? 'bg-orange-500 text-white border-orange-400' : 'bg-gray-700 text-orange-300 border-gray-500 hover:bg-orange-600 hover:text-white'}`}
            onClick={() => setPlanningEnabled(v => !v)}
          >
            {planningEnabled ? 'Planning enabled' : 'Enable planning'}
          </button>
        </div>
        <div className="flex-1 overflow-auto">
          <h2 className="text-sm font-semibold text-gray-400 mb-3">Recent Conversations</h2>
          <ul className="space-y-1">
            <li className="p-2 rounded bg-gray-700 cursor-pointer hover:bg-gray-600">
              <span className="text-sm">Current Chat</span>
            </li>
            <li className="p-2 rounded cursor-pointer hover:bg-gray-700">
              <span className="text-sm">Machine Learning Projects</span>
            </li>
            <li className="p-2 rounded cursor-pointer hover:bg-gray-700">
              <span className="text-sm">React Component Design</span>
            </li>
            <li className="p-2 rounded cursor-pointer hover:bg-gray-700">
              <span className="text-sm">Travel Planning for Europe</span>
            </li>
            <li className="p-2 rounded cursor-pointer hover:bg-gray-700">
              <span className="text-sm">Book Recommendations</span>
            </li>
          </ul>
        </div>
        <Button 
          variant="outline" 
          className="mt-4 w-full bg-orange-600 text-gray-300 border-gray-600 hover:bg-gray-700 flex items-center justify-center"
          onClick={() => {
            setMessages([]);
            setInput("");
          }}
        >
          <Plus className="w-4 h-4 mr-2" />
          New Chat
        </Button>
      </div>

      {/* Sidebar para móvil (overlay) */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="w-64 bg-gray-800 p-4 border-r border-gray-600">
            <div className="flex items-center mb-4">
              <img 
                className="w-8 h-8 mr-2" 
                src="https://www.svgrepo.com/show/353506/brave.svg" 
                alt="Brave Logo" 
              />
              <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-orange-500">
                Brave Playground
              </h1>
            </div>
            <div className="flex-1 overflow-auto">
              <h2 className="text-sm font-semibold text-gray-400 mb-3">Recent Conversations</h2>
              <ul className="space-y-1">
                <li className="p-2 rounded bg-gray-700 cursor-pointer hover:bg-gray-600">
                  <span className="text-sm">Current Chat</span>
                </li>
                <li className="p-2 rounded cursor-pointer hover:bg-gray-700">
                  <span className="text-sm">Machine Learning Projects</span>
                </li>
                <li className="p-2 rounded cursor-pointer hover:bg-gray-700">
                  <span className="text-sm">React Component Design</span>
                </li>
                <li className="p-2 rounded cursor-pointer hover:bg-gray-700">
                  <span className="text-sm">Travel Planning for Europe</span>
                </li>
                <li className="p-2 rounded cursor-pointer hover:bg-gray-700">
                  <span className="text-sm">Book Recommendations</span>
                </li>
              </ul>
            </div>
            <Button 
              variant="outline" 
              className="mt-4 w-full bg-orange-600 text-gray-300 border-gray-600 hover:bg-gray-700 flex items-center justify-center"
              onClick={() => {
                setMessages([]);
                setInput("");
              }}
            >
              <Plus className="w-4 h-4 mr-2" />
              New Chat
            </Button>
          </div>
          {/* Área para cerrar la barra al tocar fuera */}
          <div 
            className="flex-1" 
            onClick={() => setSidebarOpen(false)}
          />
        </div>
      )}

      {/* Área principal del chat */}
      <div className="flex-1 flex flex-col">
        {/* Header móvil: menú, logo y título, con altura fija */}
        <div className="md:hidden flex items-center p-4 bg-gray-800 border-b border-gray-600 flex-shrink-0 h-16">
          <Button 
            variant="outline" 
            size="icon" 
            className="bg-orange-500 hover:bg-gray-700 mr-2"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="w-4 h-4" />
          </Button>
          <img 
            className="w-6 h-6 mr-2" 
            src="https://www.svgrepo.com/show/353506/brave.svg" 
            alt="Brave Logo" 
          />
          <h1 className="text-xl font-bold">Current Chat</h1>
        </div>
        {/* Contenedor de mensajes: ocupa el espacio restante entre header y footer */}
        <div
          ref={messagesEndRef}
          className="flex-1 p-4 space-y-4 min-h-0 bg-gray-900 flex flex-col overflow-y-auto"
        >
          {messages.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center min-h-[60vh]">
              <img
                src={"/src/assets/Brave-AI-logo.png"}
                alt="Brave AI Logo"
                className="w-32 h-32 mb-8 drop-shadow-lg"
                style={{ objectFit: 'contain' }}
              />
              <div className="text-3xl font-bold text-orange-400 mb-2 text-center">Welcome to Brave Search</div>
              <div className="text-lg text-orange-100 mb-8 text-center">What do you want to search?</div>
              <div className="w-full max-w-xl flex items-center rounded-2xl border border-gray-600 bg-gray-900 px-4 py-2 shadow focus-within:ring-2 focus-within:ring-orange-500">
                <input
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder="Pregunta lo que quieras"
                  className="flex-1 bg-transparent outline-none text-white placeholder-gray-400 text-base py-2"
                  style={{ minWidth: 0 }}
                />
                <button
                  className={`ml-2 rounded-full border transition-colors duration-200 flex items-center justify-center ${planningEnabled ? 'bg-orange-500 border-orange-400' : 'bg-gray-700 border-gray-500 hover:bg-orange-600'}`}
                  onClick={() => setPlanningEnabled(v => !v)}
                  style={{ minWidth: 44, minHeight: 44, height: 44, width: 44, padding: 0 }}
                  title={planningEnabled ? 'Planning enabled' : 'Enable planning'}
                >
                  <img 
                    src={"/src/assets/planner_logo.png"} 
                    alt="Planning" 
                    style={{ 
                      maxHeight: 32, 
                      maxWidth: 32, 
                      width: 'auto', 
                      height: 'auto', 
                      display: 'block', 
                      margin: 'auto', 
                      filter: planningEnabled ? 'brightness(0) invert(1)' : 'none' 
                    }} 
                  />
                </button>
                <Button onClick={handleSend} className="ml-2 bg-orange-500 hover:bg-gray-700 text-sm rounded-full p-2">
                  <Send className="w-5 h-5" />
                </Button>
              </div>
            </div>
          ) : (
            <>
              {messages.map((message, index) => {
                // Oculta el bloque de respuesta vacío si loading está activo y es el último mensaje (asistente)
                if (
                  loading &&
                  index === messages.length - 1 &&
                  message.role === 'assistant' &&
                  !message.content
                ) {
                  return null;
                }
                // Buscar imágenes generadas para este mensaje (solo para respuestas del asistente)
                let imageElements = null;
                if (message.role === 'assistant' && message.content) {
                  // Solo mostrar imágenes si ya se han eliminado las antiguas
                  imageElements = imagesCleared ? (
                    <ImagesForMessage />
                  ) : null;
                }
                return (
                  <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-2xl p-6 mb-2 rounded-lg shadow-lg whitespace-pre-line break-words ${message.role === 'user' ? 'bg-gradient-to-br from-orange-500 to-orange-400 text-white' : 'bg-gray-800 text-orange-100 border border-orange-400'}`}
                      style={{ margin: '0.5rem' }}
                    >
                      {message.role === 'assistant' && (
                        <Bot className="w-6 h-6 mb-2 text-orange-400" />
                      )}
                      {message.role === 'assistant' ? (
                        <>
                          <ReactMarkdown 
                            children={message.content}
                            remarkPlugins={[remarkGfm]}
                            rehypePlugins={[rehypeRaw]}
                            components={{
                              a: ({node, ...props}) => <a {...props} className="underline text-orange-300 hover:text-orange-500 transition-colors duration-200" target="_blank" rel="noopener noreferrer"/>,
                              li: ({node, ...props}) => <li {...props} className="mb-2 pl-2 list-disc list-inside"/>,
                              p: ({node, ...props}) => <p {...props} className="mb-2"/>,
                              strong: ({node, ...props}) => <strong {...props} className="text-orange-400"/>,
                              em: ({node, ...props}) => <em {...props} className="italic text-orange-200"/>,
                              ul: ({node, ...props}) => <ul {...props} className="mb-2 pl-4"/>,
                              ol: ({node, ...props}) => <ol {...props} className="mb-2 pl-4 list-decimal list-inside"/>,
                              code: ({node, ...props}) => <code {...props} className="bg-gray-900 text-orange-300 px-1 rounded"/>,
                            }}
                          />
                          {imageElements}
                        </>
                      ) : (
                        typeof message.content === 'string' ? <p>{message.content}</p> : message.content
                      )}
                    </div>
                  </div>
                );
              })}
            </>
          )}
          {loading && (
            <div className="flex justify-start">
              <div className="max-w-2xl p-6 mb-2 rounded-lg shadow-lg bg-gray-800 text-orange-100 border border-orange-400 flex items-center space-x-2 animate-pulse">
                <Bot className="w-6 h-6 mb-2 text-orange-400" />
                <span className="italic text-orange-300">
                  {planningEnabled ? 'Thinking...' : 'Searching...'}
                </span>
              </div>
            </div>
          )}
          {/* Eliminado el ref={messagesEndRef} */}
        </div>
        {/* Footer con diseño moderno tipo Bing/ChatGPT */}
        <div className={`p-4 bg-gray-800 border-gray-600 flex-shrink-0 flex flex-col items-center transition-all duration-500 ${messages.length === 0 ? 'opacity-0 pointer-events-none translate-y-8' : 'opacity-100 pointer-events-auto translate-y-0'}`}>
          <div className="w-full max-w-2xl flex flex-col items-center">
            <div className="w-full flex flex-col items-center">
              <div className="w-full flex items-center rounded-2xl border border-gray-600 bg-gray-900 px-4 py-2 shadow focus-within:ring-2 focus-within:ring-orange-500">
                <input
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder="Pregunta lo que quieras"
                  className="flex-1 bg-transparent outline-none text-white placeholder-gray-400 text-base py-2"
                  style={{ minWidth: 0 }}
                />
                <button
                  className={`ml-2 rounded-full border transition-colors duration-200 flex items-center justify-center ${planningEnabled ? 'bg-orange-500 border-orange-400' : 'bg-gray-700 border-gray-500 hover:bg-orange-600'}`}
                  onClick={() => setPlanningEnabled(v => !v)}
                  style={{ minWidth: 44, minHeight: 44, height: 44, width: 44, padding: 0 }}
                  title={planningEnabled ? 'Planning enabled' : 'Enable planning'}
                >
                  <img 
                    src={"/src/assets/planner_logo.png"} 
                    alt="Planning" 
                    style={{ 
                      maxHeight: 32, 
                      maxWidth: 32, 
                      width: 'auto', 
                      height: 'auto', 
                      display: 'block', 
                      margin: 'auto', 
                      filter: planningEnabled ? 'brightness(0) invert(1)' : 'none' 
                    }} 
                  />
                </button>
                <Button onClick={handleSend} className="ml-2 bg-orange-500 hover:bg-gray-700 text-sm rounded-full p-2">
                  <Send className="w-5 h-5" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// Componente auxiliar para mostrar imágenes de la carpeta 'images'
function ImagesForMessage() {
  const [images, setImages] = useState([]);
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    // Intenta obtener la lista de imágenes del backend (asumiendo que /images está servido como estático)
    fetch('http://localhost:5000/images_list')
      .then(res => res.json())
      .then(data => setImages(data.images || []));
  }, []);
  if (!images.length) return null;
  const prev = () => setCurrent((c) => (c === 0 ? images.length - 1 : c - 1));
  const next = () => setCurrent((c) => (c === images.length - 1 ? 0 : c + 1));
  return (
    <div className="flex flex-col items-center mt-2">
      <div className="relative">
        <img
          src={`http://localhost:5000/images/${images[current]}`}
          alt="Generated"
          className="w-80 h-64 object-cover rounded border border-orange-300 shadow"
          style={{ background: '#222' }}
        />
        {images.length > 1 && (
          <>
            <button
              onClick={prev}
              className="absolute left-0 top-1/2 -translate-y-1/2 bg-gray-900 bg-opacity-60 hover:bg-opacity-90 text-orange-200 px-2 py-1 rounded-l focus:outline-none"
              style={{ zIndex: 2 }}
            >
              &#8592;
            </button>
            <button
              onClick={next}
              className="absolute right-0 top-1/2 -translate-y-1/2 bg-gray-900 bg-opacity-60 hover:bg-opacity-90 text-orange-200 px-2 py-1 rounded-r focus:outline-none"
              style={{ zIndex: 2 }}
            >
              &#8594;
            </button>
          </>
        )}
      </div>
      {images.length > 1 && (
        <div className="flex gap-1 mt-2">
          {images.map((_, i) => (
            <span
              key={i}
              className={`w-2 h-2 rounded-full ${i === current ? 'bg-orange-400' : 'bg-gray-500'}`}
              style={{ display: 'inline-block' }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
