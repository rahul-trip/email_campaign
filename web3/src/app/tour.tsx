/** The guided tour. web3's Shell starts it from the account menu (outbound:tour event); the
 * step list is rebuilt for web3's screens with the rest of the tour. */
export function useTour() {
  return { start: () => window.dispatchEvent(new Event("outbound:tour")) };
}
