/**
 * Ações mutadoras da partida. Cada função clona o estado, aplica a mudança e
 * devolve um novo GameState — nunca muta o argumento. Reusadas pelo jogador
 * (via store) e pela IA.
 */

import { FATOR_RENDA } from '../data/seed';
import { resolverCombate, type Baixa, type Rng } from './combat';
import {
  armaDe,
  armasMap,
  bairroDe,
  bairrosDaFaccao,
  defensoresDoBairro,
  destinosDeMovimento,
  faccaoDe,
  forcaDeAtaque,
} from './selectors';
import type { GameState, LogTipo, Soldado } from '../types/game';

export interface ResultadoAcao {
  state: GameState;
  ok: boolean;
  mensagem: string;
}

/** Clone profundo — GameState é puro JSON, então isto é seguro e barato (estado pequeno). */
export function clonar(state: GameState): GameState {
  return JSON.parse(JSON.stringify(state)) as GameState;
}

export function addLog(state: GameState, tipo: LogTipo, texto: string): void {
  state.log.push({ id: state.logSeq, turno: state.turno.numero, tipo, texto });
  state.logSeq += 1;
  // Mantém o log enxuto (últimos 60 eventos) — Expo Go / device com pouca RAM.
  if (state.log.length > 60) state.log = state.log.slice(-60);
}

function encontrarSoldado(state: GameState, soldadoId: string): Soldado | undefined {
  for (const f of state.faccoes) {
    const s = f.soldados.find((x) => x.id === soldadoId);
    if (s) return s;
  }
  return undefined;
}

function aplicarBaixas(state: GameState, baixas: Baixa[]): void {
  for (const b of baixas) {
    const s = encontrarSoldado(state, b.soldadoId);
    if (s) s.status = b.status;
  }
}

/** Move um soldado pra um bairro próprio adjacente. */
export function moverSoldado(
  state: GameState,
  soldadoId: string,
  destinoId: string,
): ResultadoAcao {
  const novo = clonar(state);
  const s = encontrarSoldado(novo, soldadoId);
  if (!s) return { state, ok: false, mensagem: 'Soldado não encontrado.' };
  if (s.status !== 'ativo' && s.status !== 'ferido') {
    return { state, ok: false, mensagem: `${s.nome} não pode se mover (${s.status}).` };
  }
  const destinos = destinosDeMovimento(novo, s);
  const destino = destinos.find((b) => b.id === destinoId);
  if (!destino) {
    return { state, ok: false, mensagem: 'Destino inválido (precisa ser bairro seu e vizinho).' };
  }
  const origem = bairroDe(novo, s.bairroId);
  s.bairroId = destinoId;
  addLog(novo, 'info', `${s.nome} moveu de ${origem?.nome ?? '?'} pra ${destino.nome}.`);
  return { state: novo, ok: true, mensagem: `${s.nome} → ${destino.nome}` };
}

/** Compra e equipa uma arma num soldado da facção. */
export function comprarArma(
  state: GameState,
  faccaoId: string,
  armaId: string,
  soldadoId: string,
): ResultadoAcao {
  const novo = clonar(state);
  const fac = faccaoDe(novo, faccaoId);
  const arma = armaDe(novo, armaId);
  const s = encontrarSoldado(novo, soldadoId);
  if (!fac) return { state, ok: false, mensagem: 'Facção inválida.' };
  if (!arma) return { state, ok: false, mensagem: 'Arma inválida.' };
  if (!s || s.faccaoId !== faccaoId) {
    return { state, ok: false, mensagem: 'Soldado inválido pra essa facção.' };
  }
  if (s.status === 'morto' || s.status === 'preso') {
    return { state, ok: false, mensagem: `${s.nome} não pode ser armado (${s.status}).` };
  }
  if (!arma.cidadesDisponiveis.includes(novo.cidade.id)) {
    return { state, ok: false, mensagem: `${arma.nome} não está disponível aqui.` };
  }
  if (s.armaId === armaId) {
    return { state, ok: false, mensagem: `${s.nome} já usa ${arma.nome}.` };
  }
  if (fac.caixa < arma.custo) {
    return { state, ok: false, mensagem: `Caixa insuficiente pra ${arma.nome} ($${arma.custo}).` };
  }
  fac.caixa -= arma.custo;
  s.armaId = armaId;
  addLog(novo, 'info', `${fac.nome} armou ${s.nome} com ${arma.nome} (-$${arma.custo}).`);
  return { state: novo, ok: true, mensagem: `${s.nome} equipou ${arma.nome}.` };
}

/** Ataca um bairro adjacente ao território da facção. */
export function atacarBairro(
  state: GameState,
  faccaoId: string,
  alvoId: string,
  rng: Rng = Math.random,
): ResultadoAcao {
  const novo = clonar(state);
  const fac = faccaoDe(novo, faccaoId);
  const alvo = bairroDe(novo, alvoId);
  if (!fac || !alvo) return { state, ok: false, mensagem: 'Alvo inválido.' };
  if (alvo.dono === faccaoId) {
    return { state, ok: false, mensagem: 'Esse bairro já é seu.' };
  }

  const { atacantes } = forcaDeAtaque(novo, faccaoId, alvoId);
  if (atacantes.length === 0) {
    return { state, ok: false, mensagem: 'Sem tropas em bairro vizinho pra atacar.' };
  }
  const defensores = defensoresDoBairro(novo, alvoId);

  const resultado = resolverCombate(atacantes, defensores, alvo, armasMap(novo), rng);
  aplicarBaixas(novo, resultado.baixasAtacante);
  aplicarBaixas(novo, resultado.baixasDefensor);

  const donoAntigo = alvo.dono ? faccaoDe(novo, alvo.dono) : undefined;
  const nBaixas = resultado.baixasAtacante.length + resultado.baixasDefensor.length;

  addLog(
    novo,
    'combate',
    `${fac.nome} atacou ${alvo.nome} — ataque ${resultado.forcaAtaque} vs defesa ${resultado.forcaDefesa}.`,
  );

  if (resultado.vencedor === 'atacante') {
    alvo.dono = faccaoId;
    // Sobreviventes ocupam o bairro conquistado.
    for (const a of atacantes) {
      if (a.status === 'ativo' || a.status === 'ferido') a.bairroId = alvoId;
    }
    fac.respeito += 10 + Math.round(alvo.valorBase / 100);
    fac.calor = Math.min(100, fac.calor + 8);
    const de = donoAntigo ? ` (tomado de ${donoAntigo.nome})` : '';
    addLog(novo, 'combate', `${fac.nome} DOMINOU ${alvo.nome}${de}. ${nBaixas} baixa(s).`);
    return { state: novo, ok: true, mensagem: `Você dominou ${alvo.nome}!` };
  }

  fac.calor = Math.min(100, fac.calor + 4);
  addLog(novo, 'combate', `${fac.nome} foi repelido em ${alvo.nome}. ${nBaixas} baixa(s).`);
  return { state: novo, ok: true, mensagem: `Ataque a ${alvo.nome} repelido.` };
}

/** Renda por turno + leve decaimento de calor. Muta o estado passado (usar em clone). */
export function aplicarRenda(state: GameState): void {
  for (const fac of state.faccoes) {
    const total = bairrosDaFaccao(state, fac.id).reduce((acc, b) => acc + b.valorBase, 0);
    const renda = Math.round(total * FATOR_RENDA);
    if (renda > 0) {
      fac.caixa += renda;
      if (fac.tipo === 'jogador') {
        addLog(state, 'renda', `Renda dos territórios: +$${renda}.`);
      }
    }
    fac.calor = Math.max(0, fac.calor - 3);
  }
}
