// src/components/ui/input.jsx
import React from 'react'

export const Input = ({ className = '', ...props }) => {
  return (
    <input
      className={`px-4 py-2 bg-gray-800 text-white border border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 ${className}`}
      {...props}
    />
  )
}
