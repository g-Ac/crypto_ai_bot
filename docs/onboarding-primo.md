# Projeto de Trading — Onboarding & Alinhamento

> **Pra que serve este documento:** dar a você (que vai entrar ajudando com documentação e visão de
> negócio) uma visão honesta e completa do projeto antes da nossa primeira reunião. Não precisa
> entender de trade pra ler — a Seção 2 é um glossário pros termos que aparecem aqui.
>
> Data: 08/06/2026 · Autor: Gabriel

---

## Resumo em 1 página (leia isto primeiro)

Eu mantenho um **laboratório de pesquisa de estratégias de trading de criptomoeda**. Na prática, é um
programa (um "robô") que roda sozinho 24 horas por dia num computadorzinho (Raspberry Pi) aqui em casa.
Ele observa o mercado de cripto e **simula** operações de compra e venda.

A palavra-chave é **simula**: tudo é *paper trading* — dinheiro de mentira, risco zero. Nenhum centavo
real entra ou sai. Isso é de propósito: o objetivo do laboratório não é ganhar dinheiro agora, é
**descobrir se existe uma vantagem real e repetível** (no jargão, um *edge*) antes de arriscar qualquer
coisa de verdade.

**Estado honesto, em uma frase:** eu já sei fazer o robô operar com disciplina e medir tudo com rigor,
mas **ainda não provei que ele bate o mercado de forma consistente** — e essa prova é o jogo inteiro.

**O que este projeto É:**
- Um laboratório de pesquisa e aprendizado, levado a sério, com método científico.
- Uma forma de testar ideias de mercado sem arriscar dinheiro.
- Um sistema que já funciona tecnicamente (roda, opera, registra tudo num banco de dados).

**O que este projeto NÃO é (importante pra não criarmos expectativa errada):**
- **Não** é uma máquina de fazer dinheiro pronta pra ligar.
- **Não** é, hoje, uma fonte de renda — eu trato isto como pesquisa, não como o lugar onde aposto meu dinheiro.
- **Não** é um produto pronto pra vender, escalar ou "tokenizar". Pode vir a ser algo, mas não é hoje.

**O que cada um traz:** eu trago a pesquisa, o código, os dados e o conhecimento de trade. Você traz a
documentação, a clareza (me obrigar a explicar já vale ouro) e uma visão de negócio que eu não tenho.

**O que eu quero da nossa primeira reunião:** alinhar expectativas e papéis — que jogo a gente está
jogando, em que horizonte, e o que faz sentido construir juntos. As perguntas estão na Seção 7.

---

## 1. O que é o projeto

É um **laboratório**, não um negócio. A diferença importa.

Um robô de trading, no fim, é um programa que segue uma regra do tipo *"quando o mercado fizer X, compre;
quando fizer Y, venda"*. A parte fácil é escrever essa regra. A parte difícil — e que é 90% do trabalho —
é responder à pergunta: **essa regra realmente dá lucro, ou só pareceu dar porque o período foi
favorável?** O mercado engana muito. Uma estratégia pode parecer genial por dois meses e ser pura sorte.

Por isso o projeto é montado como um laboratório científico:
- **Tudo é simulado** (paper trading), então posso testar ideias ruins sem perder dinheiro.
- **Tudo é registrado** num banco de dados — cada decisão, cada operação, com dezenas de detalhes.
- **Toda ideia vira um experimento** com critério de aprovação ou reprovação definido *antes* de olhar o
  resultado (pra não enganar a si mesmo).
- O lema é **"dados acima de opinião"**. Já reprovei várias ideias minhas que pareciam ótimas no papel.

O objetivo final é encontrar uma vantagem (*edge*) que seja real, repetível e que sobreviva aos custos de
operar. Enquanto essa vantagem não estiver provada, **não faz sentido colocar dinheiro real nem tratar
isso como negócio.** Essa é a régua honesta do projeto.

---

## 2. Glossário pra leigo (sem jargão)

Os termos que vão aparecer neste documento, em uma linha cada:

- **Paper trading:** operar com dinheiro de mentira (simulação). Risco zero. É o modo atual do projeto.
- **Edge (vantagem):** o santo graal. Uma razão real pra ganhar mais do que perder ao longo do tempo. Sem
  edge, trading é só apostar.
- **Estratégia:** a regra que decide quando comprar e vender.
- **Regime de mercado:** o "humor" do mercado num momento. Pode estar **em tendência** (subindo ou caindo
  com força), **de lado/lateralizado** (preço parado, andando de um lado pro outro) ou **nervoso/errático**.
- **Momentum:** estratégia que tenta "pegar carona" em movimentos que já estão acontecendo com força.
- **Pullback (recuo):** quando o preço, no meio de uma subida, dá uma respirada e recua um pouco antes de
  (talvez) continuar subindo. Bons pontos pra entrar mais barato.
- **Liquidação:** quando quem operou com dinheiro emprestado (alavancado) erra a mão, a corretora fecha a
  posição dele à força. Quando isso acontece com muita gente ao mesmo tempo, o preço se move bruscamente.
- **Backtest:** rodar a estratégia no passado ("se eu tivesse operado nos últimos 90 dias, o que teria
  acontecido?") pra ter uma ideia se ela presta.
- **Profit Factor (PF):** quanto a estratégia ganha pra cada R$1 que perde. **PF acima de 1 = lucrativa;
  abaixo de 1 = perde dinheiro.** É uma das métricas mais honestas.
- **Win rate (taxa de acerto):** % de operações que dão lucro. Ilude: dá pra acertar 60% das vezes e ainda
  perder dinheiro, se os acertos forem pequenos e os erros grandes.
- **Drawdown:** o tombo. A maior queda do capital do pico até o fundo. Mede o sofrimento.
- **GO / NO-GO:** o veredicto de um experimento. GO = a ideia passou nos critérios, segue. NO-GO = reprovada.

---

## 3. Como o bot funciona (do sinal ao trade)

A estratégia que está rodando hoje se chama **Momentum Pullback**. Em português claro, a lógica é:

> *"Quando o mercado está numa tendência forte, espere ele dar uma respirada (um recuo), e entre na hora
> em que ele retoma o movimento."*

O robô faz isso num ciclo, a cada 5 minutos:

1. **Lê o mercado.** Puxa os preços recentes do Bitcoin e do Ethereum (da corretora Binance).
2. **Detecta o regime.** Calcula se o mercado está em **tendência forte**, tendência fraca, nervoso, de
   lado ou totalmente errático. Isso é a peça mais importante.
3. **Filtra pelo regime.** Se o mercado **não** está em tendência, o robô **não opera** e registra "bloqueado
   por regime". Essa é a ideia central: a estratégia só funciona quando há tendência; em mercado parado ela
   se confunde, então é melhor ficar de fora.
4. **Procura o recuo (pullback).** Em tendência, ele espera o preço recuar entre 30% e 70% do último
   movimento — sem quebrar a estrutura da tendência.
5. **Confirma e entra.** Quando o preço dá sinal de que retomou o movimento, o robô abre uma operação
   simulada.
6. **Gerencia a saída.** Define onde realiza o lucro e onde corta o prejuízo, e acompanha até fechar.

**Uma analogia:** é como surfar. Você não rema em qualquer água (mar parado = sem onda = sem operar). Você
espera uma onda boa se formando (tendência), posiciona a prancha (recuo), e rema na hora em que a onda
levanta (confirmação). Se o mar está uma bagunça, você fica sentado na areia — e ficar de fora também é uma
decisão.

**E a liquidação?** No primeiro áudio eu comentei que "liquidação é o maior indício". Essa é uma **hipótese
de pesquisa minha, e ela ainda NÃO está dentro do robô.** A ideia: quando muita gente alavancada é
liquidada de uma vez, isso pode antecipar pra onde o preço vai. Hoje eu só **coleto** esses dados pra
estudar; eles ainda não influenciam nenhuma decisão. É uma das frentes abertas (Seção 5).

---

## 4. Onde estamos de verdade (estado honesto)

Aqui está a parte que muita gente esconde, e que eu faço questão de deixar na mesa.

A estratégia atual (Momentum Pullback) foi testada com rigor. O veredicto mais recente, de um período de
cerca de 30 dias (abril a maio de 2026):

- A estratégia **perdeu cerca de 6,7%**, enquanto o **Bitcoin subiu cerca de 6,3%** no mesmo período. Ou
  seja: teria sido melhor simplesmente comprar Bitcoin e não fazer nada.
- O **Profit Factor ficou abaixo de 1** — perdeu mais do que ganhou. E quando entra o **custo real de cada
  operação** (a corretora cobra uma taxa toda vez), o resultado piora ainda mais.
- A taxa de acerto até parece boa (~57%), mas isso **ilude**: os acertos foram menores que os erros.

E o mais revelador: **o pouco que a estratégia rendeu em outros momentos veio de o mercado estar subindo,
não de uma vantagem própria dela.** Foi maré favorável, não competência. No próprio áudio eu disse isso
sem perceber o peso: *"tá dando certo, mas é porque o regime tava favorável"*. Os dados confirmam essa
frase.

Eu também já tentei várias melhorias nessa estratégia (mexer em parâmetros, adicionar filtros). **Reprovei
três seguidas** com método. A conclusão foi: essa estratégia está num "teto" — espremê-la mais não vai dar
salto. Qualquer avanço de verdade virá de **mais dados** ou de uma **ideia estruturalmente diferente**, não
de ajuste fino.

**Tradução pra quem não é de trade:** a parte de engenharia está madura — o robô roda sozinho, com
disciplina, e mede tudo. O que **ainda não existe** é a prova de que ele ganha dinheiro de forma
consistente acima do mercado. E essa prova é exatamente o que separa um "projeto legal de tecnologia" de
um "negócio". Estamos do lado do projeto legal de tecnologia. Por enquanto.

---

## 5. Frentes abertas (o que estou pesquisando)

O laboratório não está parado — está investigando algumas pistas:

- **A pista da liquidação / microestrutura.** A hipótese de que o comportamento de quem opera alavancado
  (e é liquidado) carrega informação sobre o próximo movimento. Já fiz um teste preliminar: deu **morno,
  inconclusivo** — nem aprovou, nem reprovou de vez. Tem um novo teste marcado pra ~julho/2026, quando eu
  tiver dados suficientes coletados.
- **Uma mudança de filosofia.** Em vez de tentar *prever* o preço (que é quase impossível), mirar em
  *capturar estrutura que paga* — situações do mercado onde existe uma razão econômica pra um movimento
  acontecer. É uma lente diferente e, na minha visão, mais promissora.
- **Um critério pra saber a hora de parar.** Pra não ficar teimando pra sempre numa ideia morta, eu tenho
  uma regra: se acumular reprovações seguidas numa linha, ela é pausada por um tempo. Disciplina pra não
  perder meses correndo atrás de fantasma.

---

## 6. O que cada um traz / papéis possíveis

**Eu (Gabriel):** a pesquisa, o código, o banco de dados, o conhecimento de trading e o histórico de tudo
que já foi testado. O ativo central do projeto mora aqui.

**Você (primo):** dois pacotes bem diferentes, e vale separá-los com clareza:

1. **Documentação e clareza — útil JÁ, e de risco zero.** Você disse que pra entender precisa documentar, e
   que de trade não entende nada. Isso, longe de ser um problema, é um superpoder aqui: me obrigar a
   explicar o projeto pra alguém de fora **força clareza** e expõe furos no meu raciocínio. Esse pacote eu
   compro de imediato.

2. **Visão de negócio / blockchain — promissor, mas SEPARADO e prematuro.** Você mencionou a ideia de
   tokenização (tipo o pessoal que vende um imóvel em mil partes via blockchain). Quero ser honesto e
   direto, como sócio: **isso é um empreendimento completamente diferente do laboratório de trading.** Tem
   outro produto, outro público, outro risco (jurídico, regulatório, captação). Pode até ser um bom negócio
   — mas não é "a próxima etapa" deste projeto, e fundir as duas coisas agora só ia confundir os dois. Se
   for pra explorar, que seja como uma **frente própria**, com sua própria conversa.

**Uma franqueza sobre horizontes (apareceu nos áudios):** eu estou empolgado com a *estratégia* (o lado
técnico). Você falou que o robô é "longo prazo" e que prefere focar num *negócio agora, num nicho*. Não tem
certo nem errado — mas são **dois objetivos diferentes**, e é melhor a gente perceber isso na largada do que
descobrir daqui a três meses que estava cada um remando pra um lado.

---

## 7. Perguntas pra nossa primeira reunião

Não precisamos resolver tudo. Mas estas são as decisões que valem uma conversa franca:

1. **Qual é o objetivo da parceria?** A gente quer (a) tocar um laboratório de pesquisa juntos, (b) construir
   um negócio/produto, ou (c) começar documentando e decidir o rumo depois? (São caminhos diferentes.)

2. **Em que horizonte?** Você falou em "algo mais agora". Eu vejo a parte de trading como pesquisa de médio
   prazo. Dá pra conciliar — mas vamos deixar explícito o que cada um espera de "curto prazo".

3. **Lab ou negócio — o que entra primeiro?** Documentar e organizar o laboratório é um passo. Montar um
   negócio é outro. Qual deles é o foco dos próximos 30 dias?

4. **A ideia de blockchain/tokenização entra agora ou fica numa gaveta separada?** (Minha sugestão: gaveta
   separada, pra não misturar — mas quero ouvir você.)

5. **Como a gente mede se a parceria está valendo a pena?** Sem dinheiro entrando no curto prazo, qual é o
   "sinal de que estamos no caminho certo" que faz sentido pros dois?

6. **Divisão de papéis e expectativa de tempo.** Quanto cada um consegue dedicar, e quem cuida de quê?

---

> *Este é um documento vivo. Se algo aqui não ficou claro, é falha da explicação, não sua — me avisa que eu
> reescrevo. A ideia é que, depois de ler isto, você tenha "propriedade" do assunto o suficiente pra a gente
> conversar de igual pra igual na reunião.*
