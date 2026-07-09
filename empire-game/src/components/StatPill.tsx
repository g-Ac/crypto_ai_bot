import { StyleSheet, Text, View } from 'react-native';
import { cores, espaco, fontes } from '../theme/tokens';

interface Props {
  label: string;
  valor: string | number;
  cor?: string;
}

export function StatPill({ label, valor, cor = cores.gold1 }: Props) {
  return (
    <View style={styles.pill}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.valor, { color: cor }]}>{valor}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    backgroundColor: cores.bgElev,
    borderWidth: 1,
    borderColor: cores.cardBorder,
    borderRadius: 3,
    paddingVertical: espaco.xs,
    paddingHorizontal: espaco.sm,
    alignItems: 'center',
    minWidth: 64,
  },
  label: {
    fontFamily: fontes.corpo,
    fontSize: 13,
    color: cores.muted,
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  valor: {
    fontFamily: fontes.corpo,
    fontSize: 20,
    lineHeight: 22,
  },
});
