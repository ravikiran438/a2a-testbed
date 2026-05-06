import { Handle, Position, type NodeProps } from '@xyflow/react';

type AgentState = 'idle' | 'sending' | 'receiving' | 'done';

interface AgentNodeData {
  label: string;
  role: string;
  state: AgentState;
  cardId: string;
  /** True when this agent has an AgentCard loaded; false when only a
   *  path-string hint exists (custom scenario, card not yet uploaded). */
  hasCard: boolean;
  /** Path-string hint shown in the "?" tooltip when hasCard is false. */
  cardHint?: string;
  /** Click handler for the "?" badge. App.tsx wires this so the user
   *  can pick the AgentCard JSON for this specific agent. */
  onLoadCard?: (cardId: string) => void;
  [key: string]: unknown;
}

const stateClass: Record<AgentState, string> = {
  idle: 'agent-idle',
  sending: 'agent-sending',
  receiving: 'agent-receiving',
  done: 'agent-done',
};

const roleEmoji: Record<string, string> = {
  principal: 'P',
  guardian: 'G',
  service_provider: 'S',
  integrity: 'I',
  observer: 'O',
};

export function AgentNode({ data }: NodeProps) {
  const d = data as AgentNodeData;
  return (
    <div className={`agent-node ${stateClass[d.state]}`}>
      {/* Visible left/right handles — used by ordinary message edges. */}
      <Handle
        type="target"
        position={Position.Left}
        id="left"
        style={{ background: '#94a3b8', width: 8, height: 8 }}
      />
      {/* Invisible top/bottom handles — used by passive observer
          tap edges. Hidden so they don't add visual noise on the
          node; xyflow still routes through them. */}
      <Handle
        type="source"
        position={Position.Top}
        id="top-out"
        style={{ background: 'transparent', border: 'none', width: 1, height: 1, top: 0 }}
      />
      <Handle
        type="target"
        position={Position.Top}
        id="top-in"
        style={{ background: 'transparent', border: 'none', width: 1, height: 1, top: 0 }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="bottom-out"
        style={{ background: 'transparent', border: 'none', width: 1, height: 1, bottom: 0 }}
      />
      <Handle
        type="target"
        position={Position.Bottom}
        id="bottom-in"
        style={{ background: 'transparent', border: 'none', width: 1, height: 1, bottom: 0 }}
      />
      <div className="agent-badge">{roleEmoji[d.role] || '?'}</div>
      <div className="agent-body">
        <div className="agent-label">{d.label}</div>
        <div className="agent-role">{d.role.replace('_', ' ')}</div>
        {d.cardHint && (
          <button
            type="button"
            className={`agent-card-pill ${d.hasCard ? 'loaded' : 'pending'}`}
            title={
              d.hasCard
                ? `AgentCard loaded. Click to replace with a different JSON.`
                : `Click to upload this agent's card JSON (expected: ${d.cardHint
                    .split(/[\\/]/)
                    .pop()}).`
            }
            onClick={(e) => {
              e.stopPropagation();
              d.onLoadCard?.(d.cardId);
            }}
          >
            <span className="agent-card-pill-icon">
              {d.hasCard ? '✓' : '↑'}
            </span>
            <span className="agent-card-pill-name">
              {d.cardHint.split(/[\\/]/).pop()}
            </span>
          </button>
        )}
      </div>
      {!d.hasCard && (
        <button
          type="button"
          className="agent-missing-card"
          title={
            d.cardHint
              ? `No AgentCard loaded — click to upload ${d.cardHint
                  .split(/[\\/]/)
                  .pop()}`
              : 'No AgentCard loaded — click to upload one'
          }
          onClick={(e) => {
            e.stopPropagation();
            d.onLoadCard?.(d.cardId);
          }}
        >
          ?
        </button>
      )}
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        style={{ background: '#94a3b8', width: 8, height: 8 }}
      />
    </div>
  );
}
