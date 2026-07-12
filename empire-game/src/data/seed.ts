/**
 * Partida de teste — o "core loop mínimo jogável".
 *
 * Mapa em linha:  Beco do Sol (jogador) — Vila Torta (neutro) — Morro Alto (IA)
 * O bairro do meio é a disputa clássica: quem tomar Vila Torta ganha a ponte
 * pra invadir o território inimigo.
 */

import { cores } from '../theme/tokens';
import type { Arma, Bairro, Cidade, Faccao, GameState, Soldado } from '../types/game';

export const CIDADE_ID = 'zona-sul';
export const JOGADOR_ID = 'os-corvos';
export const IA_ID = 'sindicato-rubro';

export const B_BECO = 'beco-do-sol';
export const B_VILA = 'vila-torta';
export const B_MORRO = 'morro-alto';

/** Catálogo de armas da cidade. Faca é grátis (arma base). */
export const ARMAS: Arma[] = [
  { id: 'faca', nome: 'Faca', dano: 2, custo: 0, cidadesDisponiveis: [CIDADE_ID] },
  { id: 'pistola', nome: 'Pistola', dano: 5, custo: 300, cidadesDisponiveis: [CIDADE_ID] },
  { id: 'escopeta', nome: 'Escopeta', dano: 9, custo: 700, cidadesDisponiveis: [CIDADE_ID] },
  { id: 'fuzil', nome: 'Fuzil', dano: 15, custo: 1500, cidadesDisponiveis: [CIDADE_ID] },
];

function bairros(): Bairro[] {
  return [
    {
      id: B_BECO,
      nome: 'Beco do Sol',
      dono: JOGADOR_ID,
      valorBase: 1200,
      risco: 20,
      conexoes: [B_VILA],
      producao: 1,
    },
    {
      id: B_VILA,
      nome: 'Vila Torta',
      dono: null,
      valorBase: 2000,
      risco: 45,
      conexoes: [B_BECO, B_MORRO],
      producao: 0,
    },
    {
      id: B_MORRO,
      nome: 'Morro Alto',
      dono: IA_ID,
      valorBase: 1500,
      risco: 30,
      conexoes: [B_VILA],
      producao: 1,
    },
  ];
}

function soldado(
  id: string,
  nome: string,
  faccaoId: string,
  bairroId: string,
  forca: number,
  traco: Soldado['traco'],
  armaId: string | null,
): Soldado {
  return {
    id,
    nome,
    lealdade: 70,
    traco,
    forca,
    armaId,
    status: 'ativo',
    faccaoId,
    bairroId,
  };
}

function jogador(): Faccao {
  return {
    id: JOGADOR_ID,
    nome: 'Os Corvos',
    tipo: 'jogador',
    arquetipo: null,
    cor: cores.gold1,
    caixa: 500,
    respeito: 0,
    calor: 0,
    soldados: [
      soldado('p1', 'Zé Pequeno', JOGADOR_ID, B_BECO, 11, 'leal', 'pistola'),
      soldado('p2', 'Bagre', JOGADOR_ID, B_BECO, 9, 'ganancioso', 'pistola'),
      soldado('p3', 'Formiga', JOGADOR_ID, B_BECO, 8, 'covarde', 'faca'),
    ],
  };
}

function ia(): Faccao {
  return {
    id: IA_ID,
    nome: 'Sindicato Rubro',
    tipo: 'ia',
    arquetipo: 'agressivo',
    cor: cores.bloodLight,
    caixa: 500,
    respeito: 0,
    calor: 0,
    soldados: [
      soldado('e1', 'Régis', IA_ID, B_MORRO, 10, 'leal', 'pistola'),
      soldado('e2', 'Caveira', IA_ID, B_MORRO, 12, 'ganancioso', 'pistola'),
      soldado('e3', 'Sombra', IA_ID, B_MORRO, 8, 'covarde', 'faca'),
    ],
  };
}

export function cidadeInicial(): Cidade {
  return {
    id: CIDADE_ID,
    nome: 'Zona Sul',
    era: '2020s',
    dificuldadeBase: 1,
    bairros: bairros(),
  };
}

/** Monta um GameState novo e limpo pra uma partida de teste. */
export function criarPartida(): GameState {
  return {
    versao: 1,
    cidade: cidadeInicial(),
    faccoes: [jogador(), ia()],
    jogadorId: JOGADOR_ID,
    turno: { numero: 1, fase: 'decisao', acoesRestantes: ACOES_POR_TURNO },
    status: 'em_andamento',
    armas: ARMAS,
    log: [
      {
        id: 0,
        turno: 1,
        tipo: 'sistema',
        texto: 'Guerra por Zona Sul começou. Vila Torta está em disputa.',
      },
    ],
    logSeq: 1,
    recrutaSeq: 0,
    intel: [],
  };
}

/** Quantas ações (mover/atacar) o jogador tem por turno. */
export const ACOES_POR_TURNO = 3;

/** Fração do valorBase dos bairros que vira renda por turno. */
export const FATOR_RENDA = 0.1;

/** Custo pra recrutar um soldado novo (economia in-match). */
export const CUSTO_RECRUTA = 450;

/** Traços possíveis de um recruta. */
export const TRACOS: Soldado['traco'][] = ['leal', 'ganancioso', 'covarde'];

/** Pool de apelidos pra recrutas (indexado por seq + rng). */
export const NOMES_RECRUTA = [
  'Piloto', 'Neném', 'Gordo', 'Xis', 'Baiano', 'Russo', 'Tuim', 'Careca',
  'Nariz', 'Metralha', 'Dente', 'Faísca', 'Mão Branca', 'Corvo', 'Passarinho',
  'Zóio', 'Cebola', 'Trovão', 'Meia-Noite', 'Chumbo',
] as const;

// --- Espionagem / Heat / Polícia / Advogados ---

/** Custo em caixa pra espionar um bairro. */
export const CUSTO_ESPIONAGEM = 150;
/** Calor ganho ao espionar (operação arriscada). */
export const ESPIONAGEM_CALOR = 3;
/** Turnos que o intel permanece válido além do turno atual. */
export const INTEL_DURACAO = 1;
/** Multiplicador de ataque quando há intel ativo sobre o alvo. */
export const INTEL_BONUS_ATAQUE = 1.25;

/** Custo pra contratar advogado (esfria o calor / despista a polícia). */
export const CUSTO_ADVOGADO = 300;
/** Quanto de calor o advogado remove. */
export const ADVOGADO_REDUZ_CALOR = 25;

/** Calor a partir do qual a facção corre risco de batida policial. */
export const CALOR_LIMIAR_BATIDA = 50;
/** Calor removido quando uma batida acontece. */
export const BATIDA_ESFRIA_CALOR = 20;

// --- Produção (bocas / pontos de venda) ---

/** Custo pra instalar/subir um nível de boca num bairro próprio. */
export const CUSTO_BOCA = 600;
/** Nível máximo de boca por bairro. */
export const MAX_BOCA_NIVEL = 3;
/** Renda por turno gerada por nível de boca. */
export const RENDA_POR_BOCA = 160;
/** Calor por turno gerado por nível de boca (tráfico atrai a polícia). */
export const CALOR_POR_BOCA = 3;
