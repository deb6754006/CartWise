// The user's starting point when they entered an address instead of allowing location. The result
// is kept on this device only. Locating it goes through our server, which keeps nothing, and needs
// no location permission (the device's own geocoder does on Android). Never log the address.
import * as SecureStore from 'expo-secure-store';

import { api } from '../api/client';
import { withTimeout } from '../profile/savedSelection';

export type Origin = { label: string; lat: number; lng: number };
// The AD-13 body. The OpenAPI does not describe it (see the deferred item of Story 1.5).
type ApiError = { error?: { code?: string } };

export const ORIGIN_KEY = 'cartwise.origin';

function isOrigin(value: unknown): value is Origin {
  const origin = value as Origin | null;
  return (
    typeof origin?.label === 'string' &&
    Number.isFinite(origin.lat) &&
    Number.isFinite(origin.lng)
  );
}

/**
 * Finds an address through the API. Resolves to null only when our server says it was not found:
 * a bare 404 may be a missing route on a proxy or an older server. Rejects on any other failure.
 * Saves nothing.
 */
export async function resolveAddress(text: string): Promise<Origin | null> {
  const label = text.trim();
  if (!label) return null;
  const { data, error } = await withTimeout((signal) =>
    api.GET('/v1/geo/geocode', { params: { query: { q: label } }, signal }),
  );
  if ((error as ApiError | undefined)?.error?.code === 'address_not_found') return null;
  const origin = { label, lat: data?.lat, lng: data?.lng };
  if (!isOrigin(origin)) throw new Error('geocode_failed');
  return origin;
}

/** Rejects when it was not saved. */
export async function saveOrigin(origin: Origin): Promise<void> {
  await SecureStore.setItemAsync(ORIGIN_KEY, JSON.stringify(origin));
}

/** The saved starting point, or null when there is none or it cannot be read. */
export async function getSavedOrigin(): Promise<Origin | null> {
  try {
    const stored = await SecureStore.getItemAsync(ORIGIN_KEY);
    const parsed: unknown = stored ? JSON.parse(stored) : null;
    return isOrigin(parsed) ? parsed : null;
  } catch {
    return null;
  }
}
