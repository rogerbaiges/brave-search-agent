// src/components/ui/button.jsx
import React from 'react'

export const Button = ({ className = '', children, ...props }) => {
  return (
    <button className={`px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors ${className}`} {...props}>
      {children}
    </button>
  )
}
