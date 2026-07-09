import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { cores, espaco, fontes } from '../theme/tokens';
import type { LogEntry, LogTipo } from '../types/game';

const CORES_TIPO: Record<LogTipo, string> = {
  info: cores.muted,
  combate: cores.bloodLight,
  ia: cores.gold1,
  renda: cores.moneyLight,
  sistema: cores.cream,
  fim: cores.gold1,
};

interface Props {
  log: LogEntry[];
  max?: number;
}

export function LogPanel({ log, max = 12 }: Props) {
  const recentes = log.slice(-max).reverse();
  return (
    <View style={styles.painel}>
      <Text style={styles.titulo}>RELATÓRIO</Text>
      <ScrollView style={styles.scroll} nestedScrollEnabled>
        {recentes.map((e) => (
          <Text key={e.id} style={[styles.linha, { color: CORES_TIPO[e.tipo] }]}>
            <Text style={styles.turno}>[{e.turno}] </Text>
            {e.texto}
          </Text>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  painel: {
    backgroundColor: cores.bgElev,
    borderWidth: 1,
    borderColor: cores.cardBorder,
    borderRadius: 3,
    padding: espaco.sm,
  },
  titulo: {
    fontFamily: fontes.titulo,
    fontSize: 11,
    color: cores.muted,
    letterSpacing: 2,
    marginBottom: espaco.xs,
  },
  scroll: { maxHeight: 150 },
  linha: {
    fontFamily: fontes.corpo,
    fontSize: 15,
    lineHeight: 19,
    marginBottom: 2,
  },
  turno: { color: cores.mutedDim },
});
