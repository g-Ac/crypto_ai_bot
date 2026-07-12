/**
 * Fase da IA (doc, seção 4.4): cada facção rival age conforme seu arquétipo.
 * Reusa as mesmas ações do jogador (comprar / mover / atacar) — a IA joga com
 * as mesmas regras.
 */

import {
  CALOR_LIMIAR_BATIDA,
  CUSTO_ADVOGADO,
  CUSTO_BOCA,
  CUSTO_ESPIONAGEM,
  CUSTO_RECRUTA,
  MAX_BOCA_NIVEL,
} from '../data/seed';
import {
  atacarBairro,
  comprarArma,
  construirBoca,
  contratarAdvogado,
  espionarBairro,
  moverSoldado,
  recrutarSoldado,
  type ResultadoAcao,
} from './actions';
import { participaDeCombate, type Rng } from './combat';
import {
  alvosPossiveis,
  armaDe,
  bairrosDaFaccao,
  defesaEstimada,
  faccaoDe,
  forcaDeAtaque,
} from './selectors';
import type { Arquetipo, GameState } from '../types/game';

interface ConfigArquetipo {
  /** Razão mínima força-de-ataque / defesa pra decidir atacar. */
  razaoAtaque: number;
  /** Caixa que a IA segura de reserva antes de comprar armas. */
  reservaCaixa: number;
  /** Peso extra ao mirar bairros do jogador (>1 = prefere o jogador). */
  pesoJogador: number;
  /** Peso extra ao mirar bairros neutros. */
  pesoNeutro: number;
  /** Tamanho de exército (soldados de pé) a partir do qual a IA para de recrutar. */
  tetoExercito: number;
}

const CONFIG: Record<Arquetipo, ConfigArquetipo> = {
  agressivo: { razaoAtaque: 0.9, reservaCaixa: 0, pesoJogador: 1.4, pesoNeutro: 1.0, tetoExercito: 7 },
  paciente: { razaoAtaque: 1.4, reservaCaixa: 400, pesoJogador: 0.8, pesoNeutro: 1.3, tetoExercito: 6 },
  oportunista: { razaoAtaque: 1.15, reservaCaixa: 150, pesoJogador: 0.7, pesoNeutro: 1.5, tetoExercito: 6 },
};

/** Tenta uma compra de arma pro soldado mais fraco. Devolve estado (mutado ou não). */
function comprarSePossivel(state: GameState, faccaoId: string, cfg: ConfigArquetipo): GameState {
  const fac = faccaoDe(state, faccaoId);
  if (!fac) return state;

  const orcamento = fac.caixa - cfg.reservaCaixa;
  if (orcamento <= 0) return state;

  // Soldado que mais se beneficia de upgrade = o de arma mais fraca.
  const candidatos = fac.soldados
    .filter((s) => s.status === 'ativo' || s.status === 'ferido')
    .map((s) => ({ s, dano: armaDe(state, s.armaId)?.dano ?? 0 }))
    .sort((a, b) => a.dano - b.dano);
  if (candidatos.length === 0) return state;

  const alvo = candidatos[0];

  // Melhor arma que cabe no orçamento e é upgrade real.
  const melhor = state.armas
    .filter((a) => a.dano > alvo.dano && a.custo <= orcamento && a.cidadesDisponiveis.includes(state.cidade.id))
    .sort((a, b) => b.dano - a.dano)[0];
  if (!melhor) return state;

  const r: ResultadoAcao = comprarArma(state, faccaoId, melhor.id, alvo.s.id);
  return r.ok ? r.state : state;
}

/**
 * Recruta reforços enquanto o exército está abaixo do teto e sobra caixa acima
 * da reserva. Recruta no bairro próprio de maior valor (retaguarda produtiva).
 */
function recrutarSePossivel(
  state: GameState,
  faccaoId: string,
  cfg: ConfigArquetipo,
  rng: Rng,
): GameState {
  let atual = state;
  let guard = 0;
  while (guard++ < 3) {
    const fac = faccaoDe(atual, faccaoId);
    if (!fac) break;
    const vivos = fac.soldados.filter(participaDeCombate).length;
    if (vivos >= cfg.tetoExercito) break;
    if (fac.caixa - cfg.reservaCaixa < CUSTO_RECRUTA) break;

    const base = bairrosDaFaccao(atual, faccaoId).sort((a, b) => b.valorBase - a.valorBase)[0];
    if (!base) break;

    const r = recrutarSoldado(atual, faccaoId, base.id, rng);
    if (!r.ok) break;
    atual = r.state;
  }
  return atual;
}

/**
 * Investe em bocas quando há caixa folgada (acima da reserva + um colchão),
 * priorizando o bairro de maior valor ainda abaixo do teto de produção.
 */
function construirBocaSePossivel(state: GameState, faccaoId: string, cfg: ConfigArquetipo): GameState {
  const fac = faccaoDe(state, faccaoId);
  if (!fac) return state;
  // Colchão de segurança: só investe em boca se sobra bem acima da reserva.
  if (fac.caixa - cfg.reservaCaixa < CUSTO_BOCA + 200) return state;

  const alvo = bairrosDaFaccao(state, faccaoId)
    .filter((b) => b.producao < MAX_BOCA_NIVEL)
    .sort((a, b) => b.valorBase - a.valorBase)[0];
  if (!alvo) return state;

  const r = construirBoca(state, faccaoId, alvo.id);
  return r.ok ? r.state : state;
}

/** Contrata advogado quando o calor está no vermelho e sobra caixa acima da reserva. */
function advogadoSePossivel(state: GameState, faccaoId: string, cfg: ConfigArquetipo): GameState {
  const fac = faccaoDe(state, faccaoId);
  if (!fac) return state;
  if (fac.calor >= CALOR_LIMIAR_BATIDA && fac.caixa - cfg.reservaCaixa >= CUSTO_ADVOGADO) {
    const r = contratarAdvogado(state, faccaoId);
    if (r.ok) return r.state;
  }
  return state;
}

/** Reforça a fronteira: junta soldados ociosos no bairro que faz frente ao melhor alvo. */
function reforcar(state: GameState, faccaoId: string): GameState {
  const alvos = alvosPossiveis(state, faccaoId);
  if (alvos.length === 0) return state;

  // Bairro próprio que faz fronteira com algum alvo.
  const idsAlvos = new Set(alvos.map((a) => a.id));
  const fronteira = bairrosDaFaccao(state, faccaoId).find((b) =>
    b.conexoes.some((c) => idsAlvos.has(c)),
  );
  if (!fronteira) return state;

  let atual = state;
  const fac = faccaoDe(atual, faccaoId);
  if (!fac) return atual;

  for (const s of fac.soldados) {
    if (s.status !== 'ativo' && s.status !== 'ferido') continue;
    if (s.bairroId === fronteira.id) continue;
    // Só move se o bairro atual é vizinho da fronteira (1 passo).
    const bairro = bairrosDaFaccao(atual, faccaoId).find((b) => b.id === s.bairroId);
    if (bairro && bairro.conexoes.includes(fronteira.id)) {
      const r = moverSoldado(atual, s.id, fronteira.id);
      if (r.ok) atual = r.state;
    }
  }
  return atual;
}

/** Executa o turno completo de uma facção IA. Devolve novo estado. */
export function executarTurnoIA(state: GameState, faccaoId: string, rng: Rng = Math.random): GameState {
  const fac = faccaoDe(state, faccaoId);
  if (!fac || fac.tipo !== 'ia') return state;
  const cfg = CONFIG[fac.arquetipo ?? 'agressivo'];

  // 1. Economia: arma o esquadrão, recruta reforços, investe em bocas e esfria o calor.
  let atual = comprarSePossivel(state, faccaoId, cfg);
  atual = recrutarSePossivel(atual, faccaoId, cfg, rng);
  atual = construirBocaSePossivel(atual, faccaoId, cfg);
  atual = advogadoSePossivel(atual, faccaoId, cfg);

  // 2. Escolhe o melhor alvo (maior razão ponderada de vitória).
  const alvos = alvosPossiveis(atual, faccaoId);
  let melhorAlvo: { id: string; razao: number } | null = null;
  for (const alvo of alvos) {
    const ataque = forcaDeAtaque(atual, faccaoId, alvo.id).poder;
    if (ataque <= 0) continue;
    const defesa = Math.max(1, defesaEstimada(atual, alvo.id));
    const peso = alvo.dono === null ? cfg.pesoNeutro : cfg.pesoJogador;
    const razao = (ataque / defesa) * peso;
    if (!melhorAlvo || razao > melhorAlvo.razao) melhorAlvo = { id: alvo.id, razao };
  }

  // 3. Ataca se a razão bate o limiar; senão reforça a fronteira.
  if (melhorAlvo && melhorAlvo.razao >= cfg.razaoAtaque) {
    // Briga apertada + caixa sobrando: espiona antes pra ganhar bônus.
    const facAtual = faccaoDe(atual, faccaoId);
    if (
      facAtual &&
      melhorAlvo.razao < 1.15 &&
      facAtual.caixa - cfg.reservaCaixa >= CUSTO_ESPIONAGEM
    ) {
      const rEsp = espionarBairro(atual, faccaoId, melhorAlvo.id);
      if (rEsp.ok) atual = rEsp.state;
    }
    const r = atacarBairro(atual, faccaoId, melhorAlvo.id, rng);
    if (r.ok) atual = r.state;
  } else {
    atual = reforcar(atual, faccaoId);
  }

  return atual;
}
