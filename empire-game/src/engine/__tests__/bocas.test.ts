import { aplicarRenda, atacarBairro, construirBoca } from '../actions';
import { bairroDe, faccaoDe } from '../selectors';
import {
  B_BECO,
  B_VILA,
  CALOR_POR_BOCA,
  CUSTO_BOCA,
  MAX_BOCA_NIVEL,
  RENDA_POR_BOCA,
  criarPartida,
  JOGADOR_ID,
} from '../../data/seed';
import { rngSeed } from './helpers';

describe('construirBoca', () => {
  it('sobe o nível de produção e desconta a caixa em bairro próprio', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.caixa = 1000;
    const nivelAntes = bairroDe(g, B_BECO)!.producao;
    const r = construirBoca(g, JOGADOR_ID, B_BECO);
    expect(r.ok).toBe(true);
    expect(bairroDe(r.state, B_BECO)!.producao).toBe(nivelAntes + 1);
    expect(faccaoDe(r.state, JOGADOR_ID)!.caixa).toBe(1000 - CUSTO_BOCA);
  });

  it('recusa acima do nível máximo', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.caixa = 100000;
    bairroDe(g, B_BECO)!.producao = MAX_BOCA_NIVEL;
    const r = construirBoca(g, JOGADOR_ID, B_BECO);
    expect(r.ok).toBe(false);
  });

  it('recusa em bairro que não é seu', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.caixa = 1000;
    const r = construirBoca(g, JOGADOR_ID, B_VILA); // Vila é neutra
    expect(r.ok).toBe(false);
  });

  it('recusa sem caixa suficiente', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.caixa = 100;
    const r = construirBoca(g, JOGADOR_ID, B_BECO);
    expect(r.ok).toBe(false);
  });
});

describe('renda e calor de produção', () => {
  it('produção adiciona renda por turno', () => {
    const g = criarPartida();
    const jog = faccaoDe(g, JOGADOR_ID)!;
    // Isola: só Beco do jogador, produção 2.
    bairroDe(g, B_BECO)!.producao = 2;
    const caixaAntes = jog.caixa;
    aplicarRenda(g);
    const ganho = faccaoDe(g, JOGADOR_ID)!.caixa - caixaAntes;
    expect(ganho).toBeGreaterThanOrEqual(2 * RENDA_POR_BOCA);
  });

  it('produção sobe o calor antes do decaimento', () => {
    const g = criarPartida();
    const jog = faccaoDe(g, JOGADOR_ID)!;
    jog.calor = 30;
    bairroDe(g, B_BECO)!.producao = 3; // única boca do jogador
    aplicarRenda(g);
    // 30 + 3*CALOR_POR_BOCA - 3 (decaimento)
    expect(faccaoDe(g, JOGADOR_ID)!.calor).toBe(30 + 3 * CALOR_POR_BOCA - 3);
  });
});

describe('conquista transfere a boca junto com o bairro', () => {
  it('quem toma o bairro herda a produção instalada', () => {
    const g = criarPartida();
    // Vila neutra com boca nível 2; jogador ataca do Beco.
    bairroDe(g, B_VILA)!.producao = 2;
    const r = atacarBairro(g, JOGADOR_ID, B_VILA, rngSeed(1));
    expect(r.ok).toBe(true);
    const vila = bairroDe(r.state, B_VILA)!;
    if (vila.dono === JOGADOR_ID) {
      expect(vila.producao).toBe(2); // infraestrutura permanece
    }
  });
});
