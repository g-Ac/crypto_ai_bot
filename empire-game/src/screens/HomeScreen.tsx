import { useEffect } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { cores, espaco, fontes } from '../theme/tokens';
import { useGameStore } from '../store/gameStore';
import type { HomeProps } from '../navigation/types';

interface Cidade {
  nome: string;
  era: string;
  desbloqueada: boolean;
}

// Grid da tela inicial (só "Zona Sul" jogável neste passo — resto é vitrine).
const CIDADES: Cidade[] = [
  { nome: 'Zona Sul', era: '2020s', desbloqueada: true },
  { nome: 'Porto Novo', era: '1980s', desbloqueada: false },
  { nome: 'Distrito Central', era: '1920s', desbloqueada: false },
  { nome: 'Baía Grande', era: '1970s', desbloqueada: false },
  { nome: 'Alto da Serra', era: '1950s', desbloqueada: false },
  { nome: 'Costa Velha', era: '1990s', desbloqueada: false },
];

export function HomeScreen({ navigation }: HomeProps) {
  const insets = useSafeAreaInsets();
  const novoJogo = useGameStore((s) => s.novoJogo);
  const carregar = useGameStore((s) => s.carregar);
  const verificarSave = useGameStore((s) => s.verificarSave);
  const temSave = useGameStore((s) => s.temSave);

  useEffect(() => {
    void verificarSave();
  }, [verificarSave]);

  function iniciar(cidade: Cidade) {
    if (!cidade.desbloqueada) return;
    novoJogo();
    navigation.navigate('Game');
  }

  async function continuar() {
    const ok = await carregar();
    if (ok) navigation.navigate('Game');
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.conteudo,
        { paddingTop: insets.top + espaco.lg, paddingBottom: insets.bottom + espaco.xl },
      ]}
    >
      <View style={styles.titleblock}>
        <Text style={styles.title}>TERRITÓRIO</Text>
        <Text style={styles.subtitle}>
          DINHEIRO • PODER <Text style={styles.n2}>2</Text>
        </Text>
      </View>

      <View style={styles.divider} />

      {temSave ? (
        <Pressable onPress={continuar} style={styles.continuar}>
          <Text style={styles.continuarTxt}>▶ Continuar partida</Text>
        </Pressable>
      ) : (
        <Text style={styles.recorde}>Sem partida salva</Text>
      )}

      <Text style={styles.novoLabel}>— Novo Jogo —</Text>

      <View style={styles.grid}>
        {CIDADES.map((c) => (
          <Pressable
            key={c.nome}
            onPress={() => iniciar(c)}
            style={({ pressed }) => [
              styles.card,
              c.desbloqueada ? styles.cardUnlocked : styles.cardLocked,
              pressed && c.desbloqueada ? styles.cardPressed : null,
            ]}
          >
            {!c.desbloqueada ? <Text style={styles.lockword}>DESBLOQUEAR</Text> : null}
            <Text style={[styles.cardNome, c.desbloqueada ? styles.cardNomeUnlocked : styles.cardNomeLocked]}>
              {c.nome}
            </Text>
            {c.desbloqueada ? <Text style={styles.era}>{c.era}</Text> : null}
            {!c.desbloqueada ? <Text style={styles.lock}>🔒</Text> : null}
          </Pressable>
        ))}
      </View>

      <View style={styles.footer}>
        <Text style={styles.brand}>SEU ESTÚDIO AQUI</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: cores.bg },
  conteudo: {
    paddingHorizontal: espaco.lg,
    gap: espaco.lg,
  },
  titleblock: { alignItems: 'center', marginTop: espaco.sm },
  title: {
    fontFamily: fontes.titulo,
    fontSize: 46,
    color: cores.gold1,
    textShadowColor: cores.gold2,
    textShadowOffset: { width: 3, height: 3 },
    textShadowRadius: 0,
    transform: [{ rotate: '-1.2deg' }],
  },
  subtitle: {
    fontFamily: fontes.titulo,
    fontSize: 15,
    letterSpacing: 5,
    color: cores.cream,
    marginTop: espaco.sm,
    opacity: 0.85,
  },
  n2: { color: cores.moneyLight, fontSize: 19 },
  divider: {
    height: 2,
    backgroundColor: cores.gold2,
    opacity: 0.5,
  },
  continuar: {
    backgroundColor: cores.money,
    borderWidth: 2,
    borderColor: cores.moneyLight,
    borderRadius: 3,
    paddingVertical: espaco.md,
    alignItems: 'center',
  },
  continuarTxt: {
    fontFamily: fontes.titulo,
    fontSize: 15,
    color: cores.cream,
  },
  recorde: {
    fontFamily: fontes.corpo,
    fontSize: 18,
    color: cores.muted,
    textAlign: 'center',
  },
  novoLabel: {
    fontFamily: fontes.corpo,
    fontSize: 17,
    letterSpacing: 3,
    color: cores.mutedDim,
    textAlign: 'center',
    textTransform: 'uppercase',
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: espaco.md,
  },
  card: {
    width: '47%',
    flexGrow: 1,
    borderRadius: 3,
    borderWidth: 2,
    padding: espaco.md,
    minHeight: 76,
    justifyContent: 'center',
    alignItems: 'center',
  },
  cardUnlocked: {
    backgroundColor: cores.money,
    borderColor: cores.moneyLight,
  },
  cardLocked: {
    backgroundColor: cores.cardLocked,
    borderColor: cores.cardBorder,
  },
  cardPressed: { transform: [{ scale: 0.96 }] },
  cardNome: {
    fontFamily: fontes.titulo,
    fontSize: 14,
    textAlign: 'center',
  },
  cardNomeUnlocked: { color: '#eafbe9' },
  cardNomeLocked: { color: '#a8a190' },
  era: {
    fontFamily: fontes.corpo,
    fontSize: 14,
    color: cores.cream,
    opacity: 0.75,
    letterSpacing: 2,
    marginTop: 2,
  },
  lockword: {
    fontFamily: fontes.corpo,
    fontSize: 13,
    letterSpacing: 3,
    color: cores.gold1,
    opacity: 0.8,
    marginBottom: 2,
  },
  lock: { position: 'absolute', top: 6, right: 8, fontSize: 12, opacity: 0.6 },
  footer: { marginTop: espaco.md, alignItems: 'center' },
  brand: {
    fontFamily: fontes.corpo,
    fontSize: 14,
    color: cores.mutedDim,
    letterSpacing: 2,
  },
});
