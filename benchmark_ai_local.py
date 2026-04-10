#!/usr/bin/env python3
"""Benchmark de modelos GGUF locais para o AI gate do scalping bot.

Testa latencia, uso de RAM, e qualidade de output para decidir
se um modelo local pode substituir Claude Haiku no AI gate.

Cada modelo usa o seu prompt template nativo para evitar
falsos PARSE_FAIL (ChatML para Qwen, [INST] para TinyLlama,
plain text para Phi-2).
"""

import subprocess
import time
import json
import os
import psutil

# ── Configuracao ────────────────────────────────────────────────────────────

# Base paths configuraveis via env var (default: home do user actual)
LLAMA_HOME = os.environ.get("LLAMA_HOME", os.path.expanduser("~/llama.cpp"))
MODELS_DIR = os.environ.get("MODELS_DIR", os.path.expanduser("~/models"))

LLAMA_CLI = os.path.join(LLAMA_HOME, "build", "bin", "llama-cli")
# Fallback se compilado com make:
if not os.path.exists(LLAMA_CLI):
    LLAMA_CLI = os.path.join(LLAMA_HOME, "main")

SYSTEM_PROMPT = (
    "Voce e um validador rapido de trade de scalping. "
    "Recebe dados de confluencia de 3 motores de sinal. "
    'Responda SOMENTE com JSON: {"approved": true/false, "reason": "motivo curto"} '
    "Aprove se a confluencia faz sentido. Rejeite se ha risco claro."
)

# Prompt templates nativos de cada modelo
def _format_prompt_chatml(system: str, user: str) -> str:
    """ChatML — Qwen2.5"""
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

def _format_prompt_llama(system: str, user: str) -> str:
    """Llama [INST] — TinyLlama"""
    return f"[INST] <<SYS>>\n{system}\n<</SYS>>\n\n{user} [/INST]"

def _format_prompt_plain(system: str, user: str) -> str:
    """Plain text — Phi-2 (nao tem chat template oficial)"""
    return (
        f"Instruct: {system}\n\n{user}\n\n"
        f"Output:"
    )

MODELS = {
    "qwen2.5-0.5b-q8": {
        "path": os.path.join(MODELS_DIR, "qwen2.5-0.5b-instruct-q8_0.gguf"),
        "formatter": _format_prompt_chatml,
    },
    "tinyllama-1.1b-q4": {
        "path": os.path.join(MODELS_DIR, "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"),
        "formatter": _format_prompt_llama,
    },
    "phi2-2.7b-q4": {
        "path": os.path.join(MODELS_DIR, "phi-2.Q4_K_M.gguf"),
        "formatter": _format_prompt_plain,
    },
}

# 5 cenarios de teste — misturam aprovacoes e rejeicoes obvias
TEST_CASES = [
    {
        "name": "BTC LONG 2/3 — funding negativo (deve aprovar)",
        "prompt": (
            "Ativo: BTCUSDT\nDirecao: LONG\nConfluencia: 2/3\n"
            "Motores ativos: funding_rate + oi_divergence\n"
            "Motor principal: funding_rate"
        ),
        "expected_approved": True,
    },
    {
        "name": "ETH SHORT 2/3 — liquidacao intensa (deve aprovar)",
        "prompt": (
            "Ativo: ETHUSDT\nDirecao: SHORT\nConfluencia: 2/3\n"
            "Motores ativos: liquidation_cascade + basis_spread\n"
            "Motor principal: liquidation_cascade"
        ),
        "expected_approved": True,
    },
    {
        "name": "SOL LONG 2/3 — apenas LS ratio (deve rejeitar)",
        "prompt": (
            "Ativo: SOLUSDT\nDirecao: LONG\nConfluencia: 2/3\n"
            "Motores ativos: ls_ratio_extreme + ls_ratio_extreme\n"
            "Motor principal: ls_ratio_extreme"
        ),
        "expected_approved": False,
    },
    {
        "name": "BNB SHORT 2/3 — funding positivo + OI subindo (contraditorio, deve rejeitar)",
        "prompt": (
            "Ativo: BNBUSDT\nDirecao: SHORT\nConfluencia: 2/3\n"
            "Motores ativos: funding_rate + oi_divergence\n"
            "Motor principal: funding_rate"
        ),
        "expected_approved": False,
    },
    {
        "name": "XRP LONG 2/3 — cascade + basis (deve aprovar)",
        "prompt": (
            "Ativo: XRPUSDT\nDirecao: LONG\nConfluencia: 2/3\n"
            "Motores ativos: liquidation_cascade + basis_spread\n"
            "Motor principal: liquidation_cascade"
        ),
        "expected_approved": True,
    },
]


def run_inference(model_cfg: dict, prompt: str, n_predict: int = 64) -> dict:
    """Roda inferencia com llama-cli e mede performance."""

    model_path = model_cfg["path"]
    formatter = model_cfg["formatter"]
    full_prompt = formatter(SYSTEM_PROMPT, prompt)

    ram_before = psutil.virtual_memory().used / (1024 ** 2)  # MB

    start = time.time()
    try:
        result = subprocess.run(
            [
                LLAMA_CLI,
                "-m", model_path,
                "-p", full_prompt,
                "-n", str(n_predict),
                "--temp", "0.1",
                "--top-k", "1",       # quasi-deterministico
                "--no-display-prompt",
                "-ngl", "0",          # sem GPU (Pi nao tem)
                "--threads", "4",     # usar os 4 cores
            ],
            capture_output=True,
            text=True,
            timeout=30,  # timeout de 30s
        )
        elapsed = time.time() - start
        output = result.stdout.strip()
        stderr_tail = result.stderr[-200:] if result.stderr else ""
    except subprocess.TimeoutExpired:
        elapsed = 30.0
        output = "TIMEOUT"
        stderr_tail = ""
    except Exception as e:
        elapsed = time.time() - start
        output = f"ERROR: {e}"
        stderr_tail = ""

    ram_after = psutil.virtual_memory().used / (1024 ** 2)

    # Tentar parsear JSON do output
    approved = None
    reason = ""
    try:
        # Procurar JSON no output (pode ter lixo antes/depois)
        json_start = output.find("{")
        json_end = output.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(output[json_start:json_end])
            approved = parsed.get("approved")
            reason = parsed.get("reason", "")
    except (json.JSONDecodeError, ValueError):
        pass

    return {
        "elapsed_s": round(elapsed, 2),
        "ram_delta_mb": round(ram_after - ram_before, 1),
        "raw_output": output[:200],  # truncar para legibilidade
        "stderr_tail": stderr_tail,
        "json_valid": approved is not None,
        "approved": approved,
        "reason": reason,
    }


def benchmark():
    """Roda benchmark completo e imprime resultados."""

    print("=" * 70)
    print("BENCHMARK AI LOCAL — Raspberry Pi 4")
    print(f"RAM total: {psutil.virtual_memory().total / (1024**2):.0f} MB")
    print(f"RAM livre: {psutil.virtual_memory().available / (1024**2):.0f} MB")
    print(f"CPU: {psutil.cpu_count()} cores")
    print(f"llama-cli: {LLAMA_CLI}")
    print("=" * 70)

    results = {}

    for model_name, model_cfg in MODELS.items():
        model_path = model_cfg["path"]
        if not os.path.exists(model_path):
            print(f"\n[SKIP] {model_name} — ficheiro nao encontrado: {model_path}")
            continue

        print(f"\n{'─' * 70}")
        print(f"MODELO: {model_name}")
        print(f"Ficheiro: {model_path}")
        print(f"Tamanho: {os.path.getsize(model_path) / (1024**2):.0f} MB")
        print(f"Template: {model_cfg['formatter'].__doc__}")
        print(f"{'─' * 70}")

        model_results = []

        for i, tc in enumerate(TEST_CASES):
            print(f"\n  Teste {i+1}/5: {tc['name']}")

            res = run_inference(model_cfg, tc["prompt"])
            res["test_name"] = tc["name"]
            res["expected_approved"] = tc["expected_approved"]
            res["correct"] = (
                res["approved"] == tc["expected_approved"]
                if res["approved"] is not None
                else False
            )

            model_results.append(res)

            status = "OK" if res["correct"] else ("WRONG" if res["json_valid"] else "PARSE_FAIL")
            print(f"    Latencia: {res['elapsed_s']}s | JSON valido: {res['json_valid']} | "
                  f"Resultado: {status}")
            if res["reason"]:
                print(f"    Razao: {res['reason']}")
            if not res["json_valid"]:
                print(f"    Output bruto: {res['raw_output'][:100]}")

        # Resumo do modelo
        latencies = [r["elapsed_s"] for r in model_results]
        json_ok = sum(1 for r in model_results if r["json_valid"])
        correct = sum(1 for r in model_results if r["correct"])

        results[model_name] = {
            "avg_latency_s": round(sum(latencies) / len(latencies), 2),
            "max_latency_s": max(latencies),
            "min_latency_s": min(latencies),
            "json_parse_rate": f"{json_ok}/5",
            "accuracy": f"{correct}/5",
            "results": model_results,
        }

        print(f"\n  RESUMO {model_name}:")
        print(f"    Latencia media: {results[model_name]['avg_latency_s']}s")
        print(f"    Latencia max:   {results[model_name]['max_latency_s']}s")
        print(f"    JSON valido:    {json_ok}/5")
        print(f"    Acerto:         {correct}/5")

    # Resumo final
    print(f"\n{'=' * 70}")
    print("RESUMO FINAL — DECISAO")
    print(f"{'=' * 70}")

    viable_models = []
    for model_name, r in results.items():
        json_count = int(r["json_parse_rate"].split("/")[0])
        acc_count = int(r["accuracy"].split("/")[0])
        viable = (
            r["avg_latency_s"] < 3.0
            and json_count >= 4
            and acc_count >= 3
        )
        verdict = "VIAVEL" if viable else "INVIAVEL"
        if viable:
            viable_models.append(model_name)
        print(f"  {model_name}: {verdict}")
        print(f"    Latencia avg={r['avg_latency_s']}s | JSON={r['json_parse_rate']} | Acerto={r['accuracy']}")

    print(f"\nCriterios: latencia <3s, JSON valido >=4/5, acerto >=3/5")

    if viable_models:
        print(f"\nMODELOS VIAVEIS: {', '.join(viable_models)}")
        print("Proximo passo: activar ai_gate_local.py com o melhor modelo.")
    else:
        print("\nNenhum modelo viavel. Manter Haiku API quando creditos disponiveis.")

    # Guardar resultados em JSON
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "benchmark_ai_local.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResultados guardados em: {out_path}")


if __name__ == "__main__":
    benchmark()
