// src/components/ui/scroll-area.jsx
import React from 'react'
import * as RadixScrollArea from '@radix-ui/react-scroll-area'

export const ScrollArea = ({ children, className = '' }) => {
  return (
    <RadixScrollArea.Root className={`overflow-hidden ${className}`}>
      <RadixScrollArea.Viewport className="w-full h-full">
        {children}
      </RadixScrollArea.Viewport>
      <RadixScrollArea.Scrollbar
        orientation="vertical"
        className="w-2 bg-gray-800 hover:bg-gray-700"
      >
        <RadixScrollArea.Thumb className="bg-blue-600 rounded-full" />
      </RadixScrollArea.Scrollbar>
    </RadixScrollArea.Root>
  )
}
