import { useState, useEffect } from 'react'
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Bot, Send, Paperclip, Zap, Plus } from 'lucide-react'

export default function BravePlayground() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Welcome to the Brave Playground. How can I assist you today?' }
  ])
  const [input, setInput] = useState('')
  const [threadId, setThreadId] = useState(null)

  const new_connection = async () => {
    try {
      const response = await fetch('http://192.168.86.47:5000/new-conversation', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
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

  const handleSend = async () => {
    if (input.trim()) {
      setMessages([...messages, { role: 'user', content: input }])
      const userMessage = input
      setInput('')

      console.log("Using thread ID:", threadId)

      try {
        const response = await fetch('http://192.168.86.47:5000/generate', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ prompt: userMessage, thread_id: threadId }),
        })

        const data = await response.json()

        setMessages(prev => [...prev, { role: 'assistant', content: data.response }])
      } catch (error) {
        console.error('Error:', error)
        setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, there was an error processing your request.' }])
      }
    }
  }

  return (
    <div className="flex h-screen bg-gray-900 text-white">
        <div className="w-64 bg-gray-800 p-4 flex flex-col border-r border-gray-600">
          <div className="flex items-center mb-6">
            <img 
              className="w-8 h-8 mr-2" 
              src="https://www.svgrepo.com/show/353506/brave.svg" 
              alt="Brave Logo" 
            />
            <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-orange-500">Brave Playground</h1>
          </div>

          {/* Conversations List */}
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

          <Button variant="outline" className="mt-4 w-full bg-orange-600 text-gray-300 border-gray-600 hover:bg-gray-700 flex items-center justify-center">
            <Plus className="w-4 h-4 mr-2" />
            New Chat
          </Button>
        </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Chat Messages */}
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {messages.map((message, index) => (
            <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-sm p-4 rounded-lg ${message.role === 'user' ? 'bg-orange-500' : 'bg-gray-700'}`}>
                {message.role === 'assistant' && (
                  <Bot className="w-6 h-6 mb-2 text-orange-400" />
                )}
                <p>{message.content}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Input Area */}
        <div className="p-4 bg-gray-800 border-t border-gray-600">
          <div className="flex space-x-2">
            <Button variant="outline" size="icon" className="bg-orange-500 hover:bg-gray-700">
              <Paperclip className="w-4 h-4" />
            </Button>
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type your message here..."
              className="flex-1 bg-gray-700 border-gray-600 focus:ring-orange-500"
            />
            <Button onClick={handleSend} className="bg-orange-500 hover:bg-gray-700">
              <Send className="w-4 h-4 mr-2" />
              Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
