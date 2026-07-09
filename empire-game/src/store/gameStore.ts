/**
 * Store global da partida (Zustand). Orquestra o loop de turno:
 *   decisão do jogador → resolução → fase da IA → renda → checagem de vitória.
 * Persiste automaticamente no AsyncStorage a cada mudança relevante.
 */

import { create } from 'zustand';
import { ACOES_POR_TURNO, criarPartida } from '../data/seed';
import {
  aplicarRenda,
  addLog,
  atacarBairro as atacarBairroEngine,
  clonar,
  comprarArma as comprarArmaEngine,
  moverSoldado as moverSoldadoEngine,
  recrutarSoldado as recrutarSoldadoEngine,
  type ResultadoAcao,
} from '../engine/actions';
import { executarTurnoIA } from '../engine/ai';
import { iasDe } from '../engine/selectors';
import { avaliarStatus } from '../engine/victory';
import { carregarJogo, salvarJogo } from '../storage/persistence';
import type { GameState } from '../types/game';

interface GameStore {
  game: GameState | null;
  /** Mensagem curta da última ação (sucesso ou erro) pra feedback na UI. */
  feedback: string | null;
  temSave: boolean;

  novoJogo: () => void;
  carregar: () => Promise<boolean>;
  verificarSave: () => Promise<void>;
  sairParaMenu: () => void;
  limparFeedback: () => void;

  moverSoldado: (soldadoId: string, destinoId: string) => void;
  comprarArma: (armaId: string, soldadoId: string) => void;
  recrutarSoldado: (bairroId: string) => void;
  atacarBairro: (alvoId: string) => void;
  passarTurno: () => void;
}

export const useGameStore = create<GameStore>((set, get) => {
  /** Aplica o resultado de uma ação do jogador, gastando uma ação se `custaAcao`. */
  function aplicar(resultado: ResultadoAcao, custaAcao: boolean): void {
    if (!resultado.ok) {
      set({ feedback: resultado.mensagem });
      return;
    }
    const novo = resultado.state;
    if (custaAcao) novo.turno.acoesRestantes = Math.max(0, novo.turno.acoesRestantes - 1);
    novo.status = avaliarStatus(novo);
    if (novo.status === 'vitoria') {
      addLog(novo, 'fim', 'Você dominou toda a Zona Sul. VITÓRIA.');
    }
    set({ game: novo, feedback: resultado.mensagem });
    void salvarJogo(novo);
  }

  return {
    game: null,
    feedback: null,
    temSave: false,

    novoJogo() {
      const game = criarPartida();
      set({ game, feedback: null, temSave: true });
      void salvarJogo(game);
    },

    async carregar() {
      const game = await carregarJogo();
      if (game) {
        set({ game, feedback: null, temSave: true });
        return true;
      }
      return false;
    },

    async verificarSave() {
      const game = await carregarJogo();
      set({ temSave: !!game });
    },

    sairParaMenu() {
      set({ game: null, feedback: null });
    },

    limparFeedback() {
      set({ feedback: null });
    },

    moverSoldado(soldadoId, destinoId) {
      const game = get().game;
      if (!game || game.status !== 'em_andamento') return;
      if (game.turno.acoesRestantes <= 0) {
        set({ feedback: 'Sem ações neste turno. Passe o turno.' });
        return;
      }
      aplicar(moverSoldadoEngine(game, soldadoId, destinoId), true);
    },

    comprarArma(armaId, soldadoId) {
      const game = get().game;
      if (!game || game.status !== 'em_andamento') return;
      // Compra é econômica (não gasta ação), só depende de caixa.
      aplicar(comprarArmaEngine(game, game.jogadorId, armaId, soldadoId), false);
    },

    recrutarSoldado(bairroId) {
      const game = get().game;
      if (!game || game.status !== 'em_andamento') return;
      // Recrutar é econômico (não gasta ação), só depende de caixa.
      aplicar(recrutarSoldadoEngine(game, game.jogadorId, bairroId), false);
    },

    atacarBairro(alvoId) {
      const game = get().game;
      if (!game || game.status !== 'em_andamento') return;
      if (game.turno.acoesRestantes <= 0) {
        set({ feedback: 'Sem ações neste turno. Passe o turno.' });
        return;
      }
      aplicar(atacarBairroEngine(game, game.jogadorId, alvoId), true);
    },

    passarTurno() {
      const game = get().game;
      if (!game || game.status !== 'em_andamento') return;

      let s: GameState = clonar(game);
      s.turno.fase = 'ia';

      // Fase da IA: cada rival age (funções retornam novos estados clonados).
      for (const ia of iasDe(s)) {
        s = executarTurnoIA(s, ia.id);
      }

      // Renda + decaimento de calor, depois virada de turno.
      aplicarRenda(s);
      s.turno.numero += 1;
      s.turno.acoesRestantes = ACOES_POR_TURNO;
      s.turno.fase = 'decisao';

      s.status = avaliarStatus(s);
      if (s.status === 'vitoria') {
        addLog(s, 'fim', 'Você dominou toda a Zona Sul. VITÓRIA.');
      } else if (s.status === 'derrota') {
        addLog(s, 'fim', 'Perdeu todo território e todas as tropas. DERROTA.');
      } else {
        addLog(s, 'ia', `— Relatório do turno ${s.turno.numero} —`);
      }

      set({ game: s, feedback: null });
      void salvarJogo(s);
    },
  };
});
