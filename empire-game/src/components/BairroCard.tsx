import { Pressable, StyleSheet, Text, View } from 'react-native';
import { cores, espaco, fontes } from '../theme/tokens';
import type { Bairro } from '../types/game';

interface Props {
  bairro: Bairro;
  donoNome: string | null;
  donoCor: string;
  numSoldados: number;
  selecionado: boolean;
  atacavel: boolean;
  onPress: () => void;
}

export function BairroCard({
  bairro,
  donoNome,
  donoCor,
  numSoldados,
  selecionado,
  atacavel,
  onPress,
}: Props) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.card,
        { borderColor: selecionado ? cores.gold1 : donoCor },
        selecionado ? styles.selecionado : null,
        pressed ? styles.pressed : null,
      ]}
    >
      <Text style={styles.nome} numberOfLines={1}>
        {bairro.nome}
      </Text>
      <Text style={[styles.dono, { color: donoCor }]} numberOfLines={1}>
        {donoNome ?? 'Neutro'}
      </Text>
      <View style={styles.linha}>
        <Text style={styles.meta}>${bairro.valorBase}</Text>
        <Text style={styles.meta}>risco {bairro.risco}</Text>
      </View>
      <View style={styles.rodape}>
        <Text style={styles.tropas}>♦ {numSoldados}</Text>
        {bairro.producao > 0 ? <Text style={styles.boca}>▲ {bairro.producao}</Text> : null}
        {atacavel ? <Text style={styles.alvo}>⚔ ALVO</Text> : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: cores.bgElev,
    borderWidth: 2,
    borderRadius: 3,
    padding: espaco.sm,
    minHeight: 108,
  },
  selecionado: { backgroundColor: '#20200f' },
  pressed: { transform: [{ scale: 0.97 }] },
  nome: {
    fontFamily: fontes.titulo,
    fontSize: 12,
    color: cores.cream,
  },
  dono: {
    fontFamily: fontes.corpo,
    fontSize: 15,
    marginTop: 2,
  },
  linha: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: espaco.xs,
  },
  meta: {
    fontFamily: fontes.corpo,
    fontSize: 14,
    color: cores.muted,
  },
  rodape: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 'auto',
    paddingTop: espaco.xs,
  },
  tropas: {
    fontFamily: fontes.corpo,
    fontSize: 16,
    color: cores.cream,
  },
  boca: {
    fontFamily: fontes.corpo,
    fontSize: 15,
    color: cores.moneyLight,
  },
  alvo: {
    fontFamily: fontes.corpo,
    fontSize: 14,
    color: cores.bloodLight,
    letterSpacing: 1,
  },
});
