"""
API de Licenças — Monitor de Guias Unimed
==========================================
Deploy no Render.com (gratuito para começar)

Instalar:
    pip install flask flask-cors

Rodar local:
    python app.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import os

app = Flask(__name__)
CORS(app)

# ─── Banco de licenças (JSON simples para começar) ────────────
LICENCAS_FILE = "licencas.json"


def _carregar_licencas() -> dict:
    if os.path.exists(LICENCAS_FILE):
        with open(LICENCAS_FILE) as f:
            return json.load(f)
    return {}


def _salvar_licencas(dados: dict):
    with open(LICENCAS_FILE, "w") as f:
        json.dump(dados, f, indent=2)


# ─── Rotas ────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "Monitor Guias API online", "versao": "1.0"})


@app.route("/validar", methods=["POST"])
def validar():
    """Valida uma chave de licença."""
    data = request.json or {}
    chave = data.get("chave", "").strip().upper()
    crm = data.get("crm", "").strip()
    machine_id = data.get("machine_id", "")

    if not chave or not crm:
        return jsonify({"valido": False, "mensagem": "Chave e CRM são obrigatórios."}), 400

    licencas = _carregar_licencas()

    if chave not in licencas:
        return jsonify({"valido": False, "mensagem": "Chave não encontrada. Verifique e tente novamente."}), 200

    lic = licencas[chave]

    # Verifica CRM
    if lic.get("crm") and lic["crm"] != crm:
        return jsonify({"valido": False, "mensagem": "CRM não corresponde à chave informada."}), 200

    # Verifica expiração
    valida_ate = lic.get("valida_ate")
    if valida_ate and datetime.fromisoformat(valida_ate) < datetime.now():
        return jsonify({"valido": False, "mensagem": "Licença expirada. Renove sua assinatura."}), 200

    # Verifica se já está vinculada a outra máquina
    if lic.get("machine_id") and lic["machine_id"] != machine_id:
        return jsonify({"valido": False, "mensagem": "Esta chave já está ativa em outro computador. Entre em contato com o suporte."}), 200

    # Vincula máquina se ainda não vinculada
    lic["machine_id"] = machine_id
    lic["crm"] = crm
    lic["ativada_em"] = lic.get("ativada_em") or datetime.now().isoformat()
    licencas[chave] = lic
    _salvar_licencas(licencas)

    return jsonify({
        "valido": True,
        "nome": lic.get("nome", "Dr."),
        "valida_ate": valida_ate,
        "mensagem": "Licença válida!",
    }), 200


@app.route("/licencas", methods=["GET"])
def listar_licencas():
    """Lista todas as licenças (protegido por senha admin)."""
    senha = request.args.get("senha")
    if senha != os.environ.get("ADMIN_SENHA", "admin123"):
        return jsonify({"erro": "Não autorizado"}), 401
    return jsonify(_carregar_licencas())


@app.route("/criar", methods=["POST"])
def criar_licenca():
    """Cria uma nova licença."""
    senha = request.json.get("senha")
    if senha != os.environ.get("ADMIN_SENHA", "admin123"):
        return jsonify({"erro": "Não autorizado"}), 401

    data = request.json
    chave = data.get("chave", "").strip().upper()
    nome = data.get("nome", "")
    crm = data.get("crm", "")
    plano = data.get("plano", "mensal")  # mensal, anual

    if not chave:
        return jsonify({"erro": "Chave é obrigatória"}), 400

    # Define validade
    meses = 12 if plano == "anual" else 1
    valida_ate = (datetime.now() + timedelta(days=30 * meses)).isoformat()

    licencas = _carregar_licencas()
    licencas[chave] = {
        "nome": nome,
        "crm": crm,
        "plano": plano,
        "valida_ate": valida_ate,
        "criada_em": datetime.now().isoformat(),
        "machine_id": None,
        "ativada_em": None,
    }
    _salvar_licencas(licencas)

    return jsonify({"sucesso": True, "chave": chave, "valida_ate": valida_ate})


@app.route("/renovar", methods=["POST"])
def renovar_licenca():
    """Renova uma licença existente."""
    senha = request.json.get("senha")
    if senha != os.environ.get("ADMIN_SENHA", "admin123"):
        return jsonify({"erro": "Não autorizado"}), 401

    chave = request.json.get("chave", "").strip().upper()
    plano = request.json.get("plano", "mensal")

    licencas = _carregar_licencas()
    if chave not in licencas:
        return jsonify({"erro": "Chave não encontrada"}), 404

    meses = 12 if plano == "anual" else 1
    valida_ate = (datetime.now() + timedelta(days=30 * meses)).isoformat()
    licencas[chave]["valida_ate"] = valida_ate
    _salvar_licencas(licencas)

    return jsonify({"sucesso": True, "chave": chave, "valida_ate": valida_ate})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
