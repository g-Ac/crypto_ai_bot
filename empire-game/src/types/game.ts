/**
 * Estrutura de dados core do jogo — segue o game-design-doc.md.
 * Tudo aqui é JSON-serializável (nenhuma classe / função), pra permitir
 * save/load direto via AsyncStorage.
 */

export type FaccaoTipo = 'jogador' | 'ia';

/** Arquétipos de comportamento da IA (só faz sentido pra facções tipo 'ia'). */
export type Arquetipo = 'agressivo' | 'paciente' | 'oportunista';

/** Traço de personalidade do soldado — influencia poder e decisões futuras. */
export type Traco = 'leal' | 'ganancioso' | 'covarde';

export type SoldadoStatus = 'ativo' | 'ferido' | 'preso' | 'morto';

/** Fase atual do turno (loop de jogo do doc, seção 4). */
export type FaseTurno = 'relatorio' | 'decisao' | 'ia' | 'fim';

export type StatusPartida = 'em_andamento' | 'vitoria' | 'derrota';

export interface Arma {
  id: string;
  nome: string;
  dano: number;
  custo: number;
  /** ids de cidades onde a arma está disponível na loja. */
  cidadesDisponiveis: string[];
}

export interface Soldado {
  id: string;
  nome: string;
  /** 0-100. */
  lealdade: number;
  traco: Traco;
  /** Força base de combate (sem contar arma). */
  forca: number;
  /** id da arma equipada, ou null (briga no braço). */
  armaId: string | null;
  status: SoldadoStatus;
  /** Facção dona do soldado. */
  faccaoId: string;
  /** Bairro onde o soldado está posicionado. */
  bairroId: string;
}

export interface Bairro {
  id: string;
  nome: string;
  /** id da facção dona, ou null (bairro neutro). */
  dono: string | null;
  /** Valor econômico — gera renda por turno pra quem controla. */
  valorBase: number;
  /** 0-100. Risco de batida policial (chance de prisão em combate aqui). */
  risco: number;
  /** ids dos bairros adjacentes. */
  conexoes: string[];
  /** Nível da boca/ponto de venda instalado (0 = nenhum). Rende por turno e atrai polícia. */
  producao: number;
}

export interface Faccao {
  id: string;
  nome: string;
  tipo: FaccaoTipo;
  /** null pro jogador; define comportamento pra IA. */
  arquetipo: Arquetipo | null;
  /** Cor de identidade (hex) — usada na UI. */
  cor: string;
  caixa: number;
  respeito: number;
  /** 0-100. Heat / atenção policial acumulada. */
  calor: number;
  soldados: Soldado[];
}

export interface Cidade {
  id: string;
  nome: string;
  era: string;
  dificuldadeBase: number;
  bairros: Bairro[];
}

export type LogTipo = 'info' | 'combate' | 'ia' | 'renda' | 'sistema' | 'fim';

export interface LogEntry {
  id: number;
  turno: number;
  tipo: LogTipo;
  texto: string;
}

export interface Turno {
  numero: number;
  fase: FaseTurno;
  /** Ações que o jogador ainda pode gastar neste turno. */
  acoesRestantes: number;
}

/**
 * Marcador de inteligência: uma facção espionou um bairro e ganha bônus de
 * ataque contra ele até `expiraTurno` (inclusive).
 */
export interface IntelMarker {
  faccaoId: string;
  bairroId: string;
  expiraTurno: number;
}

/**
 * Estado completo de uma partida. As "rivais" do doc (Cidade.rivais) e o
 * jogador vivem juntos em `faccoes`; a cidade guarda só os bairros.
 */
export interface GameState {
  versao: number;
  cidade: Cidade;
  faccoes: Faccao[];
  jogadorId: string;
  turno: Turno;
  status: StatusPartida;
  /** Catálogo de armas disponível na partida. */
  armas: Arma[];
  log: LogEntry[];
  /** Contador monotônico pra gerar ids de log estáveis. */
  logSeq: number;
  /** Contador monotônico pra gerar ids de soldados recrutados. */
  recrutaSeq: number;
  /** Marcadores de espionagem ativos. */
  intel: IntelMarker[];
}
