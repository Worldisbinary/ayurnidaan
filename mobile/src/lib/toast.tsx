// Small, dependency-free toasts: confirm that an action worked (or didn't) without a modal.
// Announced to screen readers via a live region.
import { Ionicons } from '@expo/vector-icons';
import { createContext, use, useCallback, useMemo, useRef, useState, type PropsWithChildren } from 'react';
import { Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { font, radius, space, usePalette } from '@/lib/theme';

type Tone = 'success' | 'error' | 'info';
interface Toast { id: number; message: string; tone: Tone }
type Show = (message: string, tone?: Tone) => void;

const ToastContext = createContext<Show | null>(null);

export function useToast(): Show {
  const show = use(ToastContext);
  if (!show) throw new Error('useToast must be used inside <ToastProvider>');
  return show;
}

export function ToastProvider({ children }: PropsWithChildren) {
  const [toast, setToast] = useState<Toast | null>(null);
  const [opacity] = useState(() => new Animated.Value(0));
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seq = useRef(0);

  const hide = useCallback(() => {
    Animated.timing(opacity, { toValue: 0, duration: 160, useNativeDriver: true }).start(() => setToast(null));
  }, [opacity]);

  const show = useCallback<Show>((message, tone = 'success') => {
    if (timer.current) clearTimeout(timer.current);
    seq.current += 1;
    setToast({ id: seq.current, message, tone });
    Animated.timing(opacity, { toValue: 1, duration: 160, useNativeDriver: true }).start();
    timer.current = setTimeout(hide, tone === 'error' ? 6000 : 3200);
  }, [hide, opacity]);

  const value = useMemo(() => show, [show]);
  return (
    <ToastContext value={value}>
      {children}
      {toast && <ToastView toast={toast} opacity={opacity} onClose={hide} />}
    </ToastContext>
  );
}

function ToastView({ toast, opacity, onClose }: { toast: Toast; opacity: Animated.Value; onClose: () => void }) {
  const c = usePalette();
  const insets = useSafeAreaInsets();
  const tone = {
    success: { icon: 'checkmark-circle' as const, color: c.good },
    error: { icon: 'alert-circle' as const, color: c.critical },
    info: { icon: 'information-circle' as const, color: c.accent },
  }[toast.tone];
  return (
    // pointerEvents in style (the prop form is ignored by react-native-web): taps pass through
    // the full-screen container to the page; only the toast itself is clickable.
    <View style={[StyleSheet.absoluteFill, { justifyContent: 'flex-end', alignItems: 'center', pointerEvents: 'box-none' }]}>
      <Animated.View
        accessibilityLiveRegion="polite"
        aria-live="polite"
        style={[styles.toast, {
          opacity, marginBottom: insets.bottom + 72, backgroundColor: c.text, borderLeftColor: tone.color,
          transform: [{ translateY: opacity.interpolate({ inputRange: [0, 1], outputRange: [12, 0] }) }],
        }]}>
        <Ionicons name={tone.icon} size={18} color={tone.color} />
        <Text style={{ color: c.bg, fontSize: font.md, flexShrink: 1 }}>{toast.message}</Text>
        <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Dismiss" hitSlop={8}>
          <Ionicons name="close" size={16} color={c.bg} />
        </Pressable>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  toast: {
    flexDirection: 'row', alignItems: 'center', gap: space.sm, maxWidth: 480, marginHorizontal: space.lg,
    paddingVertical: space.md, paddingHorizontal: space.lg, borderRadius: radius, borderLeftWidth: 4,
    shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 6,
  },
});
