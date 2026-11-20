// The app's TanStack Query cache, with one rule added (SMA-59): any 401, from any page,
// means the session may have ended. Then we ask "who am I?" again; if that is a 401 too,
// RequireAuth sends the user to Login with a friendly message.
import { MutationCache, QueryCache, QueryClient, type DefaultOptions } from '@tanstack/react-query'

import { isUnauthorized, ME_KEY } from '@/api/auth'

export function makeQueryClient(defaultOptions?: DefaultOptions): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    defaultOptions,
    queryCache: new QueryCache({
      onError: (error, query) => {
        // "who am I?" itself failing is handled by RequireAuth (and would loop here).
        if (query.queryKey[0] !== ME_KEY[0]) sessionMayHaveEnded(error)
      },
    }),
    mutationCache: new MutationCache({ onError: (error) => sessionMayHaveEnded(error) }),
  })

  function sessionMayHaveEnded(error: unknown) {
    if (isUnauthorized(error)) void queryClient.invalidateQueries({ queryKey: ME_KEY })
  }

  return queryClient
}
