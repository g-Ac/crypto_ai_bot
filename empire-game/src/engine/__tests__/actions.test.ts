import {
  aplicarRenda,
  atacarBairro,
  clonar,
  comprarArma,
  moverSoldado,
  recrutarSoldado,
} from '../actions';
import {
  bairrosDaFaccao,
  faccaoDe,
} from '../selectors';
import {
  B_BECO,
  B_MORRO,
  B_VILA,
  CUSTO_RECRUTA,
  criarPartida,
  JOGADOR_ID,
} from '../../data/seed';
import { rngSeed } from './helpers';

describe('moverSoldado', () => {
  it('move pra bairro próprio adjacente', () => {
    const g = criarPartida();
    // Dá Vila ao jogador pra ter destino próprio adjacente a Beco.
    g.cidade.bairros.find((b) => b.id === B_VILA)!.dono = JOGADOR_ID;
    const r = moverSoldado(g, 'p1', B_VILA);
    expect(r.ok).toBe(true);
    const p1 = faccaoDe(r.state, JOGADOR_ID)!.soldados.find((s) => s.id === 'p1')!;
    expect(p1.bairroId).toBe(B_VILA);
  });

  it('recusa mover pra bairro que não é seu', () => {
    const g = criarPartida();
    const r = moverSoldado(g, 'p1', B_VILA); // Vila é neutra
    expect(r.ok).toBe(false);
  });

  it('não muta o estado original', () => {
    const g = criarPartida();
    g.cidade.bairros.find((b) => b.id === B_VILA)!.dono = JOGADOR_ID;
    const antes = JSON.stringify(g);
    moverSoldado(g, 'p1', B_VILA);
    expect(JSON.stringify(g)).toBe(antes);
  });
});

describe('comprarArma', () => {
  it('desconta a caixa e equipa a arma', () => {
    const g = criarPartida(); // caixa 500
    const r = comprarArma(g, JOGADOR_ID, 'pistola', 'p3'); // p3 tem faca
    expect(r.ok).toBe(true);
    const fac = faccaoDe(r.state, JOGADOR_ID)!;
    expect(fac.caixa).toBe(200);
    expect(fac.soldados.find((s) => s.id === 'p3')!.armaId).toBe('pistola');
  });

  it('recusa quando não há caixa', () => {
    const g = criarPartida();
    const r = comprarArma(g, JOGADOR_ID, 'fuzil', 'p3'); // fuzil 1500 > 500
    expect(r.ok).toBe(false);
  });

  it('recusa arma já equipada', () => {
    const g = criarPartida();
    const r = comprarArma(g, JOGADOR_ID, 'pistola', 'p1'); // p1 já tem pistola
    expect(r.ok).toBe(false);
  });
});

describe('recrutarSoldado', () => {
  it('adiciona soldado e desconta o custo em bairro próprio', () => {
    const g = criarPartida();
    const antes = faccaoDe(g, JOGADOR_ID)!.soldados.length;
    const r = recrutarSoldado(g, JOGADOR_ID, B_BECO, rngSeed(1));
    expect(r.ok).toBe(true);
    const fac = faccaoDe(r.state, JOGADOR_ID)!;
    expect(fac.soldados.length).toBe(antes + 1);
    expect(fac.caixa).toBe(500 - CUSTO_RECRUTA);
    const novo = fac.soldados[fac.soldados.length - 1];
    expect(novo.bairroId).toBe(B_BECO);
    expect(novo.status).toBe('ativo');
  });

  it('recusa recrutar em bairro que não é seu', () => {
    const g = criarPartida();
    const r = recrutarSoldado(g, JOGADOR_ID, B_VILA, rngSeed(1));
    expect(r.ok).toBe(false);
  });

  it('recusa sem caixa suficiente', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.caixa = 100;
    const r = recrutarSoldado(g, JOGADOR_ID, B_BECO, rngSeed(1));
    expect(r.ok).toBe(false);
  });
});

describe('atacarBairro', () => {
  it('recusa quando não há tropa em bairro vizinho', () => {
    const g = criarPartida(); // jogador só tem Beco, não vizinho de Morro
    const r = atacarBairro(g, JOGADOR_ID, B_MORRO, rngSeed(1));
    expect(r.ok).toBe(false);
  });

  it('conquista bairro neutro fraco e move sobreviventes pra dentro', () => {
    const g = criarPartida(); // 3 soldados no Beco atacam Vila neutra
    const r = atacarBairro(g, JOGADOR_ID, B_VILA, rngSeed(1));
    expect(r.ok).toBe(true);
    const vila = r.state.cidade.bairros.find((b) => b.id === B_VILA)!;
    expect(vila.dono).toBe(JOGADOR_ID);
    // Pelo menos um soldado sobrevivente ocupou Vila.
    const naVila = faccaoDe(r.state, JOGADOR_ID)!.soldados.filter(
      (s) => s.bairroId === B_VILA && (s.status === 'ativo' || s.status === 'ferido'),
    );
    expect(naVila.length).toBeGreaterThan(0);
  });
});

describe('aplicarRenda', () => {
  it('aumenta a caixa das facções e decai o calor (sem bocas)', () => {
    const g = clonar(criarPartida());
    // Zera a produção pra isolar o decaimento base de calor.
    for (const b of bairrosDaFaccao(g, JOGADOR_ID)) b.producao = 0;
    const fac = faccaoDe(g, JOGADOR_ID)!;
    fac.calor = 20;
    const caixaAntes = fac.caixa;
    aplicarRenda(g);
    const depois = faccaoDe(g, JOGADOR_ID)!;
    expect(depois.caixa).toBeGreaterThan(caixaAntes);
    expect(depois.calor).toBe(17); // decaimento de 3
  });

  it('sem territórios não há renda', () => {
    const g = clonar(criarPartida());
    // Tira todos os bairros do jogador.
    for (const b of bairrosDaFaccao(g, JOGADOR_ID)) b.dono = null;
    const fac = faccaoDe(g, JOGADOR_ID)!;
    const caixaAntes = fac.caixa;
    aplicarRenda(g);
    expect(faccaoDe(g, JOGADOR_ID)!.caixa).toBe(caixaAntes);
  });
});
