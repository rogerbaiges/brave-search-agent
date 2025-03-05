// src/components/ui/slider.jsx
import React from 'react'
import * as RadixSlider from '@radix-ui/react-slider'

export const Slider = ({ value, onValueChange, max, step }) => {
  return (
    <RadixSlider.Root
      className="relative flex items-center select-none touch-none w-full h-5"
      value={value}
      max={max}
      step={step}
      onValueChange={onValueChange}
    >
      <RadixSlider.Track className="relative flex-1 h-1 bg-gray-700 rounded-full">
        <RadixSlider.Range className="absolute h-full bg-blue-600 rounded-full" />
      </RadixSlider.Track>
      <RadixSlider.Thumb className="block w-5 h-5 bg-white rounded-full shadow" />
    </RadixSlider.Root>
  )
}
