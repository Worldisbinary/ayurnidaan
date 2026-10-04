// Token persistence: Keychain/Keystore via SecureStore on device, localStorage on web
// (web has no secure enclave; tokens are short-lived and revocable server-side).
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export async function setItem(key: string, value: string | null): Promise<void> {
  if (Platform.OS === 'web') {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {
      // storage disabled (private mode): session lasts for this tab only
    }
    return;
  }
  if (value === null) await SecureStore.deleteItemAsync(key);
  else await SecureStore.setItemAsync(key, value);
}

export async function getItem(key: string): Promise<string | null> {
  if (Platform.OS === 'web') {
    try {
      return typeof localStorage === 'undefined' ? null : localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  return SecureStore.getItemAsync(key);
}
