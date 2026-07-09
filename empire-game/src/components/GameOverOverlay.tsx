import { Modal, StyleSheet, Text, View } from 'react-native';
import { cores, espaco, fontes } from '../theme/tokens';
import { Botao } from './Botao';
import type { StatusPartida } from '../types/game';

interface Props {
  status: StatusPartida;
  respeito: number;
  turno: number;
  onJogarDeNovo: () => void;
  onMenu: () => void;
}

export function GameOverOverlay({ status, respeito, turno, onJogarDeNovo, onMenu }: Props) {
  const visivel = status === 'vitoria' || status === 'derrota';
  const vitoria = status === 'vitoria';
  return (
    <Modal visible={visivel} transparent animationType="fade">
      <View style={styles.overlay}>
        <View style={[styles.caixa, { borderColor: vitoria ? cores.moneyLight : cores.bloodLight }]}>
          <Text style={[styles.titulo, { color: vitoria ? cores.gold1 : cores.bloodLight }]}>
            {vitoria ? 'VITÓRIA' : 'DERROTA'}
          </Text>
          <Text style={styles.sub}>
            {vitoria
              ? 'Zona Sul é sua. O Sindicato virou história.'
              : 'Seu império ruiu. As ruas têm outro dono agora.'}
          </Text>
          <Text style={styles.stats}>
            Respeito {respeito} · Turno {turno}
          </Text>
          <View style={styles.botoes}>
            <Botao titulo="Jogar de novo" variante="primario" onPress={onJogarDeNovo} />
            <Botao titulo="Menu" variante="neutro" onPress={onMenu} />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.82)',
    justifyContent: 'center',
    padding: espaco.xl,
  },
  caixa: {
    backgroundColor: cores.bgElev,
    borderWidth: 3,
    borderRadius: 4,
    padding: espaco.xl,
    alignItems: 'center',
  },
  titulo: {
    fontFamily: fontes.titulo,
    fontSize: 40,
    letterSpacing: 2,
  },
  sub: {
    fontFamily: fontes.corpo,
    fontSize: 18,
    color: cores.cream,
    textAlign: 'center',
    marginTop: espaco.md,
  },
  stats: {
    fontFamily: fontes.corpo,
    fontSize: 16,
    color: cores.muted,
    marginTop: espaco.sm,
    marginBottom: espaco.lg,
  },
  botoes: { gap: espaco.sm, alignSelf: 'stretch' },
});
