/**
 * Seletores puros sobre GameState. Sem mutação — só leitura e derivação.
 * Compartilhados entre UI, IA e resolução de ações.
 */

import {
  garrisonNeutro,
  INICIATIVA_ATAQUE,
  participaDeCombate,
  poderEfetivo,
  VANTAGEM_CASA,
} from './combat';
import type { Arma, Bairro, Faccao, GameState, Soldado } from '../types/game';

export function faccaoDe(state: GameState, faccaoId: string): Faccao | undefined {
  return state.faccoes.find((f) => f.id === faccaoId);
}

export function jogador(state: GameState): Faccao {
  const f = faccaoDe(state, state.jogadorId);
  if (!f) throw new Error('Facção do jogador não encontrada no estado.');
  return f;
}

export function iasDe(state: GameState): Faccao[] {
  return state.faccoes.filter((f) => f.tipo === 'ia');
}

export function bairroDe(state: GameState, bairroId: string): Bairro | undefined {
  return state.cidade.bairros.find((b) => b.id === bairroId);
}

export function armasMap(state: GameState): Map<string, Arma> {
  return new Map(state.armas.map((a) => [a.id, a]));
}

export function armaDe(state: GameState, armaId: string | null): Arma | undefined {
  if (!armaId) return undefined;
  return state.armas.find((a) => a.id === armaId);
}

export function bairrosDaFaccao(state: GameState, faccaoId: string): Bairro[] {
  return state.cidade.bairros.filter((b) => b.dono === faccaoId);
}

/** Soldados de uma facção que estão num bairro específico. */
export function soldadosNoBairro(state: GameState, faccaoId: string, bairroId: string): Soldado[] {
  const f = faccaoDe(state, faccaoId);
  if (!f) return [];
  return f.soldados.filter((s) => s.bairroId === bairroId);
}

/** Todos os soldados de pé (ativo/ferido) posicionados num bairro, de qualquer facção. */
export function defensoresDoBairro(state: GameState, bairroId: string): Soldado[] {
  const b = bairroDe(state, bairroId);
  if (!b || !b.dono) return [];
  return soldadosNoBairro(state, b.dono, bairroId).filter(participaDeCombate);
}

/**
 * Força de ataque que `faccaoId` consegue projetar sobre `alvoId`: soma do poder
 * dos soldados de pé em bairros próprios adjacentes ao alvo.
 */
export function forcaDeAtaque(state: GameState, faccaoId: string, alvoId: string): {
  atacantes: Soldado[];
  poder: number;
} {
  const alvo = bairroDe(state, alvoId);
  const armas = armasMap(state);
  if (!alvo) return { atacantes: [], poder: 0 };

  const f = faccaoDe(state, faccaoId);
  if (!f) return { atacantes: [], poder: 0 };

  const bairrosProprios = new Set(bairrosDaFaccao(state, faccaoId).map((b) => b.id));
  const atacantes = f.soldados.filter(
    (s) =>
      participaDeCombate(s) &&
      bairrosProprios.has(s.bairroId) &&
      alvo.conexoes.includes(s.bairroId),
  );
  const poder = atacantes.reduce(
    (acc, s) => acc + poderEfetivo(s, s.armaId ? armas.get(s.armaId) : undefined),
    0,
  );
  return { atacantes, poder };
}

/** Ataque estimado (com bônus de iniciativa) pra exibir no preview de combate. */
export function ataqueEstimado(state: GameState, faccaoId: string, alvoId: string): number {
  return Math.round(forcaDeAtaque(state, faccaoId, alvoId).poder * INICIATIVA_ATAQUE);
}

/** Defesa estimada de um bairro (soma do poder dos defensores + guarnição neutra). */
export function defesaEstimada(state: GameState, alvoId: string): number {
  const alvo = bairroDe(state, alvoId);
  if (!alvo) return 0;
  const armas = armasMap(state);
  const defensores = defensoresDoBairro(state, alvoId);
  const somaDefesa = defensores.reduce(
    (acc, s) => acc + poderEfetivo(s, s.armaId ? armas.get(s.armaId) : undefined),
    0,
  );
  const garrison = defensores.length === 0 ? garrisonNeutro(alvo.risco) : 0;
  return Math.round(somaDefesa * VANTAGEM_CASA + garrison);
}

/** Bairros que `faccaoId` pode atacar (adjacentes a território próprio, não próprios). */
export function alvosPossiveis(state: GameState, faccaoId: string): Bairro[] {
  const proprios = bairrosDaFaccao(state, faccaoId);
  const idsProprios = new Set(proprios.map((b) => b.id));
  const alvos = new Map<string, Bairro>();
  for (const b of proprios) {
    for (const vizinhoId of b.conexoes) {
      if (idsProprios.has(vizinhoId)) continue;
      const vizinho = bairroDe(state, vizinhoId);
      if (vizinho) alvos.set(vizinho.id, vizinho);
    }
  }
  return [...alvos.values()];
}

/** Destinos válidos pra mover um soldado: bairros próprios adjacentes ao atual. */
export function destinosDeMovimento(state: GameState, soldado: Soldado): Bairro[] {
  const atual = bairroDe(state, soldado.bairroId);
  if (!atual) return [];
  return atual.conexoes
    .map((id) => bairroDe(state, id))
    .filter((b): b is Bairro => !!b && b.dono === soldado.faccaoId);
}
