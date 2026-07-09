import {
  aplicarBatidaPolicial,
  contratarAdvogado,
  espionarBairro,
  limparIntelExpirado,
} from '../actions';
import { ataqueEstimado, faccaoDe, temIntel } from '../selectors';
import { participaDeCombate } from '../combat';
import {
  B_BECO,
  B_MORRO,
  B_VILA,
  CUSTO_ADVOGADO,
  CUSTO_ESPIONAGEM,
  criarPartida,
  JOGADOR_ID,
} from '../../data/seed';
import { rngFixo } from './helpers';

describe('espionarBairro', () => {
  it('gera intel sobre bairro de fronteira, cobra caixa e sobe o calor', () => {
    const g = criarPartida();
    const r = espionarBairro(g, JOGADOR_ID, B_VILA);
    expect(r.ok).toBe(true);
    const fac = faccaoDe(r.state, JOGADOR_ID)!;
    expect(fac.caixa).toBe(500 - CUSTO_ESPIONAGEM);
    expect(fac.calor).toBeGreaterThan(0);
    expect(temIntel(r.state, JOGADOR_ID, B_VILA)).toBe(true);
  });

  it('intel aumenta o ataque estimado', () => {
    const g = criarPartida();
    const antes = ataqueEstimado(g, JOGADOR_ID, B_VILA);
    const r = espionarBairro(g, JOGADOR_ID, B_VILA);
    const depois = ataqueEstimado(r.state, JOGADOR_ID, B_VILA);
    expect(depois).toBeGreaterThan(antes);
  });

  it('recusa espionar bairro próprio ou fora da fronteira', () => {
    const g = criarPartida();
    expect(espionarBairro(g, JOGADOR_ID, B_BECO).ok).toBe(false);
    expect(espionarBairro(g, JOGADOR_ID, B_MORRO).ok).toBe(false);
  });
});

describe('contratarAdvogado', () => {
  it('reduz o calor e cobra a caixa', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.calor = 30;
    const r = contratarAdvogado(g, JOGADOR_ID);
    expect(r.ok).toBe(true);
    const fac = faccaoDe(r.state, JOGADOR_ID)!;
    expect(fac.calor).toBeLessThan(30);
    expect(fac.caixa).toBe(500 - CUSTO_ADVOGADO);
  });

  it('recusa quando o calor já está zerado', () => {
    const g = criarPartida();
    expect(contratarAdvogado(g, JOGADOR_ID).ok).toBe(false);
  });
});

describe('aplicarBatidaPolicial', () => {
  it('não faz nada com calor abaixo do limiar', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.calor = 10;
    const antes = JSON.stringify(g);
    aplicarBatidaPolicial(g, rngFixo(0));
    expect(JSON.stringify(g)).toBe(antes);
  });

  it('prende um soldado e esfria o calor quando o calor é alto', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.calor = 100;
    aplicarBatidaPolicial(g, rngFixo(0)); // roll 0 < chance => acontece
    const fac = faccaoDe(g, JOGADOR_ID)!;
    expect(fac.soldados.some((s) => s.status === 'preso')).toBe(true);
    expect(fac.calor).toBeLessThan(100);
  });

  it('não prende ninguém quando o roll passa da chance', () => {
    const g = criarPartida();
    faccaoDe(g, JOGADOR_ID)!.calor = 60;
    aplicarBatidaPolicial(g, rngFixo(0.99)); // roll alto => sem batida
    expect(faccaoDe(g, JOGADOR_ID)!.soldados.every(participaDeCombate)).toBe(true);
  });
});

describe('limparIntelExpirado', () => {
  it('remove marcadores expirados e mantém os válidos', () => {
    const g = criarPartida();
    g.intel = [
      { faccaoId: JOGADOR_ID, bairroId: B_VILA, expiraTurno: 1 },
      { faccaoId: JOGADOR_ID, bairroId: B_MORRO, expiraTurno: 5 },
    ];
    g.turno.numero = 3;
    limparIntelExpirado(g);
    expect(g.intel).toHaveLength(1);
    expect(g.intel[0].bairroId).toBe(B_MORRO);
  });
});
