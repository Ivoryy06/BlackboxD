// src/components/WorkspaceGrid.tsx
import { useState, useEffect, useCallback, useRef } from 'react';

// Types matching Go backend response
interface Monitor {
  id: number;
  name: string;
  focused: boolean;
  activeWorkspace: WorkspaceRef;
}

interface WorkspaceRef {
  id: number;
  name: string;
}

interface Workspace {
  id: number;
  name: string;
  monitor: string;
  windows: number;
  hasfullscreen: boolean;
  lastwindow: string;
  lastwindowtitle: string;
}

interface WorkspaceState {
  monitors: Monitor[];
  workspaces: Workspace[];
  activeWorkspace: number;
}

interface WorkspaceGridProps {
  apiUrl?: string;
  pollInterval?: number;
  columns?: number;
  onWorkspaceClick?: (id: number) => void;
  className?: string;
}

// API client with error handling
async function fetchWorkspaceState(apiUrl: string): Promise<WorkspaceState> {
  const response = await fetch(`${apiUrl}/api/workspaces`);
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
}

async function switchWorkspace(apiUrl: string, workspaceId: number): Promise<void> {
  const response = await fetch(`${apiUrl}/api/workspace/${workspaceId}`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Failed to switch workspace: ${response.status}`);
  }
}

// Individual workspace tile
interface WorkspaceTileProps {
  workspace: Workspace;
  isActive: boolean;
  isFocusedMonitor: boolean;
  onClick: () => void;
}

function WorkspaceTile({ workspace, isActive, isFocusedMonitor, onClick }: WorkspaceTileProps) {
  const tileClasses = [
    'workspace-tile',
    isActive && 'workspace-tile--active',
    isFocusedMonitor && 'workspace-tile--focused-monitor',
    workspace.hasfullscreen && 'workspace-tile--fullscreen',
    workspace.windows === 0 && 'workspace-tile--empty',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <button
      className={tileClasses}
      onClick={onClick}
      aria-label={`Workspace ${workspace.name}, ${workspace.windows} windows`}
      aria-pressed={isActive}
    >
      <span className="workspace-tile__id">{workspace.name}</span>
      {workspace.windows > 0 && (
        <span className="workspace-tile__window-count">{workspace.windows}</span>
      )}
      {workspace.hasfullscreen && (
        <span className="workspace-tile__fullscreen-indicator" aria-label="Fullscreen">
          ⛶
        </span>
      )}
    </button>
  );
}

// Monitor section
interface MonitorSectionProps {
  monitor: Monitor;
  workspaces: Workspace[];
  onWorkspaceClick: (id: number) => void;
}

function MonitorSection({ monitor, workspaces, onWorkspaceClick }: MonitorSectionProps) {
  const monitorWorkspaces = workspaces
    .filter((ws) => ws.monitor === monitor.name)
    .sort((a, b) => a.id - b.id);

  return (
    <section className="monitor-section" aria-label={`Monitor ${monitor.name}`}>
      <header className="monitor-section__header">
        <h3 className="monitor-section__name">{monitor.name}</h3>
        {monitor.focused && (
          <span className="monitor-section__focused-badge">focused</span>
        )}
      </header>
      <div className="monitor-section__workspaces">
        {monitorWorkspaces.map((ws) => (
          <WorkspaceTile
            key={ws.id}
            workspace={ws}
            isActive={ws.id === monitor.activeWorkspace.id}
            isFocusedMonitor={monitor.focused}
            onClick={() => onWorkspaceClick(ws.id)}
          />
        ))}
      </div>
    </section>
  );
}

// Connection status indicator
type ConnectionStatus = 'connected' | 'connecting' | 'error';

function ConnectionIndicator({ status }: { status: ConnectionStatus }) {
  const statusConfig = {
    connected: { label: 'Connected', className: 'status--connected' },
    connecting: { label: 'Connecting...', className: 'status--connecting' },
    error: { label: 'Disconnected', className: 'status--error' },
  };

  const { label, className } = statusConfig[status];

  return (
    <div className={`connection-indicator ${className}`} aria-live="polite">
      <span className="connection-indicator__dot" />
      <span className="connection-indicator__label">{label}</span>
    </div>
  );
}

// Main component
export function WorkspaceGrid({
  apiUrl = '[localhost](http://localhost:9099)',
  pollInterval = 500,
  onWorkspaceClick,
  className = '',
}: WorkspaceGridProps) {
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const fetchState = useCallback(async () => {
    try {
      const data = await fetchWorkspaceState(apiUrl);
      setState(data);
      setStatus('connected');
      setError(null);
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [apiUrl]);

  // Polling effect
  useEffect(() => {
    fetchState();

    pollRef.current = window.setInterval(fetchState, pollInterval);

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
      }
    };
  }, [fetchState, pollInterval]);

  const handleWorkspaceClick = useCallback(
    async (workspaceId: number) => {
      try {
        await switchWorkspace(apiUrl, workspaceId);
        // Immediate refresh after switch
        await fetchState();
        onWorkspaceClick?.(workspaceId);
      } catch (err) {
        console.error('Failed to switch workspace:', err);
      }
    },
    [apiUrl, fetchState, onWorkspaceClick]
  );

  if (status === 'connecting' && !state) {
    return (
      <div className={`workspace-grid workspace-grid--loading ${className}`}>
        <ConnectionIndicator status={status} />
        <p>Loading workspace state...</p>
      </div>
    );
  }

  if (status === 'error' && !state) {
    return (
      <div className={`workspace-grid workspace-grid--error ${className}`}>
        <ConnectionIndicator status={status} />
        <p className="error-message">{error}</p>
        <button onClick={fetchState} className="retry-button">
          Retry
        </button>
      </div>
    );
  }

  if (!state) {
    return null;
  }

  return (
    <div className={`workspace-grid ${className}`}>
      <header className="workspace-grid__header">
        <ConnectionIndicator status={status} />
      </header>

      <div className="workspace-grid__monitors">
        {state.monitors.map((monitor) => (
          <MonitorSection
            key={monitor.id}
            monitor={monitor}
            workspaces={state.workspaces}
            onWorkspaceClick={handleWorkspaceClick}
          />
        ))}
      </div>

      {/* Unassigned workspaces (special workspaces, etc.) */}
      {state.workspaces.some(
        (ws) => !state.monitors.find((m) => m.name === ws.monitor)
      ) && (
        <section className="workspace-grid__unassigned">
          <h3>Other Workspaces</h3>
          <div className="monitor-section__workspaces">
            {state.workspaces
              .filter((ws) => !state.monitors.find((m) => m.name === ws.monitor))
              .map((ws) => (
                <WorkspaceTile
                  key={ws.id}
                  workspace={ws}
                  isActive={ws.id === state.activeWorkspace}
                  isFocusedMonitor={false}
                  onClick={() => handleWorkspaceClick(ws.id)}
                />
              ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default WorkspaceGrid;
  
