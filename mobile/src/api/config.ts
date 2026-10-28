/** Host machine as seen from the Android emulator. */
export const DEFAULT_API_URL = 'http://10.0.2.2:8000';

export const API_URL = process.env.EXPO_PUBLIC_API_URL || DEFAULT_API_URL;
