"""
API de Licenças — Monitor de Guias Unimed
==========================================
Backend Flask com persistência via Supabase.

Variáveis de ambiente necessárias no Render:
    SUPABASE_URL    - URL do projeto Supabase (https://xxx.supabase.co)
    SUPABASE_KEY    - Secret key (service_role) do Supabase
    ADMIN_SENHA     - Senha do admin para criar/listar/renovar licenças

Instalar:
    pip install -r requirements.txt

Rodar local:
    python api_licencas_app.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
import os

app = Flask(__name__)
CORS(app)

# ─── Configuração do Supabase ─────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ADMIN_SENHA = os.environ.get("ADMIN_SENHA", "admin123")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  AVISO: SUPABASE_URL e/ou SUPABASE_KEY não configuradas.")
    print("    A API não funcionará corretamente até que sejam definidas.")
    supabase: Client = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ─── Helpers ──────────────────────────────────────────────────

def _autorizado(req) -> bool:
    """Confere a senha de admin."""
    if req.is_json and req.json:
        senha = req.json.get("senha")
    else:
        senha = req.args.get("senha")
    return senha == ADMIN_SENHA


def _agora_iso() -> str:
    """Datetime atual em UTC ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def _validade_iso(meses: int) -> str:
    """Calcula data de validade a partir de hoje, em UTC ISO 8601."""
    return (datetime.now(timezone.utc) + timedelta(days=30 * meses)).isoformat()


def _buscar_licenca(chave: str):
    """Busca uma licença pelo campo `chave`. Retorna dict ou None."""
    if not supabase:
        return None
    resp = supabase.table("licencas").select("*").eq("chave", chave).limit(1).execute()
    if resp.data and len(resp.data) > 0:
        return resp.data[0]
    return None


# ─── Rotas ────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "Monitor Guias API online",
        "versao": "2.0",
        "backend": "supabase" if supabase else "não configurado",
    })


@app.route("/health", methods=["GET"])
def health():
    """Healthcheck — útil pro Render saber se a app está viva."""
    if not supabase:
        return jsonify({"ok": False, "erro": "supabase não configurado"}), 503
    try:
        # Faz um count rápido pra ver se o banco responde
        supabase.table("licencas").select("chave", count="exact").limit(1).execute()
        return jsonify({"ok": True, "backend": "supabase"}), 200
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 503


@app.route("/validar", methods=["POST"])
def validar():
    """Valida uma chave de licença (chamado pelo app cliente)."""
    if not supabase:
        return jsonify({"valido": False, "mensagem": "Servidor de licenças indisponível."}), 503

    data = request.json or {}
    chave = data.get("chave", "").strip().upper()
    crm = data.get("crm", "").strip()
    machine_id = data.get("machine_id", "")

    if not chave or not crm:
        return jsonify({"valido": False, "mensagem": "Chave e CRM são obrigatórios."}), 400

    try:
        lic = _buscar_licenca(chave)
    except Exception as e:
        return jsonify({"valido": False, "mensagem": f"Erro ao consultar servidor: {str(e)[:80]}"}), 500

    if not lic:
        return jsonify({"valido": False, "mensagem": "Chave não encontrada. Verifique e tente novamente."}), 200

    # Verifica CRM (se já estava vinculado a outro)
    if lic.get("crm") and lic["crm"] != crm:
        return jsonify({"valido": False, "mensagem": "CRM não corresponde à chave informada."}), 200

    # Verifica expiração
    valida_ate = lic.get("valida_ate")
    if valida_ate:
        try:
            dt_valida = datetime.fromisoformat(valida_ate.replace("Z", "+00:00"))
            if dt_valida < datetime.now(timezone.utc):
                return jsonify({"valido": False, "mensagem": "Licença expirada. Renove sua assinatura."}), 200
        except Exception:
            pass  # Se a data estiver malformada, não bloqueia

    # Verifica vínculo de máquina
    if lic.get("machine_id") and lic["machine_id"] != machine_id:
        return jsonify({
            "valido": False,
            "mensagem": "Esta chave já está ativa em outro computador. Entre em contato com o suporte."
        }), 200

    # Atualiza vínculo (primeira ativação ou refresh)
    update_data = {
        "machine_id": machine_id,
        "crm": crm,
    }
    if not lic.get("ativada_em"):
        update_data["ativada_em"] = _agora_iso()

    try:
        supabase.table("licencas").update(update_data).eq("chave", chave).execute()
    except Exception as e:
        return jsonify({"valido": False, "mensagem": f"Erro ao salvar ativação: {str(e)[:80]}"}), 500

    return jsonify({
        "valido": True,
        "nome": lic.get("nome", "Dr."),
        "valida_ate": valida_ate,
        "mensagem": "Licença válida!",
    }), 200


@app.route("/licencas", methods=["GET"])
def listar_licencas():
    """Lista todas as licenças (admin)."""
    if not _autorizado(request):
        return jsonify({"erro": "Não autorizado"}), 401
    if not supabase:
        return jsonify({"erro": "Supabase não configurado"}), 503

    try:
        resp = supabase.table("licencas").select("*").order("criada_em", desc=True).execute()
        return jsonify(resp.data or [])
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/criar", methods=["POST"])
def criar_licenca():
    """Cria uma nova licença (admin)."""
    if not _autorizado(request):
        return jsonify({"erro": "Não autorizado"}), 401
    if not supabase:
        return jsonify({"erro": "Supabase não configurado"}), 503

    data = request.json or {}
    chave = data.get("chave", "").strip().upper()
    nome = data.get("nome", "")
    crm = data.get("crm", "")
    plano = data.get("plano", "mensal")  # mensal, anual

    if not chave:
        return jsonify({"erro": "Chave é obrigatória"}), 400

    # Verifica duplicata
    try:
        existente = _buscar_licenca(chave)
        if existente:
            return jsonify({"erro": "Chave já existe. Use /renovar para estender a validade."}), 409
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

    meses = 12 if plano == "anual" else 1
    valida_ate = _validade_iso(meses)

    novo = {
        "chave": chave,
        "nome": nome,
        "crm": crm,
        "plano": plano,
        "valida_ate": valida_ate,
        "criada_em": _agora_iso(),
        "machine_id": None,
        "ativada_em": None,
    }

    try:
        supabase.table("licencas").insert(novo).execute()
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

    return jsonify({"sucesso": True, "chave": chave, "valida_ate": valida_ate})


@app.route("/renovar", methods=["POST"])
def renovar_licenca():
    """Renova uma licença existente (admin)."""
    if not _autorizado(request):
        return jsonify({"erro": "Não autorizado"}), 401
    if not supabase:
        return jsonify({"erro": "Supabase não configurado"}), 503

    data = request.json or {}
    chave = data.get("chave", "").strip().upper()
    plano = data.get("plano", "mensal")

    if not chave:
        return jsonify({"erro": "Chave é obrigatória"}), 400

    try:
        lic = _buscar_licenca(chave)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

    if not lic:
        return jsonify({"erro": "Chave não encontrada"}), 404

    meses = 12 if plano == "anual" else 1
    # Renova A PARTIR DE HOJE — comportamento simples e previsível.
    # Se quiser somar à data atual de validade (estender em vez de resetar),
    # troque por: a partir de max(hoje, valida_ate) some os meses.
    valida_ate = _validade_iso(meses)

    try:
        supabase.table("licencas").update({
            "valida_ate": valida_ate,
            "plano": plano,
        }).eq("chave", chave).execute()
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

    return jsonify({"sucesso": True, "chave": chave, "valida_ate": valida_ate})


@app.route("/desvincular", methods=["POST"])
def desvincular_licenca():
    """
    Desvincula uma licença de uma máquina (admin).
    Útil quando o cliente troca de computador e precisa reativar.
    """
    if not _autorizado(request):
        return jsonify({"erro": "Não autorizado"}), 401
    if not supabase:
        return jsonify({"erro": "Supabase não configurado"}), 503

    data = request.json or {}
    chave = data.get("chave", "").strip().upper()

    if not chave:
        return jsonify({"erro": "Chave é obrigatória"}), 400

    try:
        lic = _buscar_licenca(chave)
        if not lic:
            return jsonify({"erro": "Chave não encontrada"}), 404

        supabase.table("licencas").update({"machine_id": None}).eq("chave", chave).execute()
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

    return jsonify({"sucesso": True, "chave": chave, "mensagem": "Vínculo de máquina removido."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
