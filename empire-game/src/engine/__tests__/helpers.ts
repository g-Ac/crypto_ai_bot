/** Utilitários compartilhados pelos testes do engine. */

import type { Arma, Bairro, Soldado } from '../../types/game';

/** PRNG determinístico (mulberry32) — combate reprodutível nos testes. */
export function rngSeed(seed: number): () => number {
  let a = seed;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** RNG fixo — sempre devolve o mesmo valor (útil pra forçar caminhos). */
export function rngFixo(valor: number): () => number {
  return () => valor;
}

export function soldado(over: Partial<Soldado> = {}): Soldado {
  return {
    id: 's1',
    nome: 'Teste',
    lealdade: 70,
    traco: 'ganancioso',
    forca: 10,
    armaId: null,
    status: 'ativo',
    faccaoId: 'f1',
    bairroId: 'b1',
    ...over,
  };
}

export function bairro(over: Partial<Bairro> = {}): Bairro {
  return {
    id: 'b1',
    nome: 'Bairro Teste',
    dono: null,
    valorBase: 1000,
    risco: 30,
    conexoes: [],
    ...over,
  };
}

export function arma(over: Partial<Arma> = {}): Arma {
  return {
    id: 'pistola',
    nome: 'Pistola',
    dano: 5,
    custo: 300,
    cidadesDisponiveis: ['zona-sul'],
    ...over,
  };
}
