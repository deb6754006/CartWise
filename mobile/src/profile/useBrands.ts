import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api/client';
import type { components } from '../api/schema';
import { createSelectionSaver, loadAfterSave, useSavedSelection, withTimeout } from './savedSelection';

export type Brand = components['schemas']['MyBrandOut'];
export type BrandsStatus = 'loading' | 'error' | 'ready';
/** idle: nothing to search for. searching: waiting for typing to stop, or for the answer. */
export type BrandSearchStatus = 'idle' | 'searching' | 'done' | 'error';

export const SEARCH_DEBOUNCE_MS = 300;
export const MIN_SEARCH_LENGTH = 2;
/** What the server accepts. */
export const MAX_SEARCH_LENGTH = 100;

const NO_BRANDS: readonly Brand[] = [];

function sameBrands(a: readonly Brand[], b: readonly Brand[]): boolean {
  return a.length === b.length && a.every((brand) => b.some((other) => other.id === brand.id));
}

const saver = createSelectionSaver<readonly Brand[]>(async (brands, signal) => {
  const { data } = await api.PUT('/v1/me/brands', {
    body: { brand_ids: brands.map((brand) => brand.id) },
    signal,
  });
  if (!data) throw new Error('brands_save_failed');
}, sameBrands);

/** The brands this user wants. Rejects when the request fails. */
export async function loadBrands(): Promise<Brand[]> {
  const { data } = await loadAfterSave(saver, (signal) => api.GET('/v1/me/brands', { signal }));
  if (!data) throw new Error('brands_load_failed');
  return data.brands;
}

/**
 * The brands screen's state. See useSavedSelection for how a change is saved. A search runs
 * once typing stops, and only the answer to the latest text is shown.
 */
export function useBrands() {
  const [status, setStatus] = useState<BrandsStatus>('loading');
  const [attempt, setAttempt] = useState(0);
  const { value: selected, saveFailed, reset, change } = useSavedSelection(saver, NO_BRANDS);

  const [query, setQuery] = useState('');
  const [searchStatus, setSearchStatus] = useState<BrandSearchStatus>('idle');
  const [found, setFound] = useState<Brand[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const latestSearch = useRef(0);

  useEffect(() => {
    let current = true;
    loadBrands().then(
      (brands) => {
        if (!current) return;
        reset(brands);
        setStatus('ready');
      },
      () => {
        if (current) setStatus('error');
      },
    );
    return () => {
      current = false;
    };
  }, [attempt, reset]);

  useEffect(
    () => () => {
      clearTimeout(timer.current);
      latestSearch.current = -1; // an answer that arrives after leaving is dropped
    },
    [],
  );

  const reload = useCallback(() => {
    setStatus('loading');
    setAttempt((n) => n + 1);
  }, []);

  const search = useCallback((text: string) => {
    clearTimeout(timer.current);
    const id = ++latestSearch.current;
    setQuery(text);
    setFound([]);
    if (text.trim().length < MIN_SEARCH_LENGTH) {
      setSearchStatus('idle');
      return;
    }
    setSearchStatus('searching');
    timer.current = setTimeout(() => {
      withTimeout((signal) =>
        api.GET('/v1/brands/search', { params: { query: { q: text } }, signal }),
      ).then(
        ({ data }) => {
          if (id !== latestSearch.current) return;
          if (!data) {
            setSearchStatus('error');
            return;
          }
          setFound(data);
          setSearchStatus('done');
        },
        () => {
          if (id === latestSearch.current) setSearchStatus('error');
        },
      );
    }, SEARCH_DEBOUNCE_MS);
  }, []);

  const add = useCallback(
    (brand: Brand) => {
      change((current) =>
        current.some((other) => other.id === brand.id) ? current : [...current, brand],
      );
      search('');
    },
    [change, search],
  );

  const remove = useCallback(
    (brandId: string) => {
      change((current) => current.filter((brand) => brand.id !== brandId));
    },
    [change],
  );

  // A chosen brand is not offered again. Whether anything was found is the server's answer, so
  // "not found" is not said about a brand that is right there among the chosen ones.
  const results = found.filter((brand) => !selected.some((other) => other.id === brand.id));
  const noResults = searchStatus === 'done' && found.length === 0;

  return {
    status,
    selected,
    saveFailed,
    reload,
    add,
    remove,
    query,
    search,
    searchStatus,
    results,
    noResults,
  };
}
