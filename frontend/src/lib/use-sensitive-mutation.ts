import { useCallback, useEffect, useRef, useState } from "react";

type MutationCallbacks<TData, TVariables, TContext> = {
  onError?: (error: Error, variables: TVariables, context: TContext | undefined) => unknown;
  onSettled?: (
    data: TData | undefined,
    error: Error | null,
    variables: TVariables,
    context: TContext | undefined,
  ) => unknown;
  onSuccess?: (data: TData, variables: TVariables, context: TContext | undefined) => unknown;
};

type SensitiveMutationOptions<TData, TVariables, TPublicVariables, TContext> =
  MutationCallbacks<TData, TVariables, TContext> & {
    mutationFn: (variables: TVariables) => Promise<TData>;
    onMutate?: (variables: TVariables) => TContext | Promise<TContext>;
    publicVariables?: (variables: TVariables) => TPublicVariables;
  };

type MutateCallOptions<TData, TVariables, TContext> =
  MutationCallbacks<TData, TVariables, TContext>;

/**
 * Execute secret-bearing mutations outside TanStack MutationCache.
 * Only an explicitly projected, non-sensitive variable may enter React state.
 */
function useSensitiveMutation<
  TData,
  TVariables,
  TPublicVariables = never,
  TContext = unknown,
>(
  options: SensitiveMutationOptions<TData, TVariables, TPublicVariables, TContext>,
) {
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const generationRef = useRef(0);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [variables, setVariables] = useState<TPublicVariables | undefined>();

  const reset = useCallback(() => {
    generationRef.current += 1;
    setIsPending(false);
    setError(null);
    setVariables(undefined);
  }, []);

  useEffect(() => () => {
    generationRef.current += 1;
  }, []);

  const mutateAsync = useCallback(async (
    input: TVariables,
    callOptions: MutateCallOptions<TData, TVariables, TContext> = {},
  ): Promise<TData> => {
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    const current = optionsRef.current;
    setError(null);
    setIsPending(true);
    setVariables(current.publicVariables?.(input));
    let context: TContext | undefined;
    let data: TData | undefined;
    let caught: Error | null = null;
    try {
      context = await current.onMutate?.(input);
      data = await current.mutationFn(input);
      await current.onSuccess?.(data, input, context);
      await callOptions.onSuccess?.(data, input, context);
      return data;
    } catch (reason) {
      caught = reason instanceof Error ? reason : new Error("Operazione non riuscita");
      if (generationRef.current === generation) setError(caught);
      await current.onError?.(caught, input, context);
      await callOptions.onError?.(caught, input, context);
      throw reason;
    } finally {
      await current.onSettled?.(data, caught, input, context);
      await callOptions.onSettled?.(data, caught, input, context);
      if (generationRef.current === generation) {
        setIsPending(false);
        setVariables(undefined);
      }
    }
  }, []);

  const mutate = useCallback((
    input: TVariables,
    callOptions: MutateCallOptions<TData, TVariables, TContext> = {},
  ) => {
    void mutateAsync(input, callOptions).catch(() => undefined);
  }, [mutateAsync]);

  return {
    data: undefined,
    error,
    isPending,
    mutate,
    mutateAsync,
    reset,
    variables,
  };
}

export { useSensitiveMutation };
