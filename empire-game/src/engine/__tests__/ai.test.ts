import { executarTurnoIA } from '../ai';
import { faccaoDe } from '../selectors';
import { criarPartida, IA_ID, JOGADOR_ID } from '../../data/seed';
import { rngSeed } from './helpers';

describe('executarTurnoIA', () => {
  it('a IA agressiva investe a caixa (arma ou recruta) no seu turno', () => {
    const g = criarPartida();
    const caixaAntes = faccaoDe(g, IA_ID)!.caixa;

    const depois = executarTurnoIA(g, IA_ID, rngSeed(1));

    // Economia ativa: a IA gasta parte da caixa (upgrade de arma e/ou recruta).
    expect(faccaoDe(depois, IA_ID)!.caixa).toBeLessThan(caixaAntes);
  });

  it('recruta reforço quando o arsenal já está no talo', () => {
    const g = criarPartida();
    // Todos os soldados da IA com fuzil => nenhum upgrade de arma disponível.
    for (const s of faccaoDe(g, IA_ID)!.soldados) s.armaId = 'fuzil';
    const soldadosAntes = faccaoDe(g, IA_ID)!.soldados.length;

    const depois = executarTurnoIA(g, IA_ID, rngSeed(3));
    // caixa 500 >= custo de recruta (450): entra reforço.
    expect(faccaoDe(depois, IA_ID)!.soldados.length).toBeGreaterThan(soldadosAntes);
  });

  it('ignora facção que não é IA (guard)', () => {
    const g = criarPartida();
    const antes = JSON.stringify(g);
    const depois = executarTurnoIA(g, JOGADOR_ID, rngSeed(1));
    expect(JSON.stringify(depois)).toBe(antes);
  });

  it('não muta o estado original', () => {
    const g = criarPartida();
    const antes = JSON.stringify(g);
    executarTurnoIA(g, IA_ID, rngSeed(2));
    expect(JSON.stringify(g)).toBe(antes);
  });
});
