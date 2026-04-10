"""AI gate local usando llama.cpp via subprocess.

Substitui Claude Haiku para validacao de trades borderline (2/3).
Usa o modelo que melhor pontuou no benchmark.
Fallback para Haiku se o modelo local falhar.
"""

import subprocess
import json
import os
import logging

logger = logging.getLogger("scalping.ai_gate_local")

# ── Configuracao do modelo vencedor ─────────────────────────────────────────
# SUBSTITUIR com o modelo que passou no benchmark_ai_local.py
# Paths configuraveis via env var (default: home do user actual)
LLAMA_HOME = os.environ.get("LLAMA_HOME", os.path.expanduser("~/llama.cpp"))
MODELS_DIR = os.environ.get("MODELS_DIR", os.path.expanduser("~/models"))

MODEL_PATH = os.environ.get(
    "AI_GATE_MODEL_PATH",
    os.path.join(MODELS_DIR, "qwen2.5-0.5b-instruct-q8_0.gguf"),
)
MODEL_TEMPLATE = os.environ.get("AI_GATE_MODEL_TEMPLATE", "chatml")  # "chatml" | "llama" | "plain"

LLAMA_CLI = os.path.join(LLAMA_HOME, "build", "bin", "llama-cli")
if not os.path.exists(LLAMA_CLI):
    LLAMA_CLI = os.path.join(LLAMA_HOME, "main")

SYSTEM_PROMPT = (
    "Voce e um validador rapido de trade de scalping. "
    "Recebe dados de confluencia de 3 motores de sinal. "
    'Responda SOMENTE com JSON: {"approved": true/false, "reason": "motivo curto"} '
    "Aprove se a confluencia faz sentido. Rejeite se ha risco claro."
)

# Timeout por inferencia (segundos). O benchmark mede latencia real;
# este valor e o limite absoluto para nao bloquear o ciclo de scalping.
INFERENCE_TIMEOUT = 10


def _format_prompt(system: str, user: str) -> str:
    """Formata prompt no template nativo do modelo configurado."""
    if MODEL_TEMPLATE == "chatml":
        return (
            f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
    elif MODEL_TEMPLATE == "llama":
        return f"[INST] <<SYS>>\n{system}\n<</SYS>>\n\n{user} [/INST]"
    else:  # plain
        return f"Instruct: {system}\n\n{user}\n\nOutput:"


def validate_local(symbol, direction, score, reason, best_signal_source, timeout=None):
    """Validacao local equivalente a validate_scalping_signal de trade_agents.py.

    Returns:
        (approved: bool, reason: str)
    """
    if timeout is None:
        timeout = INFERENCE_TIMEOUT

    if not os.path.exists(MODEL_PATH):
        logger.warning("Modelo local nao encontrado: %s", MODEL_PATH)
        return _fallback_haiku(symbol, direction, score, reason, best_signal_source)

    prompt = (
        f"Ativo: {symbol}\nDirecao: {direction}\nConfluencia: {score}/3\n"
        f"Motores ativos: {reason}\nMotor principal: {best_signal_source}"
    )
    full_prompt = _format_prompt(SYSTEM_PROMPT, prompt)

    try:
        result = subprocess.run(
            [
                LLAMA_CLI,
                "-m", MODEL_PATH,
                "-p", full_prompt,
                "-n", "64",
                "--temp", "0.1",
                "--top-k", "1",
                "-no-cnv",           # single-shot (evita chat mode)
                "--no-display-prompt",
                "-ngl", "0",
                "--threads", "4",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        json_start = output.find("{")
        json_end = output.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(output[json_start:json_end])
            approved = parsed.get("approved", True)
            local_reason = parsed.get("reason", "local model")
            logger.info(
                "AI_LOCAL %s: approved=%s reason=%s",
                symbol, approved, local_reason,
            )
            return approved, f"[LOCAL] {local_reason}"

        # JSON nao parseavel — fallback para Haiku
        logger.warning(
            "AI_LOCAL %s: parse fail, fallback Haiku. Output: %s",
            symbol, output[:100],
        )
        return _fallback_haiku(symbol, direction, score, reason, best_signal_source)

    except subprocess.TimeoutExpired:
        logger.warning("AI_LOCAL %s: timeout %ds, fallback Haiku", symbol, timeout)
        return _fallback_haiku(symbol, direction, score, reason, best_signal_source)

    except Exception as e:
        logger.warning("AI_LOCAL %s: erro %s, fallback Haiku", symbol, e)
        return _fallback_haiku(symbol, direction, score, reason, best_signal_source)


def _fallback_haiku(symbol, direction, score, reason, best_signal_source):
    """Tenta Haiku API como fallback. Se tambem falhar, rejeita (fail-safe)."""
    try:
        from trade_agents import validate_scalping_signal
        approved, haiku_reason = validate_scalping_signal(
            symbol, direction, score, reason, best_signal_source,
        )
        logger.info(
            "AI_FALLBACK_HAIKU %s: approved=%s reason=%s",
            symbol, approved, haiku_reason,
        )
        return approved, f"[HAIKU] {haiku_reason}"
    except Exception as e:
        logger.warning("AI_FALLBACK_HAIKU %s: tambem falhou: %s", symbol, e)
        return False, f"[FAIL-SAFE] local+haiku indisponiveis: {e}"
