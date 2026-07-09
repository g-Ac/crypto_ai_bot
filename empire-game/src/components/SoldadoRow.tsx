import { Pressable, StyleSheet, Text, View } from 'react-native';
import { cores, corStatus, espaco, fontes } from '../theme/tokens';
import type { Arma, Soldado } from '../types/game';

interface Props {
  soldado: Soldado;
  arma: Arma | undefined;
  selecionado: boolean;
  selecionavel: boolean;
  onPress?: () => void;
}

export function SoldadoRow({ soldado, arma, selecionado, selecionavel, onPress }: Props) {
  const cor = corStatus[soldado.status] ?? cores.cream;
  return (
    <Pressable
      onPress={selecionavel ? onPress : undefined}
      style={[
        styles.row,
        selecionado ? styles.selecionado : null,
        !selecionavel ? styles.inerte : null,
      ]}
    >
      <View style={styles.esq}>
        <Text style={styles.nome} numberOfLines={1}>
          {soldado.nome}
        </Text>
        <Text style={styles.detalhe}>
          {arma?.nome ?? 'Desarmado'} · {soldado.traco}
        </Text>
      </View>
      <View style={styles.dir}>
        <Text style={styles.forca}>fç {soldado.forca}</Text>
        <Text style={[styles.status, { color: cor }]}>{soldado.status}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: espaco.sm,
    paddingHorizontal: espaco.sm,
    borderRadius: 3,
    borderWidth: 1,
    borderColor: 'transparent',
    marginBottom: espaco.xs,
    backgroundColor: cores.bg,
  },
  selecionado: {
    borderColor: cores.gold1,
    backgroundColor: '#20200f',
  },
  inerte: { opacity: 0.7 },
  esq: { flex: 1, paddingRight: espaco.sm },
  dir: { alignItems: 'flex-end' },
  nome: {
    fontFamily: fontes.corpo,
    fontSize: 18,
    color: cores.cream,
    lineHeight: 20,
  },
  detalhe: {
    fontFamily: fontes.corpo,
    fontSize: 14,
    color: cores.muted,
  },
  forca: {
    fontFamily: fontes.corpo,
    fontSize: 16,
    color: cores.gold1,
  },
  status: {
    fontFamily: fontes.corpo,
    fontSize: 13,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
});
