import { avaliarStatus } from '../victory';
import { bairrosDaFaccao, faccaoDe } from '../selectors';
import { criarPartida, JOGADOR_ID, IA_ID } from '../../data/seed';

describe('avaliarStatus', () => {
  it('em andamento na partida inicial', () => {
    expect(avaliarStatus(criarPartida())).toBe('em_andamento');
  });

  it('vitória quando o jogador domina todos os bairros', () => {
    const g = criarPartida();
    for (const b of g.cidade.bairros) b.dono = JOGADOR_ID;
    expect(avaliarStatus(g)).toBe('vitoria');
  });

  it('derrota quando o jogador perde território e todas as tropas', () => {
    const g = criarPartida();
    for (const b of bairrosDaFaccao(g, JOGADOR_ID)) b.dono = IA_ID;
    for (const s of faccaoDe(g, JOGADOR_ID)!.soldados) s.status = 'morto';
    expect(avaliarStatus(g)).toBe('derrota');
  });

  it('não é derrota se ainda há tropas de pé mesmo sem território', () => {
    const g = criarPartida();
    for (const b of bairrosDaFaccao(g, JOGADOR_ID)) b.dono = IA_ID;
    // soldados seguem ativos
    expect(avaliarStatus(g)).toBe('em_andamento');
  });
});
