---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Add a screen or a tour step

1. **The data.** Make sure the API serves what the screen needs ([add an API endpoint](add-an-api-endpoint.md)), and regenerate the client with `npm run gen:api`.
2. **The page.** Create `web2/src/pages/<Name>.tsx`:
   - fetch with `useQuery({ queryKey, queryFn: () => ok(client.GET(...)) })`;
   - render through `QueryState` (loading, error, empty);
   - write with `useMutation` and invalidate the affected keys;
   - show `ApiProblem` with `Problem` or `Field`;
   - handle `isConflict` (409) by reloading.
3. **Words and colours.** Use the components in `web2/src/components/ui.tsx`, and status words and colours from `web2/src/lib/status.ts`. Never hard-code a status label. Follow the tokens in [design.md](../../design.md).
4. **The route.** Add a lazy route in `web2/src/router.tsx`. Put list filters in the URL (`validateSearch`) so views can be linked. Add it to the navigation in `web2/src/app/nav.ts`.
5. **The tour (required, [CLAUDE.md](../../../CLAUDE.md)):**
   - Mark the elements worth pointing at with `data-tour="<name>"`, or `tour="<name>"` on a `Card` or `Tabs`.
   - Add or edit a section and its steps in `web2/src/tour/steps.ts`.
   - Update the "Guided tour" part of [USER_MANUAL.md](../../USER_MANUAL.md#31-the-guided-tour).
   - `web2/e2e/tour.spec.ts` fails if a step points at a missing element.
6. **Tests:** add the screen to `web2/e2e/screens.spec.ts` (it must open without console errors on a laptop and a phone), and a flow test for any new action. Run `npm run typecheck && npm run build && npx playwright test`.
7. **The manual:** document the screen in [USER_MANUAL.md §5](../../USER_MANUAL.md#5-the-screens), and update the [web frontend LLD](../lld/web-frontend.md) if the structure changed.
