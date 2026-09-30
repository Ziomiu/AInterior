import React, { useState } from "react";

export default function WorkflowPanel({ workflows, currentWorkflowId, onSelect, onCreate, onRename, onDelete }) {
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editingName, setEditingName] = useState("");

  return (
    <div className="w-64 bg-white rounded-lg shadow-sm border border-foreground/10 p-4 flex flex-col gap-4">
      <h3 className="font-semibold text-lg">Workflows</h3>

      <div className="flex gap-2">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New workflow name"
          className="flex-1 border border-foreground/15 rounded px-2 py-1 text-sm bg-transparent focus:outline-none focus:ring-2 focus:ring-accent"
        />
        <button
          className="bg-primary text-primary-foreground hover:opacity-90 transition-opacity px-3 rounded text-sm cursor-pointer"
          onClick={() => {
            if (!newName.trim()) return;
            onCreate?.(newName.trim());
            setNewName("");
          }}
        >
          New
        </button>
      </div>

      <div className="overflow-auto flex-1">
        {workflows.length === 0 && <p className="text-sm text-muted">No workflows</p>}
        <ul className="space-y-2 mt-2">
          {workflows.map((wf) => (
            <li key={wf.id} className={`p-2 rounded border cursor-pointer ${wf.id === currentWorkflowId ? "border-accent bg-accent/10" : "border-foreground/10 bg-white"}`} onClick={(e) => (e.target.closest('button') ? null : onSelect?.(wf.id))}>
              <div className="flex items-center justify-between gap-2">
                {editingId === wf.id ? (
                  <input value={editingName} onChange={(e) => setEditingName(e.target.value)} className="flex-1 border border-foreground/15 px-2 py-1 text-sm rounded bg-transparent focus:outline-none focus:ring-2 focus:ring-accent" />
                ) : (
                  <button className="text-left flex-1 text-sm font-medium cursor-pointer" onClick={() => onSelect?.(wf.id)}>{wf.name}</button>
                )}

                <div className="flex items-center gap-1">
                  {editingId === wf.id ? (
                    <>
                      <button className="text-xs text-accent px-2 cursor-pointer" onClick={() => { onRename?.(wf.id, editingName); setEditingId(null); }}>OK</button>
                      <button className="text-xs text-muted px-2 cursor-pointer" onClick={() => setEditingId(null)}>✕</button>
                    </>
                  ) : (
                    <>
                      <button className="text-xs text-muted px-2 cursor-pointer" onClick={() => { setEditingId(wf.id); setEditingName(wf.name); }}>Edit</button>
                      <button className="text-xs text-[#7a3b2e] px-2 cursor-pointer" onClick={() => onDelete?.(wf.id)}>Del</button>
                    </>
                  )}
                </div>
              </div>

              <div className="mt-2">
                <span className="text-xs text-muted">id: {wf.id}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
