import { NavigationContainer, DefaultTheme, type Theme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { cores } from '../theme/tokens';
import { HomeScreen } from '../screens/HomeScreen';
import { GameScreen } from '../screens/GameScreen';
import type { RootStackParamList } from './types';

const Stack = createNativeStackNavigator<RootStackParamList>();

const tema: Theme = {
  ...DefaultTheme,
  dark: true,
  colors: {
    ...DefaultTheme.colors,
    background: cores.bg,
    card: cores.bg,
    text: cores.cream,
    primary: cores.gold1,
    border: cores.cardBorder,
  },
};

export function RootNavigator() {
  return (
    <NavigationContainer theme={tema}>
      <Stack.Navigator screenOptions={{ headerShown: false, contentStyle: { backgroundColor: cores.bg } }}>
        <Stack.Screen name="Home" component={HomeScreen} />
        <Stack.Screen name="Game" component={GameScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
