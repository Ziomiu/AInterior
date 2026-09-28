import React from "react";
import { toast } from 'react-hot-toast'

export const toaster = {
  create: ({ title, description, status = 'info', duration = 3000 }) => {
    toast.custom(
      (t) => (
        <div
          className={`flex items-start gap-2 rounded-md shadow-md p-3 max-w-sm border
          ${status === 'error' ? 'bg-[#f3e3df] text-[#7a3b2e] border-[#7a3b2e]/15' : ''}
          ${status === 'success' ? 'bg-accent/15 text-accent border-accent/20' : ''}
          ${status === 'warning' ? 'bg-[#f3ecd9] text-[#7a5f1e] border-[#7a5f1e]/15' : ''}
          ${status === 'info' ? 'bg-foreground/5 text-foreground border-foreground/10' : ''}`}
        >
          <div className="flex flex-col">
            {title && <span className="font-semibold text-sm">{title}</span>}
            {description && <span className="text-xs">{description}</span>}
          </div>
        </div>
      ),
      { duration }
    )
  },
}
