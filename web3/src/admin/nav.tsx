/** Links and navigation inside the console. The workspace app registers its own routes for
 * typed links; the console has different ones, so these are the same components with the route
 * names loosened to strings. */
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import type { ReactNode } from "react";

type LinkProps = {
  to: string;
  params?: Record<string, string>;
  className?: string;
  children?: ReactNode;
  activeOptions?: { exact?: boolean };
  activeProps?: { className?: string };
  title?: string;
};

export const A = Link as unknown as (props: LinkProps) => React.JSX.Element;
export const useGo = () => useNavigate() as unknown as (options: { to: string; params?: Record<string, string> }) => Promise<void>;
export const useId = () => (useParams({ strict: false }) as { id?: string }).id ?? "";
