# Território — Dinheiro • Poder 2

Sim de império criminoso por turnos (paper/protótipo). Este repositório contém o
**scaffold Expo + o core loop mínimo jogável** — o primeiro passo do
`game-design-doc.md`.

> ⚠️ Projeto original. Nome, cidades, facções e assets são próprios — inspirado
> na *pegada* do gênero, não é cópia.

## O que já roda (v1 — core loop)

- **Tela inicial** replicando a estética do protótipo (título dourado stencil,
  grid de cidades, pixel fonts Bungee + VT323).
- **1 cidade** (Zona Sul, 2020s) com **3 bairros em linha**:
  `Beco do Sol (você) — Vila Torta (neutro) — Morro Alto (IA)`.
- **2 facções**: Os Corvos (jogador) vs Sindicato Rubro (IA agressiva).
- **Loop de turno completo**: relatório → decisão do jogador (mover / comprar
  arma / atacar) → resolução de combate → fase da IA → checagem de vitória/derrota.
- **Combate** com força dos soldados + dano da arma vs defesa, fator aleatório,
  traços de personalidade, e baixas (ferido / morto / preso por batida policial).
- **Economia** por turno (renda dos territórios) pra financiar arsenal e recrutas.
- **Recrutamento** de soldados (compra por caixa em bairro próprio) — snowball via território.
- **Espionagem**: gasta caixa + sobe calor pra ganhar intel (bônus no próximo assalto).
- **Heat / polícia**: calor alto arrisca batida (soldado preso). **Advogado** esfria o calor.
- **Save/load** automático via AsyncStorage (a partida persiste ao fechar o app).
- **Vitória**: dominar os 3 bairros. **Derrota**: perder território e tropas.

## Como jogar (regra do combate)

Você tem **3 ações por turno** (mover ou atacar). Comprar arma não gasta ação, só
caixa. A tática que vence: **concentre suas tropas no bairro de frente e assalte** —
o atacante tem bônus de iniciativa, mas o defensor tem vantagem de casa. Passividade
tende a empatar.

## Como rodar no celular (Expo Go)

1. Instale o app **Expo Go** (Android / iOS).
2. No computador, dentro desta pasta:

   ```bash
   cd empire-game
   npm install          # só na primeira vez
   npx expo start
   ```

3. Escaneie o QR code do terminal com o Expo Go (Android) ou a câmera (iOS).
   Celular e PC precisam estar na **mesma rede Wi-Fi**. Se a rede bloquear a
   conexão, rode com túnel: `npx expo start --tunnel`.

## Stack

- Expo SDK 57 + TypeScript (strict)
- Zustand (estado global da partida)
- React Navigation (native-stack)
- AsyncStorage (persistência)
- @expo-google-fonts (Bungee + VT323)

## Estrutura

```
src/
  types/game.ts        # Cidade, Bairro, Faccao, Soldado, Arma, Turno, GameState
  data/seed.ts         # partida de teste (mapa, facções, catálogo de armas) + balanceamento
  theme/tokens.ts      # cores e fontes derivadas do protótipo
  engine/
    combat.ts          # resolução de combate (puro, RNG injetável)
    selectors.ts       # queries derivadas do estado (puro)
    actions.ts         # mover / comprar / atacar / renda (puro, imutável)
    ai.ts              # fase da IA por arquétipo
    victory.ts         # checagem de vitória/derrota
  store/gameStore.ts   # store Zustand — orquestra o loop de turno + persiste
  storage/persistence.ts  # save/load AsyncStorage
  navigation/          # stack Home → Game
  screens/             # HomeScreen (menu) + GameScreen (loop)
  components/          # BairroCard, SoldadoRow, LojaModal, LogPanel, etc.
```

O motor (`engine/`) é puro e sem dependência de React Native, então é
simulável/testável fora do app (foi validado por ~300 partidas headless).

## Testes

```bash
npm test          # roda a suíte Jest (jest-expo) sobre o engine/
```

Cobertura em `src/engine/__tests__/`: combate, ações (mover/comprar/recrutar/atacar/renda),
IA, seletores e checagem de vitória. RNG determinístico (mulberry32) pra combates
reprodutíveis.

## O que ficou pro próximo loop

Ver `game-design-doc.md`. Destaques: produção própria (laboratórios/pontos de
venda que rendem por turno), mais bairros e as 3 personalidades de IA de verdade
(paciente/oportunista jogando distinto), lealdade com decisões automáticas dos
soldados, meta-progressão entre partidas (cidades, contatos), e arte/áudio.
