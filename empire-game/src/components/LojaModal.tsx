import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { cores, espaco, fontes } from '../theme/tokens';
import { Botao } from './Botao';
import type { Arma, Soldado } from '../types/game';

interface Props {
  visible: boolean;
  armas: Arma[];
  caixa: number;
  soldado: Soldado | null;
  armaAtual: Arma | undefined;
  onComprar: (armaId: string) => void;
  onClose: () => void;
}

export function LojaModal({ visible, armas, caixa, soldado, armaAtual, onComprar, onClose }: Props) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.caixa}>
          <Text style={styles.titulo}>ARSENAL</Text>
          <Text style={styles.sub}>
            {soldado ? `Armar ${soldado.nome} · atual: ${armaAtual?.nome ?? 'nenhuma'}` : 'Selecione um soldado'}
          </Text>
          <Text style={styles.dinheiro}>Caixa: ${caixa}</Text>

          <View style={styles.lista}>
            {armas.map((a) => {
              const equipada = armaAtual?.id === a.id;
              const podePagar = caixa >= a.custo;
              const habilitado = !!soldado && !equipada && podePagar;
              return (
                <View key={a.id} style={styles.itemRow}>
                  <View style={styles.itemInfo}>
                    <Text style={styles.itemNome}>{a.nome}</Text>
                    <Text style={styles.itemMeta}>
                      dano {a.dano} · ${a.custo}
                      {equipada ? ' · equipada' : ''}
                    </Text>
                  </View>
                  <Botao
                    titulo={equipada ? '✓' : `$${a.custo}`}
                    variante="primario"
                    disabled={!habilitado}
                    onPress={() => onComprar(a.id)}
                    style={styles.itemBtn}
                  />
                </View>
              );
            })}
          </View>

          <Pressable onPress={onClose} style={styles.fechar}>
            <Text style={styles.fecharTxt}>Fechar</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.72)',
    justifyContent: 'center',
    padding: espaco.lg,
  },
  caixa: {
    backgroundColor: cores.bgElev,
    borderWidth: 2,
    borderColor: cores.gold2,
    borderRadius: 4,
    padding: espaco.lg,
  },
  titulo: {
    fontFamily: fontes.titulo,
    fontSize: 20,
    color: cores.gold1,
    letterSpacing: 2,
  },
  sub: {
    fontFamily: fontes.corpo,
    fontSize: 15,
    color: cores.muted,
    marginTop: espaco.xs,
  },
  dinheiro: {
    fontFamily: fontes.corpo,
    fontSize: 17,
    color: cores.moneyLight,
    marginTop: espaco.xs,
    marginBottom: espaco.sm,
  },
  lista: { gap: espaco.sm },
  itemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: cores.bg,
    borderRadius: 3,
    paddingVertical: espaco.sm,
    paddingHorizontal: espaco.md,
  },
  itemInfo: { flex: 1 },
  itemNome: {
    fontFamily: fontes.corpo,
    fontSize: 19,
    color: cores.cream,
  },
  itemMeta: {
    fontFamily: fontes.corpo,
    fontSize: 14,
    color: cores.muted,
  },
  itemBtn: { minWidth: 76 },
  fechar: {
    marginTop: espaco.md,
    alignItems: 'center',
    paddingVertical: espaco.sm,
  },
  fecharTxt: {
    fontFamily: fontes.titulo,
    fontSize: 13,
    color: cores.muted,
    letterSpacing: 1,
  },
});
