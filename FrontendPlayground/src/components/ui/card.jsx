// src/components/ui/card.jsx
import React from 'react'

export const Card = ({ className = '', children }) => {
  return <div className={`bg-gray-800 rounded-lg shadow-md ${className}`}>{children}</div>
}

export const CardHeader = ({ className = '', children }) => {
  return <div className={`p-4 border-b border-gray-700 ${className}`}>{children}</div>
}

export const CardTitle = ({ className = '', children }) => {
  return <h2 className={`text-lg font-semibold text-white ${className}`}>{children}</h2>
}

export const CardDescription = ({ className = '', children }) => {
  return <p className={`text-sm text-gray-400 ${className}`}>{children}</p>
}

export const CardContent = ({ className = '', children }) => {
  return <div className={`p-4 ${className}`}>{children}</div>
}

export const CardFooter = ({ className = '', children }) => {
  return <div className={`p-4 border-t border-gray-700 ${className}`}>{children}</div>
}
