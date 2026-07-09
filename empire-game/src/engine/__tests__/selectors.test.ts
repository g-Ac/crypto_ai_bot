import {
  alvosPossiveis,
  bairrosDaFaccao,
  defesaEstimada,
  destinosDeMovimento,
  forcaDeAtaque,
} from '../selectors';
import { B_MORRO, B_VILA, criarPartida, JOGADOR_ID } from '../../data/seed';

describe('selectors', () => {
  it('bairrosDaFaccao lista só o território do jogador', () => {
    const g = criarPartida();
    const bs = bairrosDaFaccao(g, JOGADOR_ID);
    expect(bs.map((b) => b.id)).toEqual(['beco-do-sol']);
  });

  it('alvosPossiveis do jogador é a Vila adjacente (não o Morro distante)', () => {
    const g = criarPartida();
    const ids = alvosPossiveis(g, JOGADOR_ID).map((b) => b.id);
    expect(ids).toContain(B_VILA);
    expect(ids).not.toContain(B_MORRO);
  });

  it('forcaDeAtaque reúne as tropas de bairros próprios adjacentes ao alvo', () => {
    const g = criarPartida();
    const contraVila = forcaDeAtaque(g, JOGADOR_ID, B_VILA);
    expect(contraVila.atacantes.length).toBe(3);
    expect(contraVila.poder).toBeGreaterThan(0);

    const contraMorro = forcaDeAtaque(g, JOGADOR_ID, B_MORRO);
    expect(contraMorro.atacantes.length).toBe(0);
  });

  it('defesaEstimada de bairro neutro reflete a guarnição local', () => {
    const g = criarPartida();
    expect(defesaEstimada(g, B_VILA)).toBeGreaterThan(0);
  });

  it('destinosDeMovimento só inclui bairros próprios adjacentes', () => {
    const g = criarPartida();
    const p1 = g.faccoes.find((f) => f.id === JOGADOR_ID)!.soldados[0];
    // Inicialmente Beco não tem vizinho próprio.
    expect(destinosDeMovimento(g, p1)).toEqual([]);
    // Dá Vila ao jogador e o destino aparece.
    g.cidade.bairros.find((b) => b.id === B_VILA)!.dono = JOGADOR_ID;
    expect(destinosDeMovimento(g, p1).map((b) => b.id)).toEqual([B_VILA]);
  });
});
