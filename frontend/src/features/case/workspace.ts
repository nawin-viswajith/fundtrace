import { createContext, useContext } from "react";
import type { CaseContext } from "../../types/api";

export type TabId = "overview" | "graph" | "timeline" | "risk" | "evidence" | "report" | "audit";

export const TAB_IDS: TabId[] = ["overview", "graph", "timeline", "risk", "evidence", "report", "audit"];

export interface WorkspaceApi {
  caseId: string;
  ctx: CaseContext;
  setTab: (t: TabId) => void;
  /** Switch to the trail graph and highlight these record ids. */
  showOnGraph: (ids: string[]) => void;
  highlight: string[];
  clearHighlight: () => void;
}

export const WorkspaceCtx = createContext<WorkspaceApi | null>(null);

export function useWorkspace(): WorkspaceApi {
  const v = useContext(WorkspaceCtx);
  if (!v) throw new Error("useWorkspace outside CaseWorkspace");
  return v;
}
