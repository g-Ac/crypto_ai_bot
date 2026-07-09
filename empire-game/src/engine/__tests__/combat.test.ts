import {
  garrisonNeutro,
  participaDeCombate,
  poderEfetivo,
  resolverCombate,
} from '../combat';
import { arma, bairro, rngSeed, soldado } from './helpers';

describe('poderEfetivo', () => {
  const pistola = arma({ id: 'pistola', dano: 5 });

  it('soma força + dano da arma com modificador de traço ganancioso (1.0)', () => {
    const s = soldado({ forca: 10, armaId: 'pistola', traco: 'ganancioso' });
    expect(poderEfetivo(s, pistola)).toBeCloseTo(15);
  });

  it('aplica bônus do traço leal (1.1) e penalidade do covarde (0.85)', () => {
    const leal = soldado({ forca: 10, armaId: 'pistola', traco: 'leal' });
    const covarde = soldado({ forca: 10, armaId: 'pistola', traco: 'covarde' });
    expect(poderEfetivo(leal, pistola)).toBeCloseTo(16.5);
    expect(poderEfetivo(covarde, pistola)).toBeCloseTo(12.75);
  });

  it('conta metade do poder quando ferido', () => {
    const s = soldado({ forca: 10, armaId: 'pistola', traco: 'ganancioso', status: 'ferido' });
    expect(poderEfetivo(s, pistola)).toBeCloseTo(7.5);
  });

  it('sem arma usa só a força', () => {
    const s = soldado({ forca: 10, armaId: null, traco: 'ganancioso' });
    expect(poderEfetivo(s, undefined)).toBeCloseTo(10);
  });

  it('morto e preso não contribuem', () => {
    expect(poderEfetivo(soldado({ status: 'morto' }), pistola)).toBe(0);
    expect(poderEfetivo(soldado({ status: 'preso' }), pistola)).toBe(0);
  });
});

describe('participaDeCombate', () => {
  it('só ativo e ferido participam', () => {
    expect(participaDeCombate(soldado({ status: 'ativo' }))).toBe(true);
    expect(participaDeCombate(soldado({ status: 'ferido' }))).toBe(true);
    expect(participaDeCombate(soldado({ status: 'morto' }))).toBe(false);
    expect(participaDeCombate(soldado({ status: 'preso' }))).toBe(false);
  });
});

describe('garrisonNeutro', () => {
  it('escala com o risco do bairro', () => {
    expect(garrisonNeutro(0)).toBeCloseTo(8);
    expect(garrisonNeutro(45)).toBeCloseTo(17);
  });
});

describe('resolverCombate', () => {
  const armas = new Map([['fuzil', arma({ id: 'fuzil', dano: 15 })]]);

  it('atacante muito superior vence e o defensor sofre baixas', () => {
    const atacantes = [
      soldado({ id: 'a1', forca: 12, armaId: 'fuzil', faccaoId: 'A' }),
      soldado({ id: 'a2', forca: 12, armaId: 'fuzil', faccaoId: 'A' }),
      soldado({ id: 'a3', forca: 12, armaId: 'fuzil', faccaoId: 'A' }),
    ];
    const defensores = [soldado({ id: 'd1', forca: 4, armaId: null, faccaoId: 'B' })];
    const r = resolverCombate(atacantes, defensores, bairro({ dono: 'B' }), armas, rngSeed(1));
    expect(r.vencedor).toBe('atacante');
    expect(r.forcaAtaque).toBeGreaterThan(r.forcaDefesa);
    expect(r.baixasDefensor.length).toBeGreaterThan(0);
  });

  it('defensor muito superior repele o ataque', () => {
    const atacantes = [soldado({ id: 'a1', forca: 4, armaId: null, faccaoId: 'A' })];
    const defensores = [
      soldado({ id: 'd1', forca: 12, armaId: 'fuzil', faccaoId: 'B' }),
      soldado({ id: 'd2', forca: 12, armaId: 'fuzil', faccaoId: 'B' }),
      soldado({ id: 'd3', forca: 12, armaId: 'fuzil', faccaoId: 'B' }),
    ];
    const r = resolverCombate(atacantes, defensores, bairro({ dono: 'B' }), armas, rngSeed(2));
    expect(r.vencedor).toBe('defensor');
  });

  it('bairro neutro sem defensores ainda opõe uma guarnição', () => {
    const atacantes = [soldado({ id: 'a1', forca: 1, armaId: null, faccaoId: 'A' })];
    const r = resolverCombate(atacantes, [], bairro({ dono: null, risco: 90 }), armas, rngSeed(3));
    expect(r.forcaDefesa).toBeGreaterThan(0);
  });

  it('baixas referenciam apenas soldados que participaram', () => {
    const atacantes = [soldado({ id: 'a1', forca: 10, armaId: 'fuzil', faccaoId: 'A' })];
    const defensores = [soldado({ id: 'd1', forca: 10, armaId: 'fuzil', faccaoId: 'B' })];
    const ids = new Set(['a1', 'd1']);
    const r = resolverCombate(atacantes, defensores, bairro({ dono: 'B' }), armas, rngSeed(4));
    for (const b of [...r.baixasAtacante, ...r.baixasDefensor]) {
      expect(ids.has(b.soldadoId)).toBe(true);
    }
  });
});
