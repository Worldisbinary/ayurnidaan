import { Ionicons } from '@expo/vector-icons';
import type { ColorValue } from 'react-native';

export function tabIcon(name: keyof typeof Ionicons.glyphMap) {
  return function TabIcon({ color, size }: { color: ColorValue; size: number }) {
    return <Ionicons name={name} size={size - 4} color={color as string} />;
  };
}
