"""Testes da Fatia Risco do Copiloto (avalia_risco + /risco + /banca).

O cerebro e determinístico → asserts numéricos exatos (com approx pra float). A regra de ouro:
o fee morde os DOIS lados (encolhe o premio E engorda o risco), o R:R bruto mente, o liquido nao.
Nada aqui preve direcao — so diz se o trade paga o pedagio.
"""
import sqlite3

import pytest

import copiloto


@pytest.fixture(autouse=True)
def _sem_env_banca(monkeypatch):
    # isola os testes do env COPILOTO_BANCA (nao deve vazar entre casos)
    monkeypatch.delenv("COPILOTO_BANCA", raising=False)


# ─────────────────────── A. matemática do R:R líquido ───────────────────────

def test_compra_numeros_de_referencia():
    # 7.50/7.20/8.40, banca 2000, risco 0.5%, fee 0.10% → o exemplo canonico do blueprint
    r = copiloto.avalia_risco(7.50, 7.20, alvo=8.40, banca=2000, risk_pct=0.5, fee_rt_pct=0.10)
    assert r["direction"] == "compra"
    assert r["rr_gross"] == pytest.approx(3.0, abs=0.01)
    assert r["rr_net"] == pytest.approx(2.9, abs=0.01)
    assert r["net_risk_pct"] == pytest.approx(4.1, abs=0.01)
    assert r["net_reward_pct"] == pytest.approx(11.9, abs=0.01)
    assert r["breakeven_wr"] == pytest.approx(0.256, abs=0.002)
    assert r["breakeven_price"] == pytest.approx(7.5075, abs=0.0001)
    assert r["risk_amount"] == pytest.approx(10.0, abs=0.01)
    assert r["notional"] == pytest.approx(243.9, abs=0.1)
    assert r["qty"] == pytest.approx(32.52, abs=0.01)
    assert r["veredito"] == "bom"


def test_venda_short_simetrica():
    r = copiloto.avalia_risco(100.0, 103.0, alvo=94.0, fee_rt_pct=0.10)
    assert r["direction"] == "venda"
    assert r["risk_frac_pct"] == pytest.approx(3.0, abs=0.01)
    assert r["rr_gross"] == pytest.approx(2.0, abs=0.01)   # 6% / 3%
    assert r["rr_net"] == pytest.approx(1.9, abs=0.05)     # (6-0.1)/(3+0.1)
    assert r["veredito"] == "magro"


# ─────────────────────── B. o fee é a estrela (lição do momentum) ───────────────────────

def test_fee_morde_os_dois_lados():
    sem = copiloto.avalia_risco(7.50, 7.20, alvo=8.40, fee_rt_pct=0.0)
    com = copiloto.avalia_risco(7.50, 7.20, alvo=8.40, fee_rt_pct=0.10)
    # sem fee, liquido == bruto; com fee, o liquido CAI (fee nos dois lados)
    assert sem["rr_net"] == pytest.approx(sem["rr_gross"], abs=0.001)
    assert com["rr_net"] < com["rr_gross"]


def test_stop_curto_o_fee_mata():
    # BTC 60000/59900/60200: stop de 0.17%, o fee de 0.10% domina → reprova
    r = copiloto.avalia_risco(60000.0, 59900.0, alvo=60200.0, fee_rt_pct=0.10)
    assert r["veredito"] == "reprova"
    assert r["rr_net"] < 1.0
    assert r["rr_gross"] == pytest.approx(2.0, abs=0.01)   # bruto engana: parece 2:1
    assert any("fee" in a for a in r["avisos"])            # aviso de pedagio pesado


# ─────────────────────── C. veredito por lógica (breakeven-WR) ───────────────────────

def test_rr_net_2_e_bom():
    # entry 100, stop 99 (risk 1%), fee 0.10% → net_risk 1.1%; alvo 102.3 → net_reward 2.2% → rr_net 2.0
    r = copiloto.avalia_risco(100.0, 99.0, alvo=102.3, fee_rt_pct=0.10)
    assert r["rr_net"] == pytest.approx(2.0, abs=0.01)
    assert r["veredito"] == "bom"
    assert r["breakeven_wr"] == pytest.approx(0.333, abs=0.003)


def test_rr_net_entre_1_e_2_e_magro():
    r = copiloto.avalia_risco(100.0, 99.0, alvo=101.75, fee_rt_pct=0.10)
    assert 1.0 <= r["rr_net"] < 2.0
    assert r["veredito"] == "magro"


def test_premio_menor_que_fee_reprova():
    # alvo mal acima da entrada: o ganho bruto nao paga nem o pedagio → net_reward <= 0
    r = copiloto.avalia_risco(100.0, 99.0, alvo=100.05, fee_rt_pct=0.10)
    assert r["veredito"] == "reprova"


# ─────────────────────── D. sizing / no-leverage ───────────────────────

def test_worst_case_bate_o_orcamento_quando_nao_capado():
    # sem cap: a perda real (com fee) tem que ser == risk_amount (divide pelo risco LIQUIDO)
    r = copiloto.avalia_risco(100.0, 95.0, banca=2000, risk_pct=0.5, fee_rt_pct=0.10)
    assert not r["notional_capped"]
    perda_real = r["notional"] * (r["net_risk_pct"] / 100.0)
    assert perda_real == pytest.approx(r["risk_amount"], abs=0.05)


def test_stop_colado_capa_na_banca_sem_alavancagem():
    # stop de 0.01%: pra arriscar 0.5% precisaria alavancar → capa na banca e admite risco real menor
    r = copiloto.avalia_risco(100.0, 99.99, banca=2000, risk_pct=0.5, fee_rt_pct=0.10)
    assert r["notional_capped"]
    assert r["notional"] == pytest.approx(2000, abs=0.01)
    assert r["risk_real_pct"] is not None and r["risk_real_pct"] < 0.5
    assert any("alavancagem" in a for a in r["avisos"])


# ─────────────────────── E. blocos independentes ───────────────────────

def test_sem_banca_da_veredito_mas_nao_tamanho():
    r = copiloto.avalia_risco(7.50, 7.20, alvo=8.40, banca=None, fee_rt_pct=0.10)
    assert r["rr_net"] is not None
    assert r["risk_amount"] is None and r["notional"] is None and r["qty"] is None


def test_sem_alvo_da_tamanho_mas_nao_veredito():
    r = copiloto.avalia_risco(7.50, 7.20, alvo=None, banca=2000, fee_rt_pct=0.10)
    assert r["rr_net"] is None and r["veredito"] is None
    assert r["notional"] is not None
    # os alvos-alvo saem sempre (pra guiar "mira em pelo menos")
    assert r["alvo_1a1"] > 7.50 and r["alvo_2a1"] > r["alvo_1a1"]


# ─────────────────────── F. edge cases ───────────────────────

def test_stop_igual_entrada_erro():
    assert "erro" in copiloto.avalia_risco(100.0, 100.0)


def test_precos_nao_positivos_erro():
    assert "erro" in copiloto.avalia_risco(0, 10)
    assert "erro" in copiloto.avalia_risco(10, -1)


def test_alvo_do_lado_errado_reprova():
    # compra com alvo ABAIXO da entrada → R:R negativo
    r = copiloto.avalia_risco(100.0, 95.0, alvo=98.0, fee_rt_pct=0.10)
    assert r["veredito"] == "reprova"
    assert any("lado errado" in a for a in r["avisos"])


def test_risk_pct_fora_do_perfil_e_clampado():
    r = copiloto.avalia_risco(100.0, 95.0, banca=2000, risk_pct=3.0, fee_rt_pct=0.10)
    assert any("risco/trade" in a for a in r["avisos"])
    # 3.0 clampado a 2.0 → risk_amount = 2000 * 2/100 = 40
    assert r["risk_amount"] == pytest.approx(40.0, abs=0.01)


def test_direction_explicito_incoerente_com_stop_erro():
    # forcar 'compra' com stop ACIMA da entrada → risco negativo → erro defensivo
    assert "erro" in copiloto.avalia_risco(100.0, 105.0, direction="compra")


# ─────────────────────── G. parsing tolerante (cmd_risco) ───────────────────────

def test_cmd_risco_parsing_tolerante(tmp_path):
    db = str(tmp_path / "b.db")
    out = copiloto.cmd_risco("linkusdt 7,50 stop 7,20 alvo 8,40 banca 2000", _db=db)
    assert "LINKUSDT" in out                    # symbol uppercased
    assert "R/R líquido" in out                 # veredito presente
    assert "A decisão é sua" in out             # sempre fecha com a decisao dele
    assert "Tamanho" in out                     # banca inline consumida → dimensionou


def test_cmd_risco_uso_quando_faltam_numeros(tmp_path):
    db = str(tmp_path / "b.db")
    out = copiloto.cmd_risco("LINKUSDT", _db=db)
    assert "Uso:" in out


def test_cmd_risco_sem_banca_pede_pra_setar(tmp_path):
    db = str(tmp_path / "b.db")
    out = copiloto.cmd_risco("LINKUSDT 7.50 7.20 8.40", _db=db)
    assert "/banca" in out                      # dica pra setar a banca
    assert "R/R líquido" in out                 # veredito nao depende de banca


def test_cmd_risco_stop_igual_entrada(tmp_path):
    db = str(tmp_path / "b.db")
    out = copiloto.cmd_risco("LINKUSDT 7.50 7.50", _db=db)
    assert "stop igual" in out


# ─────────────────────── H. settings I/O + cascata ───────────────────────

def test_settings_round_trip(tmp_path):
    db = str(tmp_path / "b.db")
    conn = copiloto._conn(db)
    copiloto.ensure_schema(conn)
    copiloto.set_setting(conn, "banca", 2500)
    assert copiloto.get_setting(conn, "banca") == "2500"
    assert copiloto.get_setting(conn, "inexistente", "def") == "def"
    conn.close()


def test_resolve_cascata_inline_ganha(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    conn = copiloto._conn(db)
    copiloto.ensure_schema(conn)
    copiloto.set_setting(conn, "banca", 1000)
    conn.close()
    monkeypatch.setenv("COPILOTO_BANCA", "9999")
    banca, _ = copiloto._resolve_banca_risco(inline_banca=500, db_path=db)
    assert banca == 500                          # inline > setting > env


def test_resolve_cascata_env_por_ultimo(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    monkeypatch.setenv("COPILOTO_BANCA", "777")
    banca, _ = copiloto._resolve_banca_risco(db_path=db)
    assert banca == 777                          # sem inline nem setting → env


def test_resolve_ausente_da_none(tmp_path):
    db = str(tmp_path / "b.db")
    banca, risk = copiloto._resolve_banca_risco(db_path=db)
    assert banca is None and risk == pytest.approx(0.5)


# ─────────────────────── I. backward-compat do /entrei ───────────────────────

def test_entrei_sem_banca_mensagem_identica(tmp_path):
    db = str(tmp_path / "b.db")
    out = copiloto.cmd_entrei("LINKUSDT 7.50 stop 7.20", _db=db)
    assert "Vigiando" in out
    assert "Tamanho" not in out                  # sem banca → nenhuma linha extra


def test_entrei_com_banca_sugere_tamanho(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.cmd_banca("2000", _db=db)
    out = copiloto.cmd_entrei("LINKUSDT 7.50 stop 7.20", _db=db)
    assert "Vigiando" in out
    assert "Tamanho" in out and "USDT" in out     # linha de sizing presente


# ─────────────────────── J. cmd_banca ───────────────────────

def test_cmd_banca_grava_e_mostra(tmp_path):
    db = str(tmp_path / "b.db")
    assert "não setada" in copiloto.cmd_banca("", _db=db)
    copiloto.cmd_banca("2000", _db=db)
    mostra = copiloto.cmd_banca("", _db=db)
    assert "2000" in mostra and "0.5%" in mostra


def test_cmd_banca_ajusta_risco_pct(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.cmd_banca("3000 0.75", _db=db)
    mostra = copiloto.cmd_banca("", _db=db)
    assert "0.75%" in mostra


def test_cmd_banca_clampa_risco(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.cmd_banca("3000 5.0", _db=db)       # 5% clampado ao teto duro de sanidade (2%)
    mostra = copiloto.cmd_banca("", _db=db)
    assert "2%" in mostra


# ─────────────────────── K. correções da revisão adversarial (5 achados 3/3) ───────────────────────

def test_perfil_acima_de_075_avisa_mas_nao_clampa():
    # 1.0% está DENTRO do clamp duro [0.1,2.0] mas ACIMA do teto do perfil (0.75) → avisa, sem clampar
    r = copiloto.avalia_risco(100.0, 95.0, banca=2000, risk_pct=1.0, fee_rt_pct=0.10)
    assert any("acima do teu perfil" in a for a in r["avisos"])
    assert r["risk_amount"] == pytest.approx(20.0, abs=0.01)   # 1% de 2000 (nao clampou pra 0.75)


def test_cmd_banca_nao_chama_over_risk_de_conservador(tmp_path):
    db = str(tmp_path / "b.db")
    ok = copiloto.cmd_banca("3000 0.75", _db=db)      # no teto → conservador
    assert "Conservador" in ok
    over = copiloto.cmd_banca("3000 1.0", _db=db)      # acima do teto → avisa, nao endossa
    assert "Conservador" not in over and "acima do teu perfil" in over


def test_cmd_banca_recusa_banca_nao_positiva(tmp_path):
    db = str(tmp_path / "b.db")
    assert "positiva" in copiloto.cmd_banca("-500", _db=db)
    assert "positiva" in copiloto.cmd_banca("0", _db=db)
    # nada foi gravado
    assert "não setada" in copiloto.cmd_banca("", _db=db)


def test_nan_inf_nao_furam_o_guard():
    assert "erro" in copiloto.avalia_risco(float("nan"), 95.0)
    assert "erro" in copiloto.avalia_risco(100.0, float("inf"))
    assert copiloto._is_float("nan") is False and copiloto._is_float("inf") is False


def test_env_banca_malformado_nao_quebra(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    monkeypatch.setenv("COPILOTO_BANCA", "não-é-número")
    banca, risk = copiloto._resolve_banca_risco(db_path=db)
    assert banca is None                                # cai em None em vez de estourar
    # e o comando ainda responde (nao crasha)
    out = copiloto.cmd_risco("LINKUSDT 7.50 7.20 8.40", _db=db)
    assert "R/R líquido" in out


def test_entrei_capado_admite_risco_real_menor(tmp_path):
    db = str(tmp_path / "b.db")
    copiloto.cmd_banca("2000", _db=db)
    # stop coladíssimo → notional capa na banca; /entrei tem que ADMITIR, não mascarar
    out = copiloto.cmd_entrei("BTCUSDT 100 stop 99.99", _db=db)
    assert "sem alavancagem" in out and "risco real" in out
    assert "Tamanho p/ 0.5% da banca" not in out       # nao apresenta a banca cheia como 0.5%
