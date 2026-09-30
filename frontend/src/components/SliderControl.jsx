import React from "react";
import { LuInfo } from "react-icons/lu";

const SliderControl = ({ label, value, min, max, step, onChange, textColor = "text-muted", description = "" }) => (
  <div className="w-full">
    <div className="flex items-center gap-2">
      <label className={`block text-sm font-medium ${textColor}`}>
        {label}: {value}
      </label>
      {description != "" && (
        <div className="relative group">
          <LuInfo className="text-muted cursor-help" size={16} />
          <div className="absolute left-0 bottom-full mb-2 hidden group-hover:block w-64 p-2 bg-foreground text-background text-xs rounded shadow-lg z-10">
            {description}
          </div>
        </div>
      )}
    </div>

    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange([Number(e.target.value)])}
      className="w-full h-2 bg-foreground/10 rounded-lg appearance-none cursor-pointer accent-accent"
    />
  </div>
);

export default SliderControl;
