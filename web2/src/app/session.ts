import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { client, ok, type Schemas } from "../api/client";

export type Me = Schemas["Me"];
export type MyWorkspace = Schemas["MyWorkspace"];

/** Who is signed in, and their workspaces. A 401 means nobody: the query then fails. */
export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => ok(client.GET("/api/auth/me")) });

/** The workspace this page acts in, and the signed-in person's role there. */
export type Current = { me: Me; workspace: MyWorkspace };
export const CurrentContext = createContext<Current | null>(null);

export function useCurrent(): Current {
  const current = useContext(CurrentContext);
  if (!current) throw new Error("useCurrent outside a workspace");
  return current;
}

/** A superadmin looking into a workspace they are not a member of: read-only. */
export const isViewing = (workspace: MyWorkspace) => workspace.role === null || workspace.role === undefined;

/** Admins of the workspace may manage the team, compliance and settings. */
export const useIsAdmin = () => useCurrent().workspace.role === "admin";

const LAST = "outbound.workspace";

/** The workspace this browser used last, so `/` opens it again. */
export function lastWorkspace(): string | null {
  try {
    return localStorage.getItem(LAST);
  } catch {
    return null;
  }
}

export function rememberWorkspace(slug: string | null) {
  try {
    if (slug) localStorage.setItem(LAST, slug);
    else localStorage.removeItem(LAST);
  } catch {
    // private windows may refuse storage; `/` then opens the first workspace
  }
}

/** Where `/` should go for this person: the last workspace, else their only own one. */
export function homeFor(me: Me): string | null {
  const last = lastWorkspace();
  if (last && me.workspaces.some((w) => w.slug === last)) return last;
  const own = me.workspaces.filter((w) => w.role);
  return own.length >= 1 ? own[0].slug : null;
}

/** A link to a path inside a workspace. */
export const inWorkspace = (slug: string, path = "/") => `/w/${encodeURIComponent(slug)}${path === "/" ? "/" : path}`;

/** Leave the app's pages for another URL with a full load, so every cached answer is dropped. */
export const go = (url: string) => window.location.assign(url);
