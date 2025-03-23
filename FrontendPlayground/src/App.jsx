import { useState, useEffect, useRef } from 'react'
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Bot, Send, Paperclip, Plus, Menu } from 'lucide-react'

export default function BravePlayground() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Welcome to the Brave Playground. How can I assist you today?' }
  ])
  const [input, setInput] = useState('')
  const [threadId, setThreadId] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  
  // Ref para el contenedor de mensajes (auto-scroll)
  const messagesEndRef = useRef(null)

  // Establecer la variable CSS --vh
  useEffect(() => {
    const setVh = () => {
      const vh = window.innerHeight * 0.01
      document.documentElement.style.setProperty('--vh', `${vh}px`)
    }
    setVh()
    window.addEventListener('resize', setVh)
    return () => window.removeEventListener('resize', setVh)
  }, [])

  const new_connection = async () => {
    try {
      const response = await fetch('http://192.168.86.47:5000/new-conversation', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      })
      const data = await response.json()
      setThreadId(data.thread_id)
      console.log("New thread ID:", data.thread_id)
    } catch (error) {
      console.error('Failed to start a new conversation:', error)
    }
  }

  useEffect(() => {
    new_connection()
  }, [])

  // Auto-scroll al final cuando se actualicen los mensajes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    if (input.trim()) {
      setMessages(prev => [...prev, { role: 'user', content: input }])
      const userMessage = input
      setInput('')
  
      console.log("Using thread ID:", threadId)
  
      try {
        // Código real de fetch comentado:
        // const response = await fetch('http://192.168.86.47:5000/generate', {
        //   method: 'POST',
        //   headers: { 'Content-Type': 'application/json' },
        //   body: JSON.stringify({ prompt: userMessage, thread_id: threadId }),
        // })
        // const data = await response.json()
        // setMessages(prev => [...prev, { role: 'assistant', content: data.response }])
        
        // Simulación de respuesta hardcodeada
        // Simulación de respuesta hardcodeada
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: (
            <div className="space-y-4">
              <p>
                Si et trobes a la Facultat d'Informàtica de Barcelona (FIB) i vols menjar fora, aquí tens algunes opcions properes:
              </p>
              {/* Nou restaurant inventat */}
              <div>
                <strong>Sushi Brave Search</strong>
                <p className="mt-1">
                  Situat a només 5 minuts i amb capacitat per a 2 persones.
                </p>
                <img
                  src="https://www.sushifresh.es/blog/wp-content/uploads/2019/06/48179744_23843159724700120_175341253880184832_n-860x860.jpg"
                  alt="Sushi Brave Search"
                  className="mt-1 rounded"
                />
                <a 
                  href="https://loyapp.es/comercio/programa-de-fidelizacion-de-bar-de-la-fib/?utm_source=chatgpt.com" 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  className="text-orange-400 underline"
                >
                  Veure més
                </a>
              </div>
              
              <div>
                <strong>Bar de la FIB</strong>
                <p className="mt-1">
                  Situat a l'Edifici B6 del Campus Nord de la UPC, aquest bar universitari ofereix una varietat de plats com hamburgueses, croquetes i butifarras a preus assequibles.
                </p>
                <a 
                  href="https://loyapp.es/comercio/programa-de-fidelizacion-de-bar-de-la-fib/?utm_source=chatgpt.com" 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  className="text-orange-400 underline"
                >
                  Veure més
                </a>
              </div>
              <div>
                <strong>Restaurant Tritón</strong>
                <p className="mt-1">
                  Situat al carrer Alfambra 16, a uns 167 metres de la FIB, aquest restaurant combina cuina europea i sushi, oferint una àmplia varietat de plats en un ambient acollidor.
                </p>
              </div>
              <div>
                <strong>Frankfurt Pedralbes II</strong>
                <p className="mt-1">
                  Aquest establiment és conegut pels seus frankfurts i altres plats ràpids, sent una opció popular entre estudiants i locals.
                </p>
                <a 
                  href="https://www.frankfurtpedralbes.com/" 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  className="text-orange-400 underline"
                >
                  Veure més
                </a>
              </div>
              <div>
                <strong>Cafeteria Camins</strong>
                <p className="mt-1">
                  Localitzada a l'Edifici B2 del Campus Nord, aquesta cafeteria ofereix serveis de bar i autoservei, sent una alternativa convenient dins del campus.
                </p>
                <a 
                  href="https://www.cafeteriacamins.com/" 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  className="text-orange-400 underline"
                >
                  Veure més
                </a>
              </div>
            </div>

          )
        }])

      } catch (error) {
        console.error('Error:', error)
        setMessages(prev => [...prev, { role: 'assistant', content: 'Lo siento, hubo un error procesando tu solicitud.' }])
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
          {messages.map((message, index) => (
            <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-sm p-4 rounded-lg ${message.role === 'user' ? 'bg-orange-500' : 'bg-gray-700'}`}>
                {message.role === 'assistant' && (
                  <Bot className="w-6 h-6 mb-2 text-orange-400" />
                )}
                {typeof message.content === 'string' ? <p>{message.content}</p> : message.content}
              </div>
            </div>
          ))}
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
