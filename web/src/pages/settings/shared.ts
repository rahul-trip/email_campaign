import { useMutation, useQueryClient } from "@tanstack/react-query";

export const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

/** A save that refreshes the query it belongs to. */
export function useSave<T>(key: string, send: (value: T) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: send, onSuccess: () => queryClient.invalidateQueries({ queryKey: [key] }) });
}
