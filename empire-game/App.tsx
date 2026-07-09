import { StatusBar } from 'expo-status-bar';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useFonts, Bungee_400Regular } from '@expo-google-fonts/bungee';
import { VT323_400Regular } from '@expo-google-fonts/vt323';
import { RootNavigator } from './src/navigation/RootNavigator';
import { cores } from './src/theme/tokens';

export default function App() {
  const [fontesCarregadas] = useFonts({
    Bungee_400Regular,
    VT323_400Regular,
  });

  if (!fontesCarregadas) {
    return (
      <View style={styles.carregando}>
        <ActivityIndicator color={cores.gold1} size="large" />
      </View>
    );
  }

  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <RootNavigator />
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  carregando: {
    flex: 1,
    backgroundColor: cores.bg,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
