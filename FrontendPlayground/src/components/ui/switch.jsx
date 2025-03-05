// src/components/ui/switch.jsx
import React from 'react'
import * as RadixSwitch from '@radix-ui/react-switch'

export const Switch = ({ checked, onCheckedChange, id }) => {
  return (
    <RadixSwitch.Root
      className="w-10 h-6 bg-gray-700 rounded-full relative flex items-center transition-colors"
      checked={checked}
      onCheckedChange={onCheckedChange}
      id={id}
    >
      <RadixSwitch.Thumb className="block w-4 h-4 bg-white rounded-full transition-transform transform-gpu will-change-transform" />
    </RadixSwitch.Root>
  )
}
