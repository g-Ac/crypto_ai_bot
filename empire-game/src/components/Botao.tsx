import { Pressable, StyleSheet, Text, type ViewStyle } from 'react-native';
import { cores, espaco, fontes } from '../theme/tokens';

type Variante = 'primario' | 'ataque' | 'neutro' | 'fantasma';

interface Props {
  titulo: string;
  onPress: () => void;
  variante?: Variante;
  disabled?: boolean;
  style?: ViewStyle;
}

const fundo: Record<Variante, string> = {
  primario: cores.money,
  ataque: cores.blood,
  neutro: cores.bgElev,
  fantasma: 'transparent',
};

const borda: Record<Variante, string> = {
  primario: cores.moneyLight,
  ataque: cores.bloodLight,
  neutro: cores.cardBorder,
  fantasma: cores.cardBorder,
};

export function Botao({ titulo, onPress, variante = 'primario', disabled, style }: Props) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        styles.base,
        { backgroundColor: fundo[variante], borderColor: borda[variante] },
        pressed && !disabled ? styles.pressed : null,
        disabled ? styles.disabled : null,
        style,
      ]}
    >
      <Text style={styles.texto}>{titulo}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    paddingVertical: espaco.sm + 2,
    paddingHorizontal: espaco.md,
    borderRadius: 3,
    borderWidth: 2,
    alignItems: 'center',
  },
  texto: {
    fontFamily: fontes.titulo,
    fontSize: 13,
    color: cores.cream,
    letterSpacing: 0.5,
  },
  pressed: { transform: [{ scale: 0.96 }] },
  disabled: { opacity: 0.4 },
});
