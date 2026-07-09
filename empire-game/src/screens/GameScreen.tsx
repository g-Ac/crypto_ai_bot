import { useEffect, useMemo, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { cores, espaco, fontes } from '../theme/tokens';
import {
  CALOR_LIMIAR_BATIDA,
  CUSTO_ADVOGADO,
  CUSTO_ESPIONAGEM,
  CUSTO_RECRUTA,
} from '../data/seed';
import { useGameStore } from '../store/gameStore';
import {
  alvosPossiveis,
  armaDe,
  ataqueEstimado,
  bairroDe,
  defesaEstimada,
  destinosDeMovimento,
  faccaoDe,
  jogador as jogadorSel,
  soldadosNoBairro,
  temIntel,
} from '../engine/selectors';
import { BairroCard } from '../components/BairroCard';
import { Botao } from '../components/Botao';
import { GameOverOverlay } from '../components/GameOverOverlay';
import { LogPanel } from '../components/LogPanel';
import { LojaModal } from '../components/LojaModal';
import { SoldadoRow } from '../components/SoldadoRow';
import { StatPill } from '../components/StatPill';
import type { GameProps } from '../navigation/types';
import type { Soldado } from '../types/game';

function dePe(s: Soldado): boolean {
  return s.status === 'ativo' || s.status === 'ferido';
}

export function GameScreen({ navigation }: GameProps) {
  const insets = useSafeAreaInsets();
  const game = useGameStore((s) => s.game);
  const feedback = useGameStore((s) => s.feedback);
  const limparFeedback = useGameStore((s) => s.limparFeedback);
  const moverSoldado = useGameStore((s) => s.moverSoldado);
  const comprarArma = useGameStore((s) => s.comprarArma);
  const recrutarSoldado = useGameStore((s) => s.recrutarSoldado);
  const espionarBairro = useGameStore((s) => s.espionarBairro);
  const contratarAdvogado = useGameStore((s) => s.contratarAdvogado);
  const atacarBairro = useGameStore((s) => s.atacarBairro);
  const passarTurno = useGameStore((s) => s.passarTurno);
  const novoJogo = useGameStore((s) => s.novoJogo);
  const sairParaMenu = useGameStore((s) => s.sairParaMenu);

  const [selBairroId, setSelBairroId] = useState<string | null>(null);
  const [selSoldadoId, setSelSoldadoId] = useState<string | null>(null);
  const [lojaAberta, setLojaAberta] = useState(false);

  // Limpa o feedback automaticamente após um tempo.
  useEffect(() => {
    if (!feedback) return;
    const t = setTimeout(() => limparFeedback(), 2600);
    return () => clearTimeout(t);
  }, [feedback, limparFeedback]);

  const alvos = useMemo(
    () => (game ? new Set(alvosPossiveis(game, game.jogadorId).map((b) => b.id)) : new Set<string>()),
    [game],
  );

  if (!game) {
    return (
      <View style={styles.vazio}>
        <Text style={styles.vazioTxt}>Nenhuma partida ativa.</Text>
        <Botao titulo="Voltar ao menu" variante="neutro" onPress={() => navigation.navigate('Home')} />
      </View>
    );
  }

  const jog = jogadorSel(game);
  const selBairro = selBairroId ? bairroDe(game, selBairroId) : undefined;
  const selSoldado = selSoldadoId
    ? jog.soldados.find((s) => s.id === selSoldadoId) ?? null
    : null;

  const bairroEhDoJogador = selBairro?.dono === game.jogadorId;
  const bairroAtacavel = !!selBairro && alvos.has(selBairro.id);

  // Preview de combate pro alvo selecionado.
  const preview =
    selBairro && bairroAtacavel
      ? {
          ataque: ataqueEstimado(game, game.jogadorId, selBairro.id),
          defesa: defesaEstimada(game, selBairro.id),
        }
      : null;

  const destinos = selSoldado ? destinosDeMovimento(game, selSoldado) : [];

  function selecionarBairro(id: string) {
    setSelBairroId(id);
    setSelSoldadoId(null);
  }

  function abrirArsenal() {
    setLojaAberta(true);
  }

  const soldadosDoBairro = selBairro
    ? soldadosNoBairro(game, selBairro.dono ?? '', selBairro.id)
    : [];

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <ScrollView
        contentContainerStyle={[styles.conteudo, { paddingBottom: insets.bottom + 96 }]}
      >
        {/* Cabeçalho de turno */}
        <View style={styles.topbar}>
          <View>
            <Text style={styles.turnoTxt}>TURNO {game.turno.numero}</Text>
            <Text style={styles.cidadeTxt}>
              {game.cidade.nome} · {game.cidade.era}
            </Text>
          </View>
          <StatPill label="Ações" valor={game.turno.acoesRestantes} cor={cores.gold1} />
        </View>

        {/* Stats da facção */}
        <View style={styles.stats}>
          <StatPill label="Caixa" valor={`$${jog.caixa}`} cor={cores.moneyLight} />
          <StatPill label="Respeito" valor={jog.respeito} cor={cores.gold1} />
          <StatPill
            label="Calor"
            valor={jog.calor}
            cor={jog.calor >= CALOR_LIMIAR_BATIDA ? cores.danger : cores.bloodLight}
          />
        </View>

        {/* Advogado — esfria o calor (aparece com risco de batida) */}
        {jog.calor > 0 ? (
          <View style={styles.advogadoRow}>
            {jog.calor >= CALOR_LIMIAR_BATIDA ? (
              <Text style={styles.alerta}>⚠ Calor alto — risco de batida policial!</Text>
            ) : (
              <Text style={styles.advogadoDica}>Calor atrai a polícia.</Text>
            )}
            <Botao
              titulo={`Advogado ($${CUSTO_ADVOGADO})`}
              variante="neutro"
              disabled={jog.caixa < CUSTO_ADVOGADO}
              onPress={contratarAdvogado}
              style={styles.advogadoBtn}
            />
          </View>
        ) : null}

        {/* Mapa */}
        <Text style={styles.secao}>TERRITÓRIOS</Text>
        <View style={styles.mapa}>
          {game.cidade.bairros.map((b) => {
            const dono = b.dono ? faccaoDe(game, b.dono) : undefined;
            const num = b.dono ? soldadosNoBairro(game, b.dono, b.id).filter(dePe).length : 0;
            return (
              <BairroCard
                key={b.id}
                bairro={b}
                donoNome={dono?.nome ?? null}
                donoCor={dono?.cor ?? cores.neutral}
                numSoldados={num}
                selecionado={selBairroId === b.id}
                atacavel={alvos.has(b.id)}
                onPress={() => selecionarBairro(b.id)}
              />
            );
          })}
        </View>

        {/* Painel do bairro selecionado */}
        {selBairro ? (
          <View style={styles.painel}>
            <View style={styles.painelHeader}>
              <Text style={styles.painelNome}>{selBairro.nome}</Text>
              <Text style={styles.painelDono}>
                {selBairro.dono ? faccaoDe(game, selBairro.dono)?.nome : 'Neutro'}
              </Text>
            </View>

            {/* Recrutamento (só em bairro seu) */}
            {bairroEhDoJogador ? (
              <Botao
                titulo={`+ Recrutar soldado ($${CUSTO_RECRUTA})`}
                variante="primario"
                disabled={jog.caixa < CUSTO_RECRUTA}
                onPress={() => recrutarSoldado(selBairro.id)}
              />
            ) : null}

            {/* Ataque + espionagem */}
            {bairroAtacavel && preview ? (
              <View style={styles.ataqueBox}>
                <Text style={styles.previewTxt}>
                  Seu ataque <Text style={styles.previewNum}>{preview.ataque}</Text> vs defesa{' '}
                  <Text style={styles.previewNum}>{preview.defesa}</Text>
                </Text>
                {temIntel(game, game.jogadorId, selBairro.id) ? (
                  <Text style={styles.intelTag}>🎯 Intel ativo — ataque reforçado</Text>
                ) : null}
                <Botao
                  titulo={`⚔ Atacar ${selBairro.nome}`}
                  variante="ataque"
                  disabled={game.turno.acoesRestantes <= 0 || preview.ataque <= 0}
                  onPress={() => atacarBairro(selBairro.id)}
                />
                <Botao
                  titulo={`🔍 Espionar ($${CUSTO_ESPIONAGEM})`}
                  variante="neutro"
                  disabled={
                    game.turno.acoesRestantes <= 0 ||
                    jog.caixa < CUSTO_ESPIONAGEM ||
                    temIntel(game, game.jogadorId, selBairro.id)
                  }
                  onPress={() => espionarBairro(selBairro.id)}
                />
              </View>
            ) : null}

            {/* Soldados no bairro */}
            {soldadosDoBairro.length > 0 ? (
              <View style={styles.tropasBox}>
                <Text style={styles.subsecao}>TROPAS AQUI</Text>
                {soldadosDoBairro.map((s) => (
                  <SoldadoRow
                    key={s.id}
                    soldado={s}
                    arma={armaDe(game, s.armaId)}
                    selecionado={selSoldadoId === s.id}
                    selecionavel={bairroEhDoJogador && dePe(s)}
                    onPress={() => setSelSoldadoId((cur) => (cur === s.id ? null : s.id))}
                  />
                ))}
              </View>
            ) : (
              <Text style={styles.vazioBairro}>Sem tropas neste bairro.</Text>
            )}

            {/* Ações do soldado selecionado */}
            {selSoldado ? (
              <View style={styles.acoesSoldado}>
                <Text style={styles.subsecao}>{selSoldado.nome.toUpperCase()}</Text>
                <Botao titulo="Arsenal / armar" variante="primario" onPress={abrirArsenal} />
                {destinos.length > 0 ? (
                  <>
                    <Text style={styles.moverLabel}>Mover para:</Text>
                    <View style={styles.moverBtns}>
                      {destinos.map((d) => (
                        <Botao
                          key={d.id}
                          titulo={`→ ${d.nome}`}
                          variante="neutro"
                          disabled={game.turno.acoesRestantes <= 0}
                          onPress={() => moverSoldado(selSoldado.id, d.id)}
                          style={styles.moverBtn}
                        />
                      ))}
                    </View>
                  </>
                ) : (
                  <Text style={styles.semMover}>Nenhum bairro seu adjacente pra mover.</Text>
                )}
              </View>
            ) : bairroEhDoJogador ? (
              <Text style={styles.dica}>Toque num soldado pra mover ou armar.</Text>
            ) : null}
          </View>
        ) : (
          <Text style={styles.dica}>Toque num território pra ver detalhes e agir.</Text>
        )}

        {/* Relatório */}
        <LogPanel log={game.log} />
      </ScrollView>

      {/* Barra fixa inferior */}
      <View style={[styles.rodape, { paddingBottom: insets.bottom + espaco.sm }]}>
        {feedback ? (
          <Text style={styles.feedback} numberOfLines={2}>
            {feedback}
          </Text>
        ) : null}
        <View style={styles.rodapeBtns}>
          <Botao
            titulo="Menu"
            variante="fantasma"
            onPress={() => navigation.navigate('Home')}
            style={styles.btnMenu}
          />
          <Botao
            titulo="PASSAR TURNO ▶"
            variante="primario"
            onPress={passarTurno}
            style={styles.btnTurno}
          />
        </View>
      </View>

      <LojaModal
        visible={lojaAberta}
        armas={game.armas}
        caixa={jog.caixa}
        soldado={selSoldado}
        armaAtual={selSoldado ? armaDe(game, selSoldado.armaId) : undefined}
        onComprar={(armaId) => {
          if (selSoldado) comprarArma(armaId, selSoldado.id);
        }}
        onClose={() => setLojaAberta(false)}
      />

      <GameOverOverlay
        status={game.status}
        respeito={jog.respeito}
        turno={game.turno.numero}
        onJogarDeNovo={() => {
          novoJogo();
          setSelBairroId(null);
          setSelSoldadoId(null);
        }}
        onMenu={() => {
          sairParaMenu();
          navigation.navigate('Home');
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: cores.bg },
  conteudo: { padding: espaco.md, gap: espaco.md },
  vazio: { flex: 1, backgroundColor: cores.bg, justifyContent: 'center', alignItems: 'center', gap: espaco.md },
  vazioTxt: { fontFamily: fontes.corpo, fontSize: 18, color: cores.muted },

  topbar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  turnoTxt: { fontFamily: fontes.titulo, fontSize: 20, color: cores.gold1 },
  cidadeTxt: { fontFamily: fontes.corpo, fontSize: 15, color: cores.muted, marginTop: 2 },

  stats: { flexDirection: 'row', gap: espaco.sm },

  advogadoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: espaco.sm,
  },
  alerta: { flex: 1, fontFamily: fontes.corpo, fontSize: 15, color: cores.danger },
  advogadoDica: { flex: 1, fontFamily: fontes.corpo, fontSize: 14, color: cores.muted },
  advogadoBtn: { minWidth: 130 },
  intelTag: { fontFamily: fontes.corpo, fontSize: 14, color: cores.gold1, textAlign: 'center' },

  secao: {
    fontFamily: fontes.titulo,
    fontSize: 12,
    color: cores.muted,
    letterSpacing: 2,
    marginTop: espaco.xs,
  },
  mapa: { flexDirection: 'row', gap: espaco.sm },

  painel: {
    backgroundColor: cores.bgElev,
    borderWidth: 1,
    borderColor: cores.cardBorder,
    borderRadius: 3,
    padding: espaco.md,
    gap: espaco.sm,
  },
  painelHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  painelNome: { fontFamily: fontes.titulo, fontSize: 16, color: cores.cream },
  painelDono: { fontFamily: fontes.corpo, fontSize: 15, color: cores.muted },

  ataqueBox: {
    backgroundColor: cores.bg,
    borderRadius: 3,
    padding: espaco.sm,
    gap: espaco.sm,
  },
  previewTxt: { fontFamily: fontes.corpo, fontSize: 16, color: cores.cream, textAlign: 'center' },
  previewNum: { color: cores.gold1 },

  tropasBox: { gap: espaco.xs },
  subsecao: {
    fontFamily: fontes.titulo,
    fontSize: 10,
    color: cores.mutedDim,
    letterSpacing: 2,
    marginBottom: espaco.xs,
  },
  vazioBairro: { fontFamily: fontes.corpo, fontSize: 15, color: cores.mutedDim },

  acoesSoldado: {
    borderTopWidth: 1,
    borderTopColor: cores.cardBorder,
    paddingTop: espaco.sm,
    gap: espaco.sm,
  },
  moverLabel: { fontFamily: fontes.corpo, fontSize: 15, color: cores.muted },
  moverBtns: { flexDirection: 'row', flexWrap: 'wrap', gap: espaco.sm },
  moverBtn: { flexGrow: 1 },
  semMover: { fontFamily: fontes.corpo, fontSize: 14, color: cores.mutedDim },
  dica: { fontFamily: fontes.corpo, fontSize: 15, color: cores.mutedDim, textAlign: 'center' },

  rodape: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: cores.bgElev,
    borderTopWidth: 1,
    borderTopColor: cores.cardBorder,
    paddingHorizontal: espaco.md,
    paddingTop: espaco.sm,
    gap: espaco.xs,
  },
  feedback: {
    fontFamily: fontes.corpo,
    fontSize: 15,
    color: cores.gold1,
    textAlign: 'center',
  },
  rodapeBtns: { flexDirection: 'row', gap: espaco.sm },
  btnMenu: { flex: 1 },
  btnTurno: { flex: 2 },
});
