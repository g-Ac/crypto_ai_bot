/**
 * Ações mutadoras da partida. Cada função clona o estado, aplica a mudança e
 * devolve um novo GameState — nunca muta o argumento. Reusadas pelo jogador
 * (via store) e pela IA.
 */

import {
  ADVOGADO_REDUZ_CALOR,
  BATIDA_ESFRIA_CALOR,
  CALOR_LIMIAR_BATIDA,
  CUSTO_ADVOGADO,
  CUSTO_ESPIONAGEM,
  CUSTO_RECRUTA,
  ESPIONAGEM_CALOR,
  FATOR_RENDA,
  INTEL_BONUS_ATAQUE,
  INTEL_DURACAO,
  NOMES_RECRUTA,
  TRACOS,
} from '../data/seed';
import { participaDeCombate, resolverCombate, type Baixa, type Rng } from './combat';
import {
  alvosPossiveis,
  armaDe,
  armasMap,
  bairroDe,
  bairrosDaFaccao,
  defensoresDoBairro,
  destinosDeMovimento,
  faccaoDe,
  forcaDeAtaque,
  temIntel,
} from './selectors';
import type { GameState, LogTipo, Soldado } from '../types/game';

export interface ResultadoAcao {
  state: GameState;
  ok: boolean;
  mensagem: string;
}

/** Clone profundo — GameState é puro JSON, então isto é seguro e barato (estado pequeno). */
export function clonar(state: GameState): GameState {
  return JSON.parse(JSON.stringify(state)) as GameState;
}

export function addLog(state: GameState, tipo: LogTipo, texto: string): void {
  state.log.push({ id: state.logSeq, turno: state.turno.numero, tipo, texto });
  state.logSeq += 1;
  // Mantém o log enxuto (últimos 60 eventos) — Expo Go / device com pouca RAM.
  if (state.log.length > 60) state.log = state.log.slice(-60);
}

function encontrarSoldado(state: GameState, soldadoId: string): Soldado | undefined {
  for (const f of state.faccoes) {
    const s = f.soldados.find((x) => x.id === soldadoId);
    if (s) return s;
  }
  return undefined;
}

function aplicarBaixas(state: GameState, baixas: Baixa[]): void {
  for (const b of baixas) {
    const s = encontrarSoldado(state, b.soldadoId);
    if (s) s.status = b.status;
  }
}

/** Move um soldado pra um bairro próprio adjacente. */
export function moverSoldado(
  state: GameState,
  soldadoId: string,
  destinoId: string,
): ResultadoAcao {
  const novo = clonar(state);
  const s = encontrarSoldado(novo, soldadoId);
  if (!s) return { state, ok: false, mensagem: 'Soldado não encontrado.' };
  if (s.status !== 'ativo' && s.status !== 'ferido') {
    return { state, ok: false, mensagem: `${s.nome} não pode se mover (${s.status}).` };
  }
  const destinos = destinosDeMovimento(novo, s);
  const destino = destinos.find((b) => b.id === destinoId);
  if (!destino) {
    return { state, ok: false, mensagem: 'Destino inválido (precisa ser bairro seu e vizinho).' };
  }
  const origem = bairroDe(novo, s.bairroId);
  s.bairroId = destinoId;
  addLog(novo, 'info', `${s.nome} moveu de ${origem?.nome ?? '?'} pra ${destino.nome}.`);
  return { state: novo, ok: true, mensagem: `${s.nome} → ${destino.nome}` };
}

/** Compra e equipa uma arma num soldado da facção. */
export function comprarArma(
  state: GameState,
  faccaoId: string,
  armaId: string,
  soldadoId: string,
): ResultadoAcao {
  const novo = clonar(state);
  const fac = faccaoDe(novo, faccaoId);
  const arma = armaDe(novo, armaId);
  const s = encontrarSoldado(novo, soldadoId);
  if (!fac) return { state, ok: false, mensagem: 'Facção inválida.' };
  if (!arma) return { state, ok: false, mensagem: 'Arma inválida.' };
  if (!s || s.faccaoId !== faccaoId) {
    return { state, ok: false, mensagem: 'Soldado inválido pra essa facção.' };
  }
  if (s.status === 'morto' || s.status === 'preso') {
    return { state, ok: false, mensagem: `${s.nome} não pode ser armado (${s.status}).` };
  }
  if (!arma.cidadesDisponiveis.includes(novo.cidade.id)) {
    return { state, ok: false, mensagem: `${arma.nome} não está disponível aqui.` };
  }
  if (s.armaId === armaId) {
    return { state, ok: false, mensagem: `${s.nome} já usa ${arma.nome}.` };
  }
  if (fac.caixa < arma.custo) {
    return { state, ok: false, mensagem: `Caixa insuficiente pra ${arma.nome} ($${arma.custo}).` };
  }
  fac.caixa -= arma.custo;
  s.armaId = armaId;
  addLog(novo, 'info', `${fac.nome} armou ${s.nome} com ${arma.nome} (-$${arma.custo}).`);
  return { state: novo, ok: true, mensagem: `${s.nome} equipou ${arma.nome}.` };
}

/**
 * Recruta um soldado novo num bairro próprio (economia in-match). Não gasta ação,
 * só caixa — é o motor de snowball que resolve o empate estrutural: quem controla
 * mais território arrecada mais e forma exército maior.
 */
export function recrutarSoldado(
  state: GameState,
  faccaoId: string,
  bairroId: string,
  rng: Rng = Math.random,
): ResultadoAcao {
  const novo = clonar(state);
  const fac = faccaoDe(novo, faccaoId);
  const bairro = bairroDe(novo, bairroId);
  if (!fac) return { state, ok: false, mensagem: 'Facção inválida.' };
  if (!bairro || bairro.dono !== faccaoId) {
    return { state, ok: false, mensagem: 'Só dá pra recrutar em bairro seu.' };
  }
  if (fac.caixa < CUSTO_RECRUTA) {
    return { state, ok: false, mensagem: `Caixa insuficiente pra recrutar ($${CUSTO_RECRUTA}).` };
  }

  const seq = novo.recrutaSeq;
  novo.recrutaSeq += 1;
  const nome = NOMES_RECRUTA[Math.floor(rng() * NOMES_RECRUTA.length)] ?? `Recruta ${seq}`;
  const traco = TRACOS[Math.floor(rng() * TRACOS.length)] ?? 'ganancioso';
  const forca = 7 + Math.floor(rng() * 5); // 7-11

  fac.caixa -= CUSTO_RECRUTA;
  fac.soldados.push({
    id: `${faccaoId}-r${seq}`,
    nome,
    lealdade: 60,
    traco,
    forca,
    armaId: 'faca',
    status: 'ativo',
    faccaoId,
    bairroId,
  });
  addLog(novo, 'info', `${fac.nome} recrutou ${nome} (fç ${forca}, ${traco}) em ${bairro.nome} (-$${CUSTO_RECRUTA}).`);
  return { state: novo, ok: true, mensagem: `Recrutou ${nome} em ${bairro.nome}.` };
}

/** Ataca um bairro adjacente ao território da facção. */
export function atacarBairro(
  state: GameState,
  faccaoId: string,
  alvoId: string,
  rng: Rng = Math.random,
): ResultadoAcao {
  const novo = clonar(state);
  const fac = faccaoDe(novo, faccaoId);
  const alvo = bairroDe(novo, alvoId);
  if (!fac || !alvo) return { state, ok: false, mensagem: 'Alvo inválido.' };
  if (alvo.dono === faccaoId) {
    return { state, ok: false, mensagem: 'Esse bairro já é seu.' };
  }

  const { atacantes } = forcaDeAtaque(novo, faccaoId, alvoId);
  if (atacantes.length === 0) {
    return { state, ok: false, mensagem: 'Sem tropas em bairro vizinho pra atacar.' };
  }
  const defensores = defensoresDoBairro(novo, alvoId);

  // Intel de espionagem dá bônus de ataque e é consumido no assalto.
  const comIntel = temIntel(novo, faccaoId, alvoId);
  const bonus = comIntel ? INTEL_BONUS_ATAQUE : 1;
  novo.intel = novo.intel.filter((m) => !(m.faccaoId === faccaoId && m.bairroId === alvoId));

  const resultado = resolverCombate(atacantes, defensores, alvo, armasMap(novo), rng, bonus);
  aplicarBaixas(novo, resultado.baixasAtacante);
  aplicarBaixas(novo, resultado.baixasDefensor);

  const donoAntigo = alvo.dono ? faccaoDe(novo, alvo.dono) : undefined;
  const nBaixas = resultado.baixasAtacante.length + resultado.baixasDefensor.length;
  const tagIntel = comIntel ? ' [intel]' : '';

  addLog(
    novo,
    'combate',
    `${fac.nome} atacou ${alvo.nome}${tagIntel} — ataque ${resultado.forcaAtaque} vs defesa ${resultado.forcaDefesa}.`,
  );

  if (resultado.vencedor === 'atacante') {
    alvo.dono = faccaoId;
    // Sobreviventes ocupam o bairro conquistado.
    for (const a of atacantes) {
      if (a.status === 'ativo' || a.status === 'ferido') a.bairroId = alvoId;
    }
    fac.respeito += 10 + Math.round(alvo.valorBase / 100);
    fac.calor = Math.min(100, fac.calor + 8);
    const de = donoAntigo ? ` (tomado de ${donoAntigo.nome})` : '';
    addLog(novo, 'combate', `${fac.nome} DOMINOU ${alvo.nome}${de}. ${nBaixas} baixa(s).`);
    return { state: novo, ok: true, mensagem: `Você dominou ${alvo.nome}!` };
  }

  fac.calor = Math.min(100, fac.calor + 4);
  addLog(novo, 'combate', `${fac.nome} foi repelido em ${alvo.nome}. ${nBaixas} baixa(s).`);
  return { state: novo, ok: true, mensagem: `Ataque a ${alvo.nome} repelido.` };
}

/**
 * Espiona um bairro adjacente ao território: paga caixa, sobe o calor e ganha
 * intel (bônus no próximo ataque a esse bairro). Gasta uma ação.
 */
export function espionarBairro(
  state: GameState,
  faccaoId: string,
  alvoId: string,
): ResultadoAcao {
  const novo = clonar(state);
  const fac = faccaoDe(novo, faccaoId);
  const alvo = bairroDe(novo, alvoId);
  if (!fac || !alvo) return { state, ok: false, mensagem: 'Alvo inválido.' };
  if (alvo.dono === faccaoId) {
    return { state, ok: false, mensagem: 'Não faz sentido espionar bairro seu.' };
  }
  const podeAlcancar = alvosPossiveis(novo, faccaoId).some((b) => b.id === alvoId);
  if (!podeAlcancar) {
    return { state, ok: false, mensagem: 'Só dá pra espionar bairro na sua fronteira.' };
  }
  if (fac.caixa < CUSTO_ESPIONAGEM) {
    return { state, ok: false, mensagem: `Caixa insuficiente pra espionar ($${CUSTO_ESPIONAGEM}).` };
  }

  fac.caixa -= CUSTO_ESPIONAGEM;
  fac.calor = Math.min(100, fac.calor + ESPIONAGEM_CALOR);
  // Renova/adiciona o marcador de intel.
  novo.intel = novo.intel.filter((m) => !(m.faccaoId === faccaoId && m.bairroId === alvoId));
  novo.intel.push({ faccaoId, bairroId: alvoId, expiraTurno: novo.turno.numero + INTEL_DURACAO });
  addLog(novo, 'info', `${fac.nome} espionou ${alvo.nome}. Intel obtido (+ataque no próximo assalto).`);
  return { state: novo, ok: true, mensagem: `Intel sobre ${alvo.nome} obtido.` };
}

/** Contrata advogado: paga caixa e reduz o calor (despista a polícia). Não gasta ação. */
export function contratarAdvogado(state: GameState, faccaoId: string): ResultadoAcao {
  const novo = clonar(state);
  const fac = faccaoDe(novo, faccaoId);
  if (!fac) return { state, ok: false, mensagem: 'Facção inválida.' };
  if (fac.calor <= 0) {
    return { state, ok: false, mensagem: 'Calor já está zerado.' };
  }
  if (fac.caixa < CUSTO_ADVOGADO) {
    return { state, ok: false, mensagem: `Caixa insuficiente pro advogado ($${CUSTO_ADVOGADO}).` };
  }
  fac.caixa -= CUSTO_ADVOGADO;
  const antes = fac.calor;
  fac.calor = Math.max(0, fac.calor - ADVOGADO_REDUZ_CALOR);
  addLog(novo, 'info', `${fac.nome} pagou advogado: calor ${antes} → ${fac.calor} (-$${CUSTO_ADVOGADO}).`);
  return { state: novo, ok: true, mensagem: `Advogado esfriou o calor pra ${fac.calor}.` };
}

/**
 * Batida policial: facções com calor alto arriscam ter um soldado preso. Muta o
 * estado (usar em clone, na resolução do turno). Quanto maior o calor, maior a chance.
 */
export function aplicarBatidaPolicial(state: GameState, rng: Rng = Math.random): void {
  for (const fac of state.faccoes) {
    if (fac.calor < CALOR_LIMIAR_BATIDA) continue;
    const chance = (fac.calor - CALOR_LIMIAR_BATIDA) / 100 + 0.1; // 0.1..0.6
    if (rng() >= chance) continue;

    const dePe = fac.soldados.filter(participaDeCombate);
    if (dePe.length > 0) {
      const alvo = dePe[Math.floor(rng() * dePe.length)];
      alvo.status = 'preso';
      addLog(state, 'combate', `BATIDA POLICIAL: ${alvo.nome} (${fac.nome}) foi preso.`);
    } else {
      const multa = Math.min(fac.caixa, 300);
      fac.caixa -= multa;
      addLog(state, 'combate', `BATIDA POLICIAL: ${fac.nome} perdeu $${multa} em apreensão.`);
    }
    fac.calor = Math.max(0, fac.calor - BATIDA_ESFRIA_CALOR);
  }
}

/** Remove marcadores de intel expirados. Muta o estado (usar em clone). */
export function limparIntelExpirado(state: GameState): void {
  state.intel = state.intel.filter((m) => m.expiraTurno >= state.turno.numero);
}

/** Renda por turno + leve decaimento de calor. Muta o estado passado (usar em clone). */
export function aplicarRenda(state: GameState): void {
  for (const fac of state.faccoes) {
    const total = bairrosDaFaccao(state, fac.id).reduce((acc, b) => acc + b.valorBase, 0);
    const renda = Math.round(total * FATOR_RENDA);
    if (renda > 0) {
      fac.caixa += renda;
      if (fac.tipo === 'jogador') {
        addLog(state, 'renda', `Renda dos territórios: +$${renda}.`);
      }
    }
    fac.calor = Math.max(0, fac.calor - 3);
  }
}
