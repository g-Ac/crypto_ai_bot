/**
 * Checagem de vitória/derrota (doc, seção 4.5): dominar todos os bairros vence;
 * perder todo território (sem tropas de pé pra revidar) perde.
 */

import { participaDeCombate } from './combat';
import { bairrosDaFaccao } from './selectors';
import type { GameState, StatusPartida } from '../types/game';

export function avaliarStatus(state: GameState): StatusPartida {
  const totalBairros = state.cidade.bairros.length;
  const doJogador = bairrosDaFaccao(state, state.jogadorId).length;

  if (doJogador === totalBairros) return 'vitoria';

  const jogador = state.faccoes.find((f) => f.id === state.jogadorId);
  const tropasDePe = jogador?.soldados.some(participaDeCombate) ?? false;

  // Sem território e sem tropas de pé = acabou.
  if (doJogador === 0 && !tropasDePe) return 'derrota';

  return 'em_andamento';
}
