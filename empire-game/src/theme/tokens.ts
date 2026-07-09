/**
 * Tokens visuais derivados do protótipo (tela-inicial-prototipo.html).
 * Paleta retro/graffiti: dourado stencil sobre preto, verde "money", vermelho sangue.
 */

export const cores = {
  bg: '#0c0c0a',
  bgElev: '#15150f',
  gold1: '#f2b93a',
  gold2: '#8a5a12',
  money: '#2f5233',
  moneyLight: '#4d7d52',
  blood: '#7a1f1f',
  bloodLight: '#a83a3a',
  cream: '#e9e2cf',
  muted: '#8f8a78',
  mutedDim: '#5b5648',
  cardLocked: '#1a1a17',
  cardBorder: '#3a3327',
  danger: '#c74848',
  neutral: '#6b6b62',
} as const;

export const fontes = {
  /** Títulos / labels em stencil. */
  titulo: 'Bungee_400Regular',
  /** Corpo / números em pixel mono. */
  corpo: 'VT323_400Regular',
} as const;

/** Cores por status de soldado, pra UI consistente. */
export const corStatus: Record<string, string> = {
  ativo: cores.moneyLight,
  ferido: cores.gold1,
  preso: cores.muted,
  morto: cores.bloodLight,
};

export const espaco = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 18,
  xl: 26,
} as const;
