import { useState, useEffect, useRef } from 'react'
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Bot, Send, Paperclip, Plus, Menu } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'

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
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Welcome to the Brave Playground. How can I assist you today?' }
  ])
  const [input, setInput] = useState('')
  const [threadId, setThreadId] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)

  useEffect(() => {
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
          endpoint: 'search',
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
    <div style={{ height: "calc(var(--vh, 1vh) * 100)" }} className="flex flex-col md:flex-row bg-gray-900 text-white">
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
        <div className="flex-1 overflow-auto p-4 space-y-4 min-h-0 bg-gray-900">
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
              // Busca imágenes en la carpeta 'images' modificadas recientemente (opcional: puedes mejorar el criterio)
              // Aquí asumimos que el backend sirve las imágenes estáticamente desde /images
              // y que el nombre de la imagen contiene la fecha/hora o un identificador único
              // Para demo, simplemente mostramos todas las imágenes de la carpeta
              // En producción, deberías asociar imágenes a mensajes por algún identificador
              imageElements = (
                <ImagesForMessage />
              );
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
          {loading && (
            <div className="flex justify-start">
              <div className="max-w-2xl p-6 mb-2 rounded-lg shadow-lg bg-gray-800 text-orange-100 border border-orange-400 flex items-center space-x-2 animate-pulse">
                <Bot className="w-6 h-6 mb-2 text-orange-400" />
                <span className="italic text-orange-300">Thinking...</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        {/* Footer con altura fija */}
          {/* Footer con altura fija y componentes reducidos */}
          <div className="p-2 bg-gray-800 border-t border-gray-600 flex-shrink-0 h-20">
            <div className="flex items-center space-x-2">
              <Button variant="outline" size="icon" className="bg-orange-500 hover:bg-gray-700">
                <Paperclip className="w-4 h-10" />
              </Button>
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Type your message here..."
                className="flex-1 bg-gray-700 border-gray-600 focus:ring-orange-500 text-sm p-2"
              />
              <Button onClick={handleSend} className="bg-orange-500 hover:bg-gray-700 text-sm">
                <Send className="w-4 h-5 mr-1" />
                Send
              </Button>
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
