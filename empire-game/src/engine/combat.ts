/**
 * Combate simples (doc, seção 4.3): força total dos soldados + dano da arma
 * vs defesa, com fator aleatório. Soldados podem ficar feridos, mortos ou presos.
 *
 * Funções puras: recebem estado, devolvem resultado. RNG injetável pra testes.
 */

import type { Arma, Bairro, Soldado, SoldadoStatus, Traco } from '../types/game';

export type Rng = () => number;

/** Vantagem de território pra quem defende em casa. */
export const VANTAGEM_CASA = 1.05;

/**
 * Bônus de iniciativa de quem ataca — recompensa a ofensiva e evita o
 * empate frio (ninguém toma a casa do outro). Balanceamento de v1: um jogador
 * que concentra tropas e assalta vence ~47% vs a IA agressiva; passividade empata.
 */
export const INICIATIVA_ATAQUE = 1.2;

/**
 * Guarnição/milícia local que defende um bairro neutro (sem soldados de facção).
 * Escala com o risco do bairro — na mesma ordem de grandeza do poder de um
 * pequeno esquadrão, não do valorBase econômico.
 */
export function garrisonNeutro(risco: number): number {
  return 8 + risco * 0.2;
}

/** Modificador de poder por traço de personalidade. */
const MOD_TRACO: Record<Traco, number> = {
  leal: 1.1,
  ganancioso: 1.0,
  covarde: 0.85,
};

/** Só quem está de pé (ativo/ferido) participa e conta força. */
export function participaDeCombate(s: Soldado): boolean {
  return s.status === 'ativo' || s.status === 'ferido';
}

/** Poder efetivo de um soldado = (força + dano da arma) * traço * penalidade de ferimento. */
export function poderEfetivo(s: Soldado, arma: Arma | undefined): number {
  if (!participaDeCombate(s)) return 0;
  const base = s.forca + (arma?.dano ?? 0);
  const feridoPenalidade = s.status === 'ferido' ? 0.5 : 1;
  return base * MOD_TRACO[s.traco] * feridoPenalidade;
}

function entre(rng: Rng, min: number, max: number): number {
  return min + rng() * (max - min);
}

export interface Baixa {
  soldadoId: string;
  status: SoldadoStatus;
}

export interface ResultadoCombate {
  vencedor: 'atacante' | 'defensor';
  forcaAtaque: number;
  forcaDefesa: number;
  baixasAtacante: Baixa[];
  baixasDefensor: Baixa[];
}

/**
 * Aplica baixas a um lado. `pressao` (0-1) é a chance-base de cada soldado ser
 * atingido; `risco` (0-100) do bairro adiciona chance de prisão (batida policial).
 */
function calcularBaixas(
  soldados: Soldado[],
  pressao: number,
  risco: number,
  rng: Rng,
): Baixa[] {
  const baixas: Baixa[] = [];
  for (const s of soldados) {
    if (!participaDeCombate(s)) continue;

    if (rng() < pressao) {
      // Atingido. Se já estava ferido, não resiste de novo.
      let status: SoldadoStatus;
      if (s.status === 'ferido') {
        status = 'morto';
      } else {
        status = rng() < 0.4 ? 'morto' : 'ferido';
      }
      baixas.push({ soldadoId: s.id, status });
      continue;
    }

    // Não foi atingido no tiroteio, mas pode cair na batida policial.
    if (rng() < (risco / 100) * 0.2) {
      baixas.push({ soldadoId: s.id, status: 'preso' });
    }
  }
  return baixas;
}

/**
 * Resolve um confronto. `armas` mapeia armaId -> Arma pra lookup de dano.
 * Se `defensores` estiver vazio, o bairro neutro ainda oferece uma guarnição mínima.
 */
export function resolverCombate(
  atacantes: Soldado[],
  defensores: Soldado[],
  bairro: Bairro,
  armas: Map<string, Arma>,
  rng: Rng = Math.random,
): ResultadoCombate {
  const poder = (s: Soldado) => poderEfetivo(s, s.armaId ? armas.get(s.armaId) : undefined);

  const somaAtaque = atacantes.reduce((acc, s) => acc + poder(s), 0);
  const somaDefesa = defensores.reduce((acc, s) => acc + poder(s), 0);

  const garrison = defensores.length === 0 ? garrisonNeutro(bairro.risco) : 0;

  const forcaAtaque = somaAtaque * INICIATIVA_ATAQUE * entre(rng, 0.85, 1.15);
  const forcaDefesa = (somaDefesa * VANTAGEM_CASA + garrison) * entre(rng, 0.85, 1.15);

  const vencedor: ResultadoCombate['vencedor'] =
    forcaAtaque >= forcaDefesa ? 'atacante' : 'defensor';

  // Combate apertado = mais baixas dos dois lados.
  const intensidade =
    Math.min(forcaAtaque, forcaDefesa) / Math.max(forcaAtaque, forcaDefesa, 1);
  const pressaoPerdedor = 0.55 + 0.4 * intensidade;
  const pressaoVencedor = 0.15 + 0.35 * intensidade;

  const baixasAtacante = calcularBaixas(
    atacantes,
    vencedor === 'atacante' ? pressaoVencedor : pressaoPerdedor,
    bairro.risco,
    rng,
  );
  const baixasDefensor = calcularBaixas(
    defensores,
    vencedor === 'defensor' ? pressaoVencedor : pressaoPerdedor,
    bairro.risco,
    rng,
  );

  return {
    vencedor,
    forcaAtaque: Math.round(forcaAtaque),
    forcaDefesa: Math.round(forcaDefesa),
    baixasAtacante,
    baixasDefensor,
  };
}
