// src/components/ui/tabs.jsx
import React from 'react'
import * as RadixTabs from '@radix-ui/react-tabs'

export const Tabs = ({ children, value, className = '' }) => {
  return (
    <RadixTabs.Root className={`flex flex-col ${className}`} value={value}>
      {children}
    </RadixTabs.Root>
  )
}

export const TabsList = ({ children, className = '' }) => {
  return (
    <RadixTabs.List className={`flex space-x-2 border-b border-gray-700 mb-4 ${className}`}>
      {children}
    </RadixTabs.List>
  )
}

export const TabsTrigger = ({ value, children, className = '' }) => {
  return (
    <RadixTabs.Trigger
      className={`px-4 py-2 text-gray-400 hover:text-white transition-colors ${className}`}
      value={value}
    >
      {children}
    </RadixTabs.Trigger>
  )
}

export const TabsContent = ({ value, children, className = '' }) => {
  return (
    <RadixTabs.Content className={`flex-1 ${className}`} value={value}>
      {children}
    </RadixTabs.Content>
  )
}
