import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import imaplib
import json
import math
import os
import re
import secrets
import smtplib
import tempfile
import uuid
import sqlite3
from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Request,
    Form
)

from fastapi.responses import (
    FileResponse,
    RedirectResponse,
    JSONResponse,
    Response
)

from starlette.middleware.sessions import SessionMiddleware

try:
    from extrator import ExtratorAgent
    from Classificar import ClassificarAgent
except Exception as import_erro:
    print("AVISO: agentes de IA indisponíveis:", repr(import_erro))
    ExtratorAgent = None
    ClassificarAgent = None

load_dotenv(Path(__file__).with_name(".env"))

BASE_DIR = Path(__file__).resolve().parent
GITHUB_REPO_URL = "https://github.com/Vini-p11/Paraiba"
APP_VERSION = os.getenv("APP_VERSION", "v1.0.0")


def obter_codigo_versao() -> str:
    sha = os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("GITHUB_SHA") or ""
    if sha:
        return sha[:7]
    try:
        import subprocess
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=2
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/Vini-p11/Paraiba/commits/main",
            headers={"User-Agent": "AgenteFinanceiro/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
            if dados.get("sha"):
                return str(dados["sha"])[:7]
    except Exception:
        pass
    return APP_VERSION


def resolver_arquivo_html(*nomes: str) -> Path:
    for nome in nomes:
        candidato = BASE_DIR / nome
        if candidato.is_file():
            return candidato
    return BASE_DIR / nomes[0]


@asynccontextmanager
async def lifespan(app: FastAPI):
    tarefas = []
    if (
        os.getenv("IMAP_HOST")
        and os.getenv("IMAP_USER")
        and os.getenv("IMAP_PASSWORD")
        and os.getenv("IMAP_OWNER_CPF")
    ):
        tarefas.append(asyncio.create_task(monitorar_caixa_email()))
    if os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"):
        tarefas.append(asyncio.create_task(monitorar_vencimentos()))
    app.state.background_tasks = tarefas
    try:
        yield
    finally:
        for tarefa in tarefas:
            tarefa.cancel()
        if tarefas:
            await asyncio.gather(*tarefas, return_exceptions=True)


app = FastAPI(
    title="Agente Financeiro",
    description="Sistema de processamento de notas fiscais com Agentes de IA",
    version="1.0.0",
    lifespan=lifespan
)

SESSION_SECRET = os.getenv(
    "SESSION_SECRET",
    "chave-local-desenvolvimento"
).strip()


HTTPS_ONLY = (
    os.getenv(
        "HTTPS_ONLY",
        "false"
    ).strip().lower()
    == "true"
)
MAX_PDF_SIZE = 50 * 1024 * 1024
MAX_ARQUIVO_SIZE = 50 * 1024 * 1024
IS_SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
DOCUMENTOS_DIR = (
    Path(tempfile.gettempdir()) / "agente_financeiro_documentos"
    if IS_SERVERLESS
    else Path(__file__).with_name("documentos")
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="finance_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=HTTPS_ONLY
)
try:
    if ExtratorAgent is None or ClassificarAgent is None:
        raise RuntimeError("Dependências dos agentes de IA não estão disponíveis.")
    extrator = ExtratorAgent()
    classificar = ClassificarAgent()
except Exception as erro:
    print(
        "ERRO AO INICIALIZAR OS AGENTES:"
    )
    print(
        repr(erro)
    )
    extrator = None
    classificar = None
trabalhos = {}
def criar_trabalho(
    trabalho_id: str,
    status: str,
    mensagem: str,
    resultado=None
):
    metadados = {
        chave: valor
        for chave, valor in trabalhos.get(trabalho_id, {}).items()
        if chave not in {
            "status", "message", "mensagem", "result", "resultado"
        }
    }
    trabalhos[trabalho_id] = {
        **metadados,

        "status":
        status,
        "message":
        mensagem,
        "mensagem":
        mensagem,
        "result":
        resultado,
        "resultado":
        resultado
    }
@app.get("/")
async def inicio(
    request: Request
):
    if not request.session.get(
        "logado"
    ):
        return RedirectResponse(
            "/login",
            status_code=302
        )
    caminho = resolver_arquivo_html("index.html")
    if not caminho.exists():
        return JSONResponse(status_code=500, content={"detail": "O arquivo index.html não foi encontrado na pasta do projeto."})
    return FileResponse(caminho)

@app.get("/nota-fiscal")
async def pagina_nota_fiscal(request: Request):
    if not request.session.get("logado"):
        return RedirectResponse("/login", status_code=302)
    caminho = resolver_arquivo_html("NotaFiscal.html", "nota_fiscal.html")
    if not caminho.exists():
        return JSONResponse(
            status_code=500,
            content={"detail": "O arquivo nota_fiscal.html não foi encontrado na pasta do projeto."}
        )
    return FileResponse(caminho)


@app.get("/login")
async def pagina_login():
    caminho_login = resolver_arquivo_html("Login.html", "login.html")
    if not caminho_login.exists():
        return JSONResponse(
            status_code=500,
            content={
                "detail":
                "O arquivo login.html não foi encontrado na pasta do projeto."
            }
        )
    return FileResponse(
        caminho_login
    )

@app.post("/login")
async def fazer_login(
    request: Request
):
    try:
        formulario = await request.form()
        login = str(formulario.get("login") or formulario.get("usuario") or "").strip()
        senha = formulario.get(
            "senha"
        )
        usuario_correto = (os.getenv("ADMIN_USER") or os.getenv("LOGIN_USUARIO") or "AnaJamyle_Miguel_Vinicius").strip()
        senha_correta = (os.getenv("ADMIN_PASSWORD") or os.getenv("LOGIN_SENHA") or "poiu7654321").strip()
        prof_usuario = os.getenv("PROFESSOR_USER", "professor").strip()
        prof_senha = os.getenv("PROFESSOR_PASSWORD", "professor123").strip()
        senha_str = str(senha or "").strip()

        if (
            (login == usuario_correto and senha_str == senha_correta)
            or (login.casefold() == prof_usuario.casefold() and senha_str == prof_senha)
        ):
            request.session.clear()
            request.session[
                "logado"
            ] = True
            request.session["papel"] = "admin"
            return RedirectResponse(
                "/",
                status_code=303
            )

        with conectar_db() as conn:
            conta = conn.execute(
                "SELECT id, pessoa_id, senha_hash FROM usuarios WHERE login=? COLLATE NOCASE AND status='ATIVO'",
                (login,)
            ).fetchone()
            if conta and verificar_senha(str(senha or ""), conta["senha_hash"]):
                request.session.clear()
                request.session["logado"] = True
                request.session["usuario_id"] = conta["id"]
                request.session["pessoa_id"] = conta["pessoa_id"]
                request.session["papel"] = "pessoa"
                return RedirectResponse("/", status_code=303)

        return RedirectResponse(
            "/login?erro=1",
            status_code=303
        )


    except Exception as erro:

        print(
            "ERRO NO LOGIN:"
        )

        print(
            repr(erro)
        )


        return JSONResponse(

            status_code=500,

            content={
                "detail":
                "Erro ao realizar login."
            }
        )

@app.get("/logout")
async def logout(
    request: Request
):
    request.session.clear()
    return RedirectResponse(
        "/login",
        status_code=302
    )
@app.get("/api/health")
async def health():
    return {
        "status":
        "online",
        "sistema":
        "Agente Financeiro",
        "versao": obter_codigo_versao(),
        "github_url": GITHUB_REPO_URL,
        "modelo_ia": os.getenv("GEMINI_MODEL", "gemini-3.3-flash").strip(),
        "extrator": extrator is not None,
        "classificador": classificar is not None,
        "email_configurado": bool(os.getenv("IMAP_HOST") and os.getenv("IMAP_USER") and os.getenv("IMAP_PASSWORD") and os.getenv("IMAP_OWNER_CPF")),
        "smtp_configurado": bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM")),
    }
@app.post("/api/extrair")
async def iniciar_trabalho(
    request: Request,
    arquivo: UploadFile = File(...)
):
    if not request.session.get("logado"):
        return JSONResponse(
            status_code=401,
            content={"detail": "Usuário não autenticado."}
        )

    if not arquivo.filename:
        return JSONResponse(
            status_code=400,
            content={"detail": "Nenhum arquivo foi enviado."}
        )

    nome_arquivo = arquivo.filename.lower()
    extensao = Path(nome_arquivo).suffix

    if extensao not in {".pdf", ".json"}:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Formato não suportado. Selecione uma nota fiscal em PDF ou um arquivo JSON."
            }
        )

    try:
        conteudo = await arquivo.read()
    except Exception as erro:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Não foi possível ler o arquivo: {erro}"}
        )
    finally:
        await arquivo.close()

    if not conteudo:
        return JSONResponse(
            status_code=400,
            content={"detail": "O arquivo está vazio."}
        )

    if len(conteudo) > MAX_ARQUIVO_SIZE:
        return JSONResponse(
            status_code=400,
            content={"detail": "O arquivo deve ter no máximo 50 MB."}
        )

    trabalho_id = str(uuid.uuid4())
    if extensao == ".json":
        try:
            dados_json = json.loads(conteudo.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as erro:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": f"JSON inválido. Verifique a codificação UTF-8 e a estrutura do arquivo. Detalhe: {erro}"
                }
            )

        if not isinstance(dados_json, dict):
            return JSONResponse(status_code=400, content={"detail": "O JSON da nota deve conter um objeto de dados."})
        try:
            documento_id, nome_documento = salvar_documento(
                arquivo.filename, conteudo, "UPLOAD", usuario_id_sessao(request)
            )
        except (OSError, sqlite3.Error) as erro:
            return JSONResponse(status_code=500, content={"detail": f"Não foi possível armazenar o documento: {erro}"})
        dados_json["documento_id"] = documento_id
        dados_json["documento_origem"] = nome_documento
        preencher_vencimento_ausente(dados_json)
        with conectar_db() as conn:
            conn.execute("UPDATE documentos SET status='LIDO' WHERE id=?", (documento_id,))
        criar_trabalho(
            trabalho_id,
            "concluido",
            "Arquivo JSON lido com sucesso.",
            dados_json
        )
        trabalhos[trabalho_id]["usuario_id"] = usuario_id_sessao(request)
        return JSONResponse(
            status_code=200,
            content={
                "sucesso": True,
                "trabalho_id": trabalho_id,
                "status": "concluido",
                "message": "Arquivo JSON lido com sucesso.",
                "mensagem": "Arquivo JSON lido com sucesso.",
                "result": dados_json,
                "resultado": dados_json
            }
        )

    # PDFs passam pelos agentes já usados pelo projeto.
    if extrator is None:
        return JSONResponse(
            status_code=500,
            content={"detail": "O ExtratorAgent não foi inicializado. Confira a configuração do projeto."}
        )
    if classificar is None:
        return JSONResponse(
            status_code=500,
            content={"detail": "O ClassificarAgent não foi inicializado. Confira a configuração do projeto."}
        )

    if not conteudo.startswith(b"%PDF"):
        return JSONResponse(
            status_code=400,
            content={"detail": "O arquivo selecionado tem extensão PDF, mas não parece ser um PDF válido."}
        )

    try:
        documento_id, nome_documento = salvar_documento(
            arquivo.filename, conteudo, "UPLOAD", usuario_id_sessao(request)
        )
    except (OSError, sqlite3.Error) as erro:
        return JSONResponse(status_code=500, content={"detail": f"Não foi possível armazenar o documento: {erro}"})

    try:
        caminho_pdf = Path(tempfile.gettempdir()) / f"{trabalho_id}.pdf"
        caminho_pdf.write_bytes(conteudo)
    except OSError as erro:
        with conectar_db() as conn:
            conn.execute("UPDATE documentos SET status='ERRO' WHERE id=?", (documento_id,))
        criar_trabalho(trabalho_id, "erro", f"Erro ao salvar o PDF: {erro}", None)
        trabalhos[trabalho_id]["usuario_id"] = usuario_id_sessao(request)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Erro ao salvar o PDF: {erro}", "trabalho_id": trabalho_id}
        )

    criar_trabalho(
        trabalho_id,
        "aguardando",
        "PDF recebido. Aguardando processamento.",
        None
    )
    trabalhos[trabalho_id]["usuario_id"] = usuario_id_sessao(request)
    trabalhos[trabalho_id]["documento_id"] = documento_id
    trabalhos[trabalho_id]["nome_arquivo"] = nome_documento
    asyncio.create_task(processar_trabalho(trabalho_id, str(caminho_pdf)))

    return JSONResponse(
        status_code=200,
        content={
            "sucesso": True,
            "trabalho_id": trabalho_id,
            "status": "aguardando",
            "message": "PDF enviado com sucesso.",
            "mensagem": "PDF enviado com sucesso."
        }
    )

async def processar_trabalho(
    trabalho_id: str,
    caminho_pdf: str
):
    try:
        print(
            f"\n[{trabalho_id}] Iniciando ExtratorAgent..."
        )
        criar_trabalho(
            trabalho_id,
            "processando",
            " Agente Extrator analisando o PDF...",
            None
        )
        print(
            "Enviando PDF para o Gemini..."
        )
        resultado = await asyncio.to_thread(
            extrator.extrator,
            caminho_pdf
        )
        print(
            "PDF processado pelo ExtratorAgent."
        )
        criar_trabalho(
            trabalho_id,
            "processando",
            "Agente Classificador analisando as despesas...",
            None
        )
        print(
            "Iniciando ClassificarAgent..."
        )

        classificacao = await asyncio.to_thread(
            classificar.classificar,
            resultado
        )
        print(
            "Classificação concluída."
        )
        if hasattr(
            resultado,
            "model_dump"
        ):
            resultado_final = (
                resultado.model_dump()
            )
        elif isinstance(
            resultado,
            dict
        ):
            resultado_final = (
                dict(resultado)
            )
        else:
            resultado_final = {
                "dados":
                resultado
            }
        preencher_vencimento_ausente(resultado_final)
        if hasattr(
            classificacao,
            "model_dump"
        ):
            classificacao = (
                classificacao.model_dump()
            )
        if isinstance(
            classificacao,
            dict
        ):
            for campo, valor in classificacao.items():
                if valor not in (None, "", []) or campo not in resultado_final:
                    resultado_final[campo] = valor
        documento_id = trabalhos.get(trabalho_id, {}).get("documento_id")
        if documento_id:
            resultado_final["documento_id"] = documento_id
            resultado_final["documento_origem"] = trabalhos[trabalho_id]["nome_arquivo"]
            with conectar_db() as conn:
                conn.execute("UPDATE documentos SET status='LIDO' WHERE id=?", (documento_id,))
        criar_trabalho(
            trabalho_id,
            "concluido",
            " Dados extraídos e classificados com sucesso.",
            resultado_final
        )
        print(
            f"[{trabalho_id}] Trabalho concluído com sucesso."
        )
    except Exception as erro:
        documento_id = trabalhos.get(trabalho_id, {}).get("documento_id")
        if documento_id:
            with conectar_db() as conn:
                conn.execute("UPDATE documentos SET status='ERRO' WHERE id=?", (documento_id,))
        print(
            "\n============================================================"
        )
        print(
            "ERRO NO TRABALHO"
        )
        print(
            f"[{trabalho_id}]"
        )
        print(
            repr(erro)
        )
        print(
            "============================================================\n"
        )

        criar_trabalho(
            trabalho_id,
            "erro",
            str(erro),
            None
        )
    finally:
        try:
            Path(
                caminho_pdf
            ).unlink(
                missing_ok=True
            )
            print(
                f"[{trabalho_id}] PDF temporário removido."
            )
        except Exception as erro:
            print(
                f"Erro ao remover PDF temporário: {erro}"
            )
@app.get(
    "/api/status/{trabalho_id}"
)
async def consultar_trabalho(
    request: Request,
    trabalho_id: str
):
    if not request.session.get(
        "logado"
    ):
        return JSONResponse(
            status_code=401,
            content={
                "detail":
                "Usuário não autenticado."
            }
        )
    trabalho = trabalhos.get(
        trabalho_id
    )
    if trabalho is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail":
                "Trabalho não encontrado.",
                "trabalho_id":
                trabalho_id
            }
        )
    if request.session.get("papel") != "admin" and trabalho.get("usuario_id") != usuario_id_sessao(request):
        return JSONResponse(status_code=404, content={"detail": "Trabalho não encontrado."})
    status = trabalho.get(
        "status",
        "desconhecido"
    )
    mensagem = trabalho.get(
        "message",
        trabalho.get(
            "mensagem",
            ""
        )
    )
    resultado = trabalho.get(
        "result",
        trabalho.get(
            "resultado",
            None
        )
    )
    return JSONResponse(
        status_code=200,
        content={
            "trabalho_id":
            trabalho_id,
            "status":
            status,
            "message":
            mensagem,
            "mensagem":
            mensagem,
            "result":
            resultado,
            "resultado":
            resultado
        }
    )
@app.delete(
    "/api/trabalhos/{trabalho_id}"
)
async def excluir_trabalho(
    request: Request,
    trabalho_id: str
):
    if not request.session.get(
        "logado"
    ):
        return JSONResponse(
            status_code=401,
            content={
                "detail":
                "Usuário não autenticado."
            }
        )
    if trabalho_id not in trabalhos:
        return JSONResponse(
            status_code=404,
            content={
                "detail":
                "Trabalho não encontrado."
            }
        )
    if request.session.get("papel") != "admin" and trabalhos[trabalho_id].get("usuario_id") != usuario_id_sessao(request):
        return JSONResponse(status_code=404, content={"detail": "Trabalho não encontrado."})
    del trabalhos[
        trabalho_id
    ]
    return {
        "sucesso":
        True,
        "mensagem":
        "Trabalho removido."
    }
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )

# ==================== BANCO DE DADOS E CADASTROS ====================
def resolver_db_path() -> Path:
    if os.getenv("DATABASE_PATH"):
        return Path(os.getenv("DATABASE_PATH"))
    local_db = Path(__file__).with_name("agente_financeiro.db")
    if IS_SERVERLESS:
        import shutil
        tmp_db = Path(tempfile.gettempdir()) / "agente_financeiro.db"
        if not tmp_db.exists() and local_db.exists():
            try:
                shutil.copy2(local_db, tmp_db)
            except OSError:
                pass
        return tmp_db
    return local_db

DB_PATH = resolver_db_path()
ENTIDADES = {
    "fornecedores": {"titulo": "Manter fornecedor", "campos": ["razao_social", "nome_fantasia", "cnpj", "telefone", "email", "endereco"]},
    "clientes": {"titulo": "Manter cliente", "campos": ["nome", "cpf_cnpj", "telefone", "email", "endereco"]},
    "pessoas": {"titulo": "Manter pessoas", "campos": ["nome", "razao_social", "cpf_cnpj", "data_nascimento", "tipo_pessoa", "telefone", "email", "responsavel_nome", "responsavel_cpf", "autorizacao_responsavel"]},
    "faturados": {"titulo": "Manter faturado", "campos": ["nome", "cpf", "cnpj", "observacao"]},
    "tipos_receita": {"titulo": "Manter tipo de receita", "campos": ["descricao", "observacao"]},
    "tipos_despesa": {"titulo": "Manter tipo de despesa", "campos": ["descricao", "observacao"]},
    "classificacoes": {"titulo": "Manter classificação", "campos": ["descricao", "tipo", "observacao"]},
}

def conectar_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def salvar_documento(nome_arquivo, conteudo, origem, usuario_id=None):
    DOCUMENTOS_DIR.mkdir(parents=True, exist_ok=True)
    nome_seguro = Path(nome_arquivo).name
    caminho = DOCUMENTOS_DIR / f"{uuid.uuid4()}{Path(nome_seguro).suffix.lower()}"
    caminho.write_bytes(conteudo)
    try:
        with conectar_db() as conn:
            cur = conn.execute(
                "INSERT INTO documentos(nome_arquivo,caminho,origem,status,recebido_em,usuario_id) VALUES(?,?,?,?,?,?)",
                (nome_seguro, str(caminho), origem, "PENDENTE", datetime.now().isoformat(timespec="seconds"), usuario_id)
            )
            return cur.lastrowid, nome_seguro
    except sqlite3.Error:
        caminho.unlink(missing_ok=True)
        raise


def normalizar_documentos(dados):
    limites = {"cpf": 11, "cnpj": 14, "cpf_cnpj": 14, "responsavel_cpf": 11}
    nomes = {"cpf": "CPF", "cnpj": "CNPJ", "cpf_cnpj": "CPF/CNPJ", "responsavel_cpf": "CPF do responsável"}
    for campo, limite in limites.items():
        if campo not in dados:
            continue
        documento = re.sub(r"\D", "", str(dados[campo]))
        if len(documento) > limite:
            raise ValueError(f"{nomes[campo]} deve conter no máximo {limite} dígitos.")
        dados[campo] = documento


def validar_campos_texto(dados):
    campos_nome = {
        "nome", "nome_completo", "razao_social", "nome_fantasia",
        "responsavel_nome",
    }
    for campo in campos_nome.intersection(dados):
        valor = str(dados[campo]).strip()
        if len(valor) > 50 or (valor and not all(caractere.isalpha() or caractere.isspace() for caractere in valor)):
            raise ValueError(f"{campo.replace('_', ' ').capitalize()} deve conter somente letras e espaços, com até 50 caracteres.")
        dados[campo] = valor

    for campo in {"tipo", "tipo_pessoa"}.intersection(dados):
        valor = str(dados[campo]).strip()
        if len(valor) > 50 or (valor and not all(caractere.isalpha() or caractere.isspace() for caractere in valor)):
            raise ValueError(f"{campo.replace('_', ' ').capitalize()} deve conter somente letras e espaços, com até 50 caracteres.")
        dados[campo] = valor

    if "telefone" in dados:
        telefone = str(dados["telefone"]).strip()
        if len(telefone) > 15 or (telefone and not telefone.isdigit()):
            raise ValueError("Telefone deve conter somente números e no máximo 15 dígitos.")
        dados["telefone"] = telefone

    if "email" in dados:
        email = str(dados["email"]).strip()
        if len(email) > 50:
            raise ValueError("E-mail deve conter no máximo 50 caracteres.")
        dados["email"] = email


def calcular_idade(data_nascimento):
    try:
        nascimento = date.fromisoformat(str(data_nascimento))
    except (TypeError, ValueError):
        raise ValueError("Informe uma data de nascimento válida.")
    hoje = date.today()
    if nascimento > hoje:
        raise ValueError("A data de nascimento não pode ser futura.")
    return hoje.year - nascimento.year - (
        (hoje.month, hoje.day) < (nascimento.month, nascimento.day)
    )


def converter_valor_monetario(valor):
    texto = re.sub(r"[^0-9,.-]", "", str(valor)).strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    valor_convertido = float(texto)
    if not math.isfinite(valor_convertido) or valor_convertido <= 0:
        raise ValueError("O valor deve ser positivo.")
    return valor_convertido


def normalizar_data_iso(valor):
    if not valor:
        raise ValueError("Informe uma data válida.")
    return date.fromisoformat(str(valor)[:10]).isoformat()


def gerar_hash_senha(senha):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, 310_000)
    return f"{salt.hex()}${digest.hex()}"


def verificar_senha(senha, senha_hash):
    try:
        salt_hex, digest_hex = senha_hash.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except (AttributeError, ValueError):
        return False
    candidato = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, 310_000)
    return hmac.compare_digest(candidato.hex(), digest_hex)


def preencher_vencimento_ausente(nota):
    if not isinstance(nota, dict):
        return
    data_emissao = nota.get("data_emissao")
    data_vencimento = nota.get("data_vencimento") or data_emissao
    if not nota.get("data_vencimento"):
        nota["data_vencimento"] = data_vencimento
    parcelas = nota.get("parcelas")
    if isinstance(parcelas, list):
        for parcela in parcelas:
            if isinstance(parcela, dict) and not parcela.get("data_vencimento"):
                parcela["data_vencimento"] = data_vencimento


def inicializar_db():
    with conectar_db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS registros (id INTEGER PRIMARY KEY AUTOINCREMENT, entidade TEXT NOT NULL, dados TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ATIVO', criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS movimentos (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, dados TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ATIVO', criado_em TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS parcelas (id INTEGER PRIMARY KEY AUTOINCREMENT, movimento_id INTEGER NOT NULL, identificacao TEXT NOT NULL UNIQUE, numero INTEGER NOT NULL, data_vencimento TEXT, valor REAL NOT NULL, status TEXT NOT NULL DEFAULT 'ATIVO', FOREIGN KEY(movimento_id) REFERENCES movimentos(id))")
        conn.execute("CREATE TABLE IF NOT EXISTS status_parcelas_arquivados (parcela_id INTEGER PRIMARY KEY, movimento_id INTEGER NOT NULL, status_anterior TEXT NOT NULL, FOREIGN KEY(parcela_id) REFERENCES parcelas(id), FOREIGN KEY(movimento_id) REFERENCES movimentos(id))")
        conn.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, pessoa_id INTEGER NOT NULL UNIQUE, cpf TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ATIVO', criado_em TEXT NOT NULL, FOREIGN KEY(pessoa_id) REFERENCES registros(id))")
        colunas_usuario = {row["name"] for row in conn.execute("PRAGMA table_info(usuarios)")}
        if "login" not in colunas_usuario:
            conn.execute("ALTER TABLE usuarios ADD COLUMN login TEXT")
        if "documento" not in colunas_usuario:
            conn.execute("ALTER TABLE usuarios ADD COLUMN documento TEXT")
        conn.execute("UPDATE usuarios SET login=cpf WHERE login IS NULL OR TRIM(login)=''")
        conn.execute("UPDATE usuarios SET documento=cpf WHERE documento IS NULL OR TRIM(documento)=''")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_login ON usuarios(login COLLATE NOCASE)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_documento ON usuarios(documento)")
        conn.execute("CREATE TABLE IF NOT EXISTS movimentos_financeiros (id INTEGER PRIMARY KEY AUTOINCREMENT, parcela_id INTEGER NOT NULL, tipo TEXT NOT NULL, valor REAL NOT NULL, data_movimento TEXT NOT NULL, comprovante TEXT, criado_em TEXT NOT NULL, FOREIGN KEY(parcela_id) REFERENCES parcelas(id))")
        conn.execute("CREATE TABLE IF NOT EXISTS documentos (id INTEGER PRIMARY KEY AUTOINCREMENT, nome_arquivo TEXT NOT NULL, caminho TEXT NOT NULL, origem TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDENTE', recebido_em TEXT NOT NULL, movimento_id INTEGER, FOREIGN KEY(movimento_id) REFERENCES movimentos(id))")
        conn.execute("CREATE TABLE IF NOT EXISTS notificacoes_enviadas (id INTEGER PRIMARY KEY AUTOINCREMENT, parcela_id INTEGER NOT NULL, data_envio TEXT NOT NULL, email TEXT NOT NULL, UNIQUE(parcela_id,data_envio,email), FOREIGN KEY(parcela_id) REFERENCES parcelas(id))")
        for tabela in ("registros", "movimentos", "documentos"):
            colunas = {row["name"] for row in conn.execute(f"PRAGMA table_info({tabela})")}
            if "usuario_id" not in colunas:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id)")
        conn.execute(
            "UPDATE registros SET usuario_id=(SELECT id FROM usuarios WHERE usuarios.pessoa_id=registros.id) "
            "WHERE entidade='pessoas' AND usuario_id IS NULL "
            "AND EXISTS(SELECT 1 FROM usuarios WHERE usuarios.pessoa_id=registros.id)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_registros_usuario ON registros(usuario_id,entidade,status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movimentos_usuario ON movimentos(usuario_id,status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documentos_usuario ON documentos(usuario_id,movimento_id)")
        prof_login = os.getenv("PROFESSOR_USER", "professor").strip()
        prof_senha = os.getenv("PROFESSOR_PASSWORD", "professor123").strip()
        existe_prof = conn.execute("SELECT id FROM usuarios WHERE login=? COLLATE NOCASE", (prof_login,)).fetchone()
        if not existe_prof:
            agora = datetime.now().isoformat(timespec="seconds")
            dados_prof = {
                "nome": "Professor Avaliador",
                "razao_social": "",
                "cpf_cnpj": "11122233344",
                "data_nascimento": "1985-05-15",
                "tipo_pessoa": "USUARIO",
                "telefone": "83999999999",
                "email": "professor@universidade.edu.br"
            }
            cur_p = conn.execute(
                "INSERT INTO registros(entidade,dados,status,criado_em,atualizado_em) VALUES(?,?,?,?,?)",
                ("pessoas", json.dumps(dados_prof, ensure_ascii=False), "ATIVO", agora, agora)
            )
            pid = cur_p.lastrowid
            cur_u = conn.execute(
                "INSERT OR IGNORE INTO usuarios(pessoa_id,cpf,login,documento,senha_hash,status,criado_em) VALUES(?,?,?,?,?,?,?)",
                (pid, "11122233344", prof_login, "11122233344", gerar_hash_senha(prof_senha), "ATIVO", agora)
            )
            if cur_u.lastrowid:
                conn.execute("UPDATE registros SET usuario_id=? WHERE id=?", (cur_u.lastrowid, pid))

inicializar_db()

def autenticado(request: Request):
    return bool(request.session.get("logado"))

def usuario_id_sessao(request: Request):
    if request.session.get("papel") == "admin":
        return None
    try:
        return int(request.session.get("usuario_id", -1))
    except (TypeError, ValueError):
        return -1

def filtro_proprietario(request: Request, prefixo: str = ""):
    if request.session.get("papel") == "admin":
        return "", ()
    return f" AND {prefixo}usuario_id=?", (usuario_id_sessao(request),)


@app.post("/api/cadastro")
async def cadastrar_pessoa(request: Request):
    dados = await request.json()
    if not isinstance(dados, dict):
        return JSONResponse(status_code=400, content={"detail": "Os dados do cadastro devem ser um objeto."})
    nome = str(dados.get("nome", "")).strip()
    login = str(dados.get("login", "")).strip()
    documento = re.sub(r"\D", "", str(dados.get("cpf_cnpj") or dados.get("cpf") or ""))
    email = str(dados.get("email", "")).strip()
    telefone = str(dados.get("telefone", "")).strip()
    try:
        validar_campos_texto({
            "nome": nome,
            "email": email,
            "telefone": telefone,
        })
    except ValueError as erro:
        return JSONResponse(status_code=400, content={"detail": str(erro)})
    nome = nome.strip()
    email = email.strip()
    telefone = telefone.strip()
    senha = str(dados.get("senha", ""))
    data_nascimento = dados.get("data_nascimento")
    if not nome:
        return JSONResponse(status_code=400, content={"detail": "Informe o nome completo."})
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", login):
        return JSONResponse(status_code=400, content={"detail": "O login deve ter de 3 a 32 caracteres: letras, números, ponto, hífen ou sublinhado."})
    if login.casefold() in {(os.getenv("ADMIN_USER") or os.getenv("LOGIN_USUARIO") or "AnaJamyle_Miguel_Vinicius").strip().casefold(), os.getenv("PROFESSOR_USER", "professor").strip().casefold()}:
        return JSONResponse(status_code=400, content={"detail": "Esse login está reservado para a conta administrativa."})
    if len(documento) not in {11, 14}:
        return JSONResponse(status_code=400, content={"detail": "Informe um CPF com 11 ou CNPJ com 14 números."})
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return JSONResponse(status_code=400, content={"detail": "Informe um e-mail válido."})
    if len(senha) < 8:
        return JSONResponse(status_code=400, content={"detail": "A senha deve ter pelo menos 8 caracteres."})
    try:
        idade = calcular_idade(data_nascimento)
    except ValueError as erro:
        return JSONResponse(status_code=400, content={"detail": str(erro)})
    responsavel = str(dados.get("responsavel_nome", "")).strip()
    cpf_responsavel = re.sub(r"\D", "", str(dados.get("responsavel_cpf", "")))
    if idade < 18 and (
        not responsavel
        or len(cpf_responsavel) != 11
        or dados.get("autorizacao_responsavel") is not True
    ):
        return JSONResponse(
            status_code=400,
            content={"detail": "Para menores de 18 anos, informe o responsável, o CPF dele e confirme a autorização."}
        )
    agora = datetime.now().isoformat(timespec="seconds")
    pessoa = {
        "nome": nome,
        "razao_social": "",
        "cpf_cnpj": documento,
        "data_nascimento": str(data_nascimento),
        "tipo_pessoa": "USUARIO",
        "telefone": telefone,
        "email": email,
    }
    if idade < 18:
        pessoa["responsavel_nome"] = responsavel
        pessoa["responsavel_cpf"] = cpf_responsavel
        pessoa["autorizacao_responsavel"] = True
    try:
        with conectar_db() as conn:
            cur = conn.execute(
                "INSERT INTO registros(entidade,dados,status,criado_em,atualizado_em) VALUES(?,?,?,?,?)",
                ("pessoas", json.dumps(pessoa, ensure_ascii=False), "ATIVO", agora, agora)
            )
            pessoa_id = cur.lastrowid
            usuario = conn.execute(
                "INSERT INTO usuarios(pessoa_id,cpf,login,documento,senha_hash,criado_em) VALUES(?,?,?,?,?,?)",
                (pessoa_id, documento, login, documento, gerar_hash_senha(senha), agora)
            )
            usuario_id = usuario.lastrowid
            conn.execute("UPDATE registros SET usuario_id=? WHERE id=?", (usuario_id, pessoa_id))
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=409, content={"detail": "O login ou CPF/CNPJ já está cadastrado."})
    return {"sucesso": True, "mensagem": "Cadastro realizado. Entre com seu login e senha.", "idade": idade}

def resposta_registro(row):
    item = dict(row)
    item["dados"] = json.loads(item["dados"])
    if item["entidade"] == "pessoas" and item["dados"].get("data_nascimento"):
        try:
            item["dados"]["idade"] = calcular_idade(item["dados"]["data_nascimento"])
        except ValueError:
            item["dados"]["idade"] = None
    return item

@app.get("/api/entidades")
async def listar_entidades(request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    return {"entidades": ENTIDADES}

@app.get("/api/registros/{entidade}")
async def listar_registros(entidade: str, request: Request, todos: bool = False, busca: str = "", status: str = "ATIVO"):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    if entidade not in ENTIDADES:
        return JSONResponse(status_code=404, content={"detail": "Cadastro não encontrado."})

    if not todos and not busca.strip():
        return {"registros": [], "campos": ENTIDADES[entidade]["campos"], "mensagem": "Use a busca ou clique em Todos para carregar registros."}
    filtro, parametros = filtro_proprietario(request)
    with conectar_db() as conn:
        rows = conn.execute(f"SELECT * FROM registros WHERE entidade=? AND status=?{filtro} ORDER BY id DESC", (entidade, status.upper(), *parametros)).fetchall()
    itens = [resposta_registro(r) for r in rows]
    if busca.strip():
        termo = busca.strip().casefold()
        itens = [x for x in itens if termo in json.dumps(x["dados"], ensure_ascii=False).casefold() or termo in str(x["id"])]
    return {"registros": itens, "campos": ENTIDADES[entidade]["campos"]}

@app.post("/api/registros/{entidade}")
async def criar_registro(entidade: str, request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    if entidade not in ENTIDADES:
        return JSONResponse(status_code=404, content={"detail": "Cadastro não encontrado."})
    dados = await request.json()
    dados = {c: str(dados.get(c, "")).strip() for c in ENTIDADES[entidade]["campos"]}
    try:
        validar_campos_texto(dados)
        normalizar_documentos(dados)
        if entidade == "pessoas":
            if not dados.get("nome") or not dados.get("cpf_cnpj"):
                raise ValueError("Informe nome e CPF/CNPJ da pessoa.")
            idade = calcular_idade(dados.get("data_nascimento"))
            if idade < 18 and (
                not dados.get("responsavel_nome")
                or len(dados.get("responsavel_cpf", "")) != 11
                or str(dados.get("autorizacao_responsavel", "")).lower() not in {"true", "sim", "1"}
            ):
                raise ValueError("Menores de 18 anos exigem autorização e CPF do responsável.")
    except ValueError as erro:
        return JSONResponse(status_code=400, content={"detail": str(erro)})
    if not any(dados.values()):
        return JSONResponse(status_code=400, content={"detail": "Preencha pelo menos um campo."})
    agora = datetime.now().isoformat(timespec="seconds")
    usuario_id = usuario_id_sessao(request)
    with conectar_db() as conn:
        cur = conn.execute("INSERT INTO registros(entidade,dados,status,criado_em,atualizado_em,usuario_id) VALUES(?,?,?,?,?,?)", (entidade, json.dumps(dados, ensure_ascii=False), "ATIVO", agora, agora, usuario_id))
        rid = cur.lastrowid
    return {"sucesso": True, "id": rid, "status": "ATIVO", "mensagem": "Cadastro salvo com sucesso."}

@app.put("/api/registros/{entidade}/{registro_id}")
async def atualizar_registro(entidade: str, registro_id: int, request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    if entidade not in ENTIDADES:
        return JSONResponse(status_code=404, content={"detail": "Cadastro não encontrado."})
    novos = await request.json()
    filtro, parametros = filtro_proprietario(request)
    try:
        validar_campos_texto(novos)
        normalizar_documentos(novos)
        if entidade == "pessoas":
            with conectar_db() as conn:
                atual = conn.execute(
                    f"SELECT dados FROM registros WHERE id=? AND entidade=?{filtro}",
                    (registro_id, entidade, *parametros)
                ).fetchone()
            if not atual:
                return JSONResponse(status_code=404, content={"detail": "Registro não encontrado."})
            pessoa = json.loads(atual["dados"])
            pessoa.update({k: str(v).strip() for k, v in novos.items() if k in ENTIDADES[entidade]["campos"]})
            idade = calcular_idade(pessoa.get("data_nascimento"))
            if idade < 18 and (
                not pessoa.get("responsavel_nome")
                or len(re.sub(r"\D", "", pessoa.get("responsavel_cpf", ""))) != 11
                or str(pessoa.get("autorizacao_responsavel", "")).lower() not in {"true", "sim", "1"}
            ):
                raise ValueError("Menores de 18 anos exigem autorização e CPF do responsável.")
    except ValueError as erro:
        return JSONResponse(status_code=400, content={"detail": str(erro)})
    with conectar_db() as conn:
        row = conn.execute(f"SELECT * FROM registros WHERE id=? AND entidade=?{filtro}", (registro_id, entidade, *parametros)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"detail": "Registro não encontrado."})
        antigos = json.loads(row["dados"])
        for campo in ENTIDADES[entidade]["campos"]:
            if campo in novos: antigos[campo] = str(novos[campo]).strip()
        conn.execute("UPDATE registros SET dados=?, atualizado_em=? WHERE id=?", (json.dumps(antigos, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), registro_id))
    return {"sucesso": True, "mensagem": "Cadastro atualizado com sucesso."}

@app.delete("/api/registros/{entidade}/{registro_id}")
async def inativar_registro(entidade: str, registro_id: int, request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    if entidade not in ENTIDADES:
        return JSONResponse(status_code=404, content={"detail": "Cadastro não encontrado."})
    filtro, parametros = filtro_proprietario(request)
    with conectar_db() as conn:
        cur = conn.execute(f"UPDATE registros SET status='INATIVO', atualizado_em=? WHERE id=? AND entidade=? AND status='ATIVO'{filtro}", (datetime.now().isoformat(timespec="seconds"), registro_id, entidade, *parametros))
        if not cur.rowcount:
            return JSONResponse(status_code=404, content={"detail": "Registro ativo não encontrado."})
    return {"sucesso": True, "mensagem": "Registro excluído com sucesso."}

@app.post("/api/registros/{entidade}/{registro_id}/reativar")
async def reativar_registro(entidade: str, registro_id: int, request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    if entidade not in ENTIDADES:
        return JSONResponse(status_code=404, content={"detail": "Cadastro não encontrado."})
    filtro, parametros = filtro_proprietario(request)
    with conectar_db() as conn:
        cur = conn.execute(f"UPDATE registros SET status='ATIVO', atualizado_em=? WHERE id=? AND entidade=? AND status='INATIVO'{filtro}", (datetime.now().isoformat(timespec="seconds"), registro_id, entidade, *parametros))
        if not cur.rowcount:
            return JSONResponse(status_code=404, content={"detail": "Registro inativo não encontrado."})
    return {"sucesso": True, "mensagem": "Registro reativado com sucesso."}

@app.get("/api/movimentos")
async def listar_movimentos(request: Request, tipo: str = "", busca: str = "", todos: bool = False, status: str = "ATIVO"):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    if not todos and not busca.strip():
        return {"movimentos": [], "mensagem": "Use a busca ou clique em Todos para carregar lançamentos."}
    filtro, parametros = filtro_proprietario(request, "m.")
    with conectar_db() as conn:
        rows = conn.execute(f"SELECT m.* FROM movimentos m WHERE m.status=?{filtro} ORDER BY m.id DESC", (status.upper(), *parametros)).fetchall()
        out=[]
        for r in rows:
            dados=json.loads(r["dados"])
            if tipo and r["tipo"] != tipo: continue
            if busca.strip() and busca.casefold() not in json.dumps(dados, ensure_ascii=False).casefold() and busca.casefold() not in str(r["id"]): continue
            parcelas=[dict(x) for x in conn.execute("SELECT * FROM parcelas WHERE movimento_id=? ORDER BY numero", (r["id"],)).fetchall()]
            out.append({"id":r["id"],"tipo":r["tipo"],"status":r["status"],"dados":dados,"parcelas":parcelas,"criado_em":r["criado_em"]})
    return {"movimentos": out}

@app.post("/api/movimentos")
async def criar_movimento(request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    payload=await request.json()
    tipo=str(payload.get("tipo", "APAGAR")).upper()
    if tipo not in ("APAGAR", "ARECEBER"):
        return JSONResponse(status_code=400, content={"detail": "Tipo deve ser APAGAR ou ARECEBER."})
    dados=payload.get("dados", {})
    if not isinstance(dados, dict):
        return JSONResponse(status_code=400, content={"detail": "Informe os dados do movimento."})
    pessoa_ref = str(dados.get("pessoa_id", "")).strip()
    try:
        pessoa_entidade, pessoa_id_texto = pessoa_ref.split(":", 1)
        pessoa_id = int(pessoa_id_texto)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Selecione uma pessoa cadastrada."})
    if pessoa_entidade not in {"pessoas", "clientes", "faturados"} or pessoa_id <= 0:
        return JSONResponse(status_code=400, content={"detail": "A pessoa selecionada não é válida."})
    filtro, parametros = filtro_proprietario(request)
    with conectar_db() as conn:
        pessoa_row = conn.execute(
            f"SELECT dados FROM registros WHERE entidade=? AND id=? AND status='ATIVO'{filtro}",
            (pessoa_entidade, pessoa_id, *parametros)
        ).fetchone()
    if not pessoa_row:
        return JSONResponse(status_code=400, content={"detail": "A pessoa selecionada não existe ou está inativa."})
    pessoa_dados = json.loads(pessoa_row["dados"])
    dados["pessoa"] = str(
        pessoa_dados.get("nome")
        or pessoa_dados.get("nome_completo")
        or pessoa_dados.get("razao_social")
        or ""
    ).strip()
    if not dados["pessoa"]:
        return JSONResponse(status_code=400, content={"detail": "O cadastro selecionado não possui nome ou razão social."})
    dados["pessoa_id"] = pessoa_id
    dados["pessoa_entidade"] = pessoa_entidade
    dados["documento_origem"] = str(dados.get("documento_origem", "")).strip()
    dados["subcategoria"] = str(dados.get("subcategoria", "")).strip()
    if not dados["pessoa"]:
        return JSONResponse(status_code=400, content={"detail": "Informe a pessoa vinculada."})
    if dados["subcategoria"] not in {"Insumos", "Operacional", "Venda de Produção"}:
        return JSONResponse(status_code=400, content={"detail": "Selecione uma subcategoria válida."})
    try:
        documento_id = int(dados.get("documento_id", 0))
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Selecione um documento de origem válido."})
    filtro_documento, parametros_documento = filtro_proprietario(request)
    with conectar_db() as conn:
        documento = conn.execute(
            f"SELECT nome_arquivo FROM documentos WHERE id=? AND movimento_id IS NULL{filtro_documento}",
            (documento_id, *parametros_documento)
        ).fetchone()
    if not documento:
        return JSONResponse(status_code=400, content={"detail": "O documento selecionado não existe ou já está vinculado."})
    dados["documento_origem"] = documento["nome_arquivo"]
    parcelas_in=payload.get("parcelas", [])
    if isinstance(dados.get("classificacoes"), str):
        dados["classificacoes"] = [x.strip() for x in dados["classificacoes"].split(",") if x.strip()]
    if isinstance(dados.get("classificacoes"), list):
        entidade_class = "tipos_receita" if tipo == "ARECEBER" else "tipos_despesa"
        dados["tipo_classificacao"] = entidade_class
    if not isinstance(parcelas_in, list) or not parcelas_in:
        return JSONResponse(status_code=400, content={"detail": "Informe pelo menos uma parcela."})
    try:
        for parcela in parcelas_in:
            if not isinstance(parcela, dict):
                raise ValueError
            date.fromisoformat(str(parcela.get("data_vencimento", "")))
            converter_valor_monetario(parcela.get("valor", 0))
        with conectar_db() as conn:
            usuario_id = usuario_id_sessao(request)
            cur=conn.execute("INSERT INTO movimentos(tipo,dados,status,criado_em,usuario_id) VALUES(?,?,?,?,?)", (tipo,json.dumps(dados,ensure_ascii=False),"ATIVO",datetime.now().isoformat(timespec="seconds"),usuario_id))
            mid=cur.lastrowid
            condicao_documento = " AND usuario_id=?" if usuario_id is not None else ""
            parametros_vinculo = (mid, documento_id, usuario_id) if usuario_id is not None else (mid, documento_id)
            vinculo = conn.execute(
                f"UPDATE documentos SET movimento_id=?,status='VINCULADO' WHERE id=? AND movimento_id IS NULL{condicao_documento}",
                parametros_vinculo
            )
            if not vinculo.rowcount:
                raise sqlite3.IntegrityError("O documento já foi vinculado a outro movimento.")
            for i, par in enumerate(parcelas_in, start=1):
                ident=str(par.get("identificacao") or f"MOV-{mid}-PAR-{i}").strip()
                conn.execute("INSERT INTO parcelas(movimento_id,identificacao,numero,data_vencimento,valor,status) VALUES(?,?,?,?,?,?)", (mid,ident,int(par.get("numero",i)),par.get("data_vencimento"),converter_valor_monetario(par.get("valor",0)),"ATIVO"))
    except sqlite3.IntegrityError:
        return JSONResponse(status_code=409, content={"detail": "A identificação da parcela já existe ou o documento foi vinculado a outro movimento."})
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Verifique número, vencimento e valor positivo das parcelas."})
    return {"sucesso": True,"id":mid,"mensagem":f"Movimento e {len(parcelas_in)} parcela(s) registrados com sucesso."}


@app.post("/api/parcelas/{parcela_id}/quitar")
async def quitar_parcela(
    parcela_id: int,
    request: Request,
    comprovante: UploadFile = File(...),
    data_movimento: str = Form(default="")
):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    if not comprovante.filename or Path(comprovante.filename).suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
        return JSONResponse(status_code=400, content={"detail": "Envie o comprovante em PDF ou imagem."})
    try:
        conteudo = await comprovante.read()
    finally:
        await comprovante.close()
    if not conteudo or len(conteudo) > MAX_ARQUIVO_SIZE:
        return JSONResponse(status_code=400, content={"detail": "O comprovante está vazio ou excede 50 MB."})
    data_baixa = data_movimento or date.today().isoformat()
    try:
        date.fromisoformat(data_baixa)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Informe uma data de pagamento/recebimento válida."})
    filtro_movimento, parametros_movimento = filtro_proprietario(request, "m.")
    with conectar_db() as conn:
        parcela = conn.execute(
            f"SELECT p.*,m.tipo FROM parcelas p JOIN movimentos m ON m.id=p.movimento_id WHERE p.id=? AND p.status='ATIVO' AND m.status='ATIVO'{filtro_movimento}",
            (parcela_id, *parametros_movimento)
        ).fetchone()
    if not parcela:
        return JSONResponse(status_code=404, content={"detail": "Parcela aberta não encontrada."})
    try:
        documento_id, _ = salvar_documento(comprovante.filename, conteudo, "COMPROVANTE", usuario_id_sessao(request))
    except (OSError, sqlite3.Error) as erro:
        return JSONResponse(status_code=500, content={"detail": f"Não foi possível armazenar o comprovante: {erro}"})
    status_final = "PAGO" if parcela["tipo"] == "APAGAR" else "RECEBIDO"
    try:
        with conectar_db() as conn:
            atualizada = conn.execute(
                "UPDATE parcelas SET status=? WHERE id=? AND status='ATIVO'",
                (status_final, parcela_id)
            )
            if not atualizada.rowcount:
                return JSONResponse(status_code=409, content={"detail": "A parcela já foi baixada."})
            conn.execute(
                "INSERT INTO movimentos_financeiros(parcela_id,tipo,valor,data_movimento,comprovante,criado_em) VALUES(?,?,?,?,?,?)",
                (parcela_id, parcela["tipo"], parcela["valor"], data_baixa, str(documento_id), datetime.now().isoformat(timespec="seconds"))
            )
            conn.execute("UPDATE documentos SET status='VINCULADO' WHERE id=?", (documento_id,))
    except sqlite3.Error as erro:
        return JSONResponse(status_code=500, content={"detail": f"Não foi possível registrar a baixa: {erro}"})
    return {"sucesso": True, "status": status_final, "mensagem": "Baixa registrada com o comprovante anexado."}


@app.get("/api/documentos")
async def listar_documentos(request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    filtro, parametros = filtro_proprietario(request)
    with conectar_db() as conn:
        rows = conn.execute(
            f"SELECT id,nome_arquivo,origem,status,recebido_em,movimento_id FROM documentos WHERE 1=1{filtro} ORDER BY id DESC",
            parametros
        ).fetchall()
    return {"documentos": [dict(row) for row in rows]}


@app.get("/api/documentos/{documento_id}")
async def baixar_documento(documento_id: int, request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    filtro, parametros = filtro_proprietario(request)
    with conectar_db() as conn:
        row = conn.execute(f"SELECT caminho,nome_arquivo FROM documentos WHERE id=?{filtro}", (documento_id, *parametros)).fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"detail": "Documento não encontrado."})
    caminho = Path(row["caminho"]).resolve()
    if caminho.parent != DOCUMENTOS_DIR.resolve() or not caminho.is_file():
        return JSONResponse(status_code=404, content={"detail": "Arquivo armazenado não encontrado."})
    return FileResponse(caminho, filename=row["nome_arquivo"])


@app.delete("/api/movimentos/{movimento_id}")
async def inativar_movimento(movimento_id: int, request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    filtro, parametros = filtro_proprietario(request)
    with conectar_db() as conn:
        movimento = conn.execute(f"SELECT id FROM movimentos WHERE id=? AND status='ATIVO'{filtro}",(movimento_id, *parametros)).fetchone()
        if not movimento:
            return JSONResponse(status_code=404,content={"detail":"Lançamento ativo não encontrado."})
        conn.execute(
            "INSERT OR REPLACE INTO status_parcelas_arquivados(parcela_id,movimento_id,status_anterior) "
            "SELECT id,movimento_id,status FROM parcelas WHERE movimento_id=?",
            (movimento_id,)
        )
        cur=conn.execute(f"UPDATE movimentos SET status='INATIVO' WHERE id=? AND status='ATIVO'{filtro}",(movimento_id, *parametros))
        if not cur.rowcount:
            return JSONResponse(status_code=404,content={"detail":"Lançamento ativo não encontrado."})
        conn.execute("UPDATE parcelas SET status='INATIVO' WHERE movimento_id=?",(movimento_id,))
    return {"sucesso":True,"mensagem":"Lançamento excluído com sucesso."}


@app.post("/api/movimentos/{movimento_id}/reativar")
async def reativar_movimento(movimento_id: int, request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    filtro, parametros = filtro_proprietario(request)
    with conectar_db() as conn:
        movimento = conn.execute(
            f"SELECT id,tipo FROM movimentos WHERE id=? AND status='INATIVO'{filtro}",
            (movimento_id, *parametros)
        ).fetchone()
        if not movimento:
            return JSONResponse(status_code=404, content={"detail": "Lançamento excluído não encontrado."})
        atualizado = conn.execute(
            f"UPDATE movimentos SET status='ATIVO' WHERE id=? AND status='INATIVO'{filtro}",
            (movimento_id, *parametros)
        )
        if not atualizado.rowcount:
            return JSONResponse(status_code=409, content={"detail": "Não foi possível reativar o lançamento."})
        conn.execute(
            "UPDATE parcelas SET status=COALESCE("
            "(SELECT status_anterior FROM status_parcelas_arquivados "
            "WHERE status_parcelas_arquivados.parcela_id=parcelas.id),"
            "CASE WHEN EXISTS(SELECT 1 FROM movimentos_financeiros "
            "WHERE movimentos_financeiros.parcela_id=parcelas.id) "
            "THEN ? ELSE 'ATIVO' END) "
            "WHERE movimento_id=? AND status='INATIVO'",
            ("PAGO" if movimento["tipo"] == "APAGAR" else "RECEBIDO", movimento_id)
        )
        conn.execute("DELETE FROM status_parcelas_arquivados WHERE movimento_id=?", (movimento_id,))
    return {"sucesso": True, "mensagem": "Lançamento reativado com sucesso."}

@app.post("/api/analisar-nota")
async def analisar_nota(request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail":"Usuário não autenticado."})
    payload=await request.json()
    fornecedor=payload.get("fornecedor") or {}
    faturado=payload.get("faturado") or {}
    tipo_movimento = str(payload.get("tipo_movimento", "APAGAR")).upper()
    entidade_categoria = "tipos_receita" if tipo_movimento == "ARECEBER" else "tipos_despesa"
    despesas=payload.get("tipo_despesa") or payload.get("classificacao_despesa") or []
    if isinstance(despesas,str): despesas=[despesas]
    filtro_registros, parametros_registros = filtro_proprietario(request)
    def achar(entidade, termos):
        with conectar_db() as conn: rows=conn.execute(f"SELECT * FROM registros WHERE entidade=? AND status='ATIVO'{filtro_registros}",(entidade, *parametros_registros)).fetchall()
        for row in rows:
            dados=json.loads(row["dados"])
            for termo in termos:
                if termo and any(str(v).strip().casefold()==str(termo).strip().casefold() for v in dados.values() if v):
                    return {"existe":True,"id":row["id"],"dados":dados}
        return {"existe":False,"id":None,"dados":None}
    f=achar("fornecedores",[fornecedor.get("razao_social"),fornecedor.get("cnpj")])
    fat=achar("faturados",[faturado.get("nome_completo"),faturado.get("nome"),faturado.get("cpf"),faturado.get("cnpj")])
    resultados=[]
    for d in despesas:
        descricao=d if isinstance(d,str) else (d.get("descricao") or d.get("nome") or str(d))
        achado=achar("classificacoes",[descricao])
        if not achado["existe"]: achado=achar(entidade_categoria,[descricao])
        resultados.append({"descricao":descricao,**achado})
    return {"fornecedor":{"nome":fornecedor.get("razao_social",""),"cnpj":fornecedor.get("cnpj",""),**f},"faturado":{"nome":faturado.get("nome_completo") or faturado.get("nome",""),"cpf":faturado.get("cpf",""),**fat},"despesas":resultados}

@app.post("/api/registrar-nota")
async def registrar_nota(request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401,content={"detail":"Usuário não autenticado."})
    payload=await request.json()
    nota=payload.get("nota",{})
    if not isinstance(nota, dict):
        return JSONResponse(status_code=400, content={"detail": "Os dados da nota devem ser um objeto."})
    fornecedor=nota.get("fornecedor") or {}
    faturado=nota.get("faturado") or {}
    if not isinstance(fornecedor, dict) or not isinstance(faturado, dict):
        return JSONResponse(status_code=400, content={"detail": "Fornecedor e faturado devem conter objetos de dados."})
    try:
        normalizar_documentos(fornecedor)
        normalizar_documentos(faturado)
    except ValueError as erro:
        return JSONResponse(status_code=400, content={"detail": str(erro)})
    preencher_vencimento_ausente(nota)
    tipo_movimento = str(nota.get("tipo_movimento", "APAGAR")).upper()
    if tipo_movimento not in {"APAGAR", "ARECEBER"}:
        return JSONResponse(status_code=400, content={"detail": "Tipo de movimento extraído inválido."})
    if nota.get("requer_revisao") and nota.get("revisado") is not True:
        return JSONResponse(
            status_code=409,
            content={"detail": "A classificação tem baixa confiança. Revise os dados e confirme a revisão humana antes de registrar."}
        )
    subcategoria = str(nota.get("subcategoria", "")).strip()
    if subcategoria not in {"Insumos", "Operacional", "Venda de Produção"}:
        return JSONResponse(status_code=400, content={"detail": "Informe uma subcategoria válida após revisar o documento."})
    pessoa_nome = str(
        nota.get("favorecido")
        or faturado.get("nome_completo")
        or faturado.get("nome")
        or ""
    ).strip()
    try:
        documento_id = int(nota.get("documento_id", 0))
    except (ValueError, TypeError):
        documento_id = 0
    if not pessoa_nome or not documento_id:
        return JSONResponse(status_code=400, content={"detail": "A nota precisa indicar a pessoa favorecida e o documento de origem."})
    filtro_documento, parametros_documento = filtro_proprietario(request)
    with conectar_db() as conn:
        documento = conn.execute(
            f"SELECT nome_arquivo FROM documentos WHERE id=? AND movimento_id IS NULL{filtro_documento}",
            (documento_id, *parametros_documento)
        ).fetchone()
    if not documento:
        return JSONResponse(status_code=409, content={"detail": "O documento de origem não existe ou já está vinculado."})
    documento_origem = documento["nome_arquivo"]
    parcelas=nota.get("parcelas") or []
    if not isinstance(parcelas, list):
        return JSONResponse(status_code=400, content={"detail": "As parcelas extraídas devem ser uma lista."})
    if not parcelas:
        try:
            valor_total = converter_valor_monetario(nota.get("valor_total", 0))
            parcelas=[{"numero":1,"data_vencimento":nota.get("data_vencimento") or nota.get("data_emissao"),"valor":valor_total}]
        except ValueError as erro:
            return JSONResponse(status_code=400, content={"detail": f"Valor ou vencimento inválido na nota: {erro}"})
    try:
        for parcela in parcelas:
            if not isinstance(parcela, dict):
                raise ValueError("Parcela inválida.")
            parcela["data_vencimento"] = normalizar_data_iso(parcela.get("data_vencimento"))
            parcela["valor"] = converter_valor_monetario(parcela.get("valor", 0))
            parcela["numero"] = int(parcela.get("numero", 1))
    except (ValueError, TypeError) as erro:
        return JSONResponse(status_code=400, content={"detail": f"Confira os vencimentos e valores das parcelas: {erro}"})
    def criar_se_nao_existir(entidade, dados, chave):
        valor=next((str(dados.get(k,"" )).strip() for k in chave if dados.get(k)),"")
        filtro, parametros = filtro_proprietario(request)
        with conectar_db() as conn:
            rows=conn.execute(f"SELECT * FROM registros WHERE entidade=? AND status='ATIVO'{filtro}",(entidade, *parametros)).fetchall()
            for r in rows:
                atual=json.loads(r["dados"])
                if valor and any(str(atual.get(k,"")).strip().casefold()==valor.casefold() for k in chave): return r["id"]
            campos=ENTIDADES[entidade]["campos"]
            novo={c:str(dados.get(c,"")) for c in campos}
            agora=datetime.now().isoformat(timespec="seconds")
            cur=conn.execute("INSERT INTO registros(entidade,dados,status,criado_em,atualizado_em,usuario_id) VALUES(?,?,?,?,?,?)",(entidade,json.dumps(novo,ensure_ascii=False),"ATIVO",agora,agora,usuario_id_sessao(request)))
            return cur.lastrowid
    fid=criar_se_nao_existir("fornecedores",fornecedor,["cnpj","razao_social"])
    fatdados={"nome":faturado.get("nome_completo") or faturado.get("nome") or pessoa_nome,"cpf":faturado.get("cpf",""),"cnpj":faturado.get("cnpj",""),"observacao":"Criado pela leitura da nota fiscal"}
    fatid=criar_se_nao_existir("faturados",fatdados,["cpf","cnpj","nome"])
    classificacoes=nota.get("tipo_despesa") or nota.get("classificacao_despesa") or []
    if isinstance(classificacoes,str): classificacoes=[classificacoes]
    class_ids=[]
    entidade_classificacao = "tipos_receita" if tipo_movimento == "ARECEBER" else "tipos_despesa"
    for c in classificacoes:
        desc=c if isinstance(c,str) else c.get("descricao",str(c))
        cid=criar_se_nao_existir(entidade_classificacao,{"descricao":desc,"observacao":"Criado pela leitura do documento"},["descricao"])
        class_ids.append({"id":cid,"descricao":desc})
    dados_mov={"fornecedor_id":fid,"faturado_id":fatid,"pessoa_id":fatid,"pessoa_entidade":"faturados","numero_nota":nota.get("numero_nota_fiscal"),"data_emissao":nota.get("data_emissao"),"valor_total":nota.get("valor_total"),"classificacoes":class_ids,"pessoa":pessoa_nome,"subcategoria":subcategoria,"documento_id":documento_id,"documento_origem":documento_origem,"requer_revisao":bool(nota.get("requer_revisao")),"nota":nota}
    with conectar_db() as conn:
        usuario_id = usuario_id_sessao(request)
        cur=conn.execute("INSERT INTO movimentos(tipo,dados,status,criado_em,usuario_id) VALUES(?,?,?,?,?)",(tipo_movimento,json.dumps(dados_mov,ensure_ascii=False),"ATIVO",datetime.now().isoformat(timespec="seconds"),usuario_id))
        mid=cur.lastrowid
        for i,par in enumerate(parcelas,1):
            ident=str(par.get("identificacao") or f"NF-{nota.get('numero_nota_fiscal','SEMNUM')}-{i}-{mid}")
            conn.execute("INSERT INTO parcelas(movimento_id,identificacao,numero,data_vencimento,valor,status) VALUES(?,?,?,?,?,?)",(mid,ident,int(par.get("numero",i)),par.get("data_vencimento"),par["valor"],"ATIVO"))
        condicao_documento = " AND usuario_id=?" if usuario_id is not None else ""
        parametros_vinculo = (mid, documento_id, usuario_id) if usuario_id is not None else (mid, documento_id)
        vinculo = conn.execute(
            f"UPDATE documentos SET movimento_id=?,status='VINCULADO' WHERE id=? AND movimento_id IS NULL{condicao_documento}",
            parametros_vinculo
        )
        if not vinculo.rowcount:
            raise sqlite3.IntegrityError("O documento já foi vinculado a outro movimento.")
    return {"sucesso":True,"movimento_id":mid,"fornecedor_id":fid,"faturado_id":fatid,"classificacoes":class_ids,"parcelas":len(parcelas),"mensagem":"Fornecedor, faturado, classificações, movimento e parcelas foram verificados/registrados com sucesso."}


@app.get("/api/relatorios/contas")
async def relatorio_contas(
    request: Request,
    tipo: str = "APAGAR",
    data_inicio: str = "",
    data_fim: str = ""
):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    tipo = tipo.upper()
    if tipo not in {"APAGAR", "ARECEBER"}:
        return JSONResponse(status_code=400, content={"detail": "Tipo deve ser APAGAR ou ARECEBER."})
    try:
        inicio = date.fromisoformat(data_inicio) if data_inicio else None
        fim = date.fromisoformat(data_fim) if data_fim else None
        if inicio and fim and inicio > fim:
            raise ValueError
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Informe um período válido."})
    filtro, parametros = filtro_proprietario(request, "m.")
    with conectar_db() as conn:
        rows = conn.execute(
            "SELECT m.id AS movimento_id,m.tipo,m.dados,p.id AS parcela_id,p.numero,p.data_vencimento,p.valor,p.status "
            "FROM movimentos m JOIN parcelas p ON p.movimento_id=m.id "
            f"WHERE m.tipo=? AND m.status='ATIVO' AND p.status='ATIVO'{filtro} ORDER BY p.data_vencimento,p.numero",
            (tipo, *parametros)
        ).fetchall()
    hoje = date.today()
    contas = []
    for row in rows:
        dados = json.loads(row["dados"])
        vencimento = row["data_vencimento"]
        venc_data = date.fromisoformat(vencimento) if vencimento else None
        if inicio and (not venc_data or venc_data < inicio):
            continue
        if fim and (not venc_data or venc_data > fim):
            continue
        contas.append({
            "movimento_id": row["movimento_id"],
            "parcela_id": row["parcela_id"],
            "numero": row["numero"],
            "data_vencimento": vencimento,
            "pessoa": dados.get("pessoa", "—"),
            "subcategoria": dados.get("subcategoria", "—"),
            "documento_origem": dados.get("documento_origem", "—"),
            "valor": row["valor"],
            "status": row["status"],
            "vencida": row["status"] == "ATIVO" and venc_data is not None and venc_data < hoje,
        })
    return {"tipo": tipo, "contas": contas}


@app.get("/api/relatorios/fluxo-caixa")
async def relatorio_fluxo_caixa(
    request: Request,
    data_inicio: str = "",
    data_fim: str = ""
):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    try:
        inicio = date.fromisoformat(data_inicio) if data_inicio else None
        fim = date.fromisoformat(data_fim) if data_fim else None
        if inicio and fim and inicio > fim:
            raise ValueError
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Informe um período válido."})
    filtro, parametros = filtro_proprietario(request, "m.")
    with conectar_db() as conn:
        rows = conn.execute(
            "SELECT f.data_movimento,f.tipo,f.valor,m.dados,p.numero "
            "FROM movimentos_financeiros f JOIN parcelas p ON p.id=f.parcela_id "
            f"JOIN movimentos m ON m.id=p.movimento_id WHERE 1=1{filtro} ORDER BY f.data_movimento",
            parametros
        ).fetchall()
    lancamentos = []
    grupos_pessoa = {}
    grupos_categoria = {}
    grupos_periodo = {}
    receitas = despesas = 0.0
    for row in rows:
        data_evento = date.fromisoformat(row["data_movimento"])
        if inicio and data_evento < inicio or fim and data_evento > fim:
            continue
        dados = json.loads(row["dados"])
        valor = float(row["valor"])
        if row["tipo"] == "ARECEBER":
            receitas += valor
        else:
            despesas += valor
        periodo = data_evento.strftime("%Y-%m")
        pessoa = dados.get("pessoa", "—")
        categoria = dados.get("subcategoria", "—")
        for grupo, chave in (
            (grupos_pessoa, pessoa),
            (grupos_categoria, categoria),
            (grupos_periodo, periodo),
        ):
            valores = grupo.setdefault(chave, {"receitas": 0.0, "despesas": 0.0})
            valores["receitas" if row["tipo"] == "ARECEBER" else "despesas"] += valor
        lancamentos.append({
            "data": row["data_movimento"],
            "tipo": row["tipo"],
            "pessoa": pessoa,
            "subcategoria": categoria,
            "valor": valor,
        })
    return {
        "resumo": {"receitas": receitas, "despesas": despesas, "saldo": receitas - despesas},
        "por_pessoa": grupos_pessoa,
        "por_categoria": grupos_categoria,
        "por_periodo": grupos_periodo,
        "lancamentos": lancamentos,
    }


def importar_anexos_email():
    host = os.getenv("IMAP_HOST")
    usuario = os.getenv("IMAP_USER")
    senha = os.getenv("IMAP_PASSWORD")
    if not host or not usuario or not senha:
        return []
    proprietario_email = re.sub(r"\D", "", os.getenv("IMAP_OWNER_CPF", ""))
    if len(proprietario_email) != 11:
        raise ValueError("Configure IMAP_OWNER_CPF com o CPF da conta proprietária dos anexos.")
    with conectar_db() as conn:
        conta = conn.execute(
            "SELECT id FROM usuarios WHERE documento=? AND status='ATIVO'",
            (proprietario_email,)
        ).fetchone()
    if not conta:
        raise ValueError("IMAP_OWNER_CPF não corresponde a uma conta ativa cadastrada.")
    proprietario_id = conta["id"]
    porta = int(os.getenv("IMAP_PORT", "993"))
    pasta = os.getenv("IMAP_FOLDER", "INBOX")
    cliente = imaplib.IMAP4_SSL(host, porta)
    importados = []
    try:
        cliente.login(usuario, senha)
        status, _ = cliente.select(pasta)
        if status != "OK":
            raise imaplib.IMAP4.error(f"Não foi possível abrir a pasta IMAP {pasta}.")
        status, resultados = cliente.search(None, "UNSEEN")
        if status != "OK":
            raise imaplib.IMAP4.error("Não foi possível consultar as mensagens não lidas.")
        for mensagem_id in resultados[0].split():
            status, partes = cliente.fetch(mensagem_id, "(RFC822)")
            if status != "OK":
                raise imaplib.IMAP4.error("Não foi possível baixar uma mensagem.")
            mensagem_bytes = next(
                (
                    parte[1] for parte in partes
                    if isinstance(parte, tuple) and isinstance(parte[1], bytes)
                ),
                None
            )
            if mensagem_bytes is None:
                raise imaplib.IMAP4.error("A mensagem baixada não contém conteúdo.")
            mensagem = BytesParser(policy=policy.default).parsebytes(mensagem_bytes)
            for parte in mensagem.walk():
                nome = parte.get_filename()
                if not nome or Path(nome).suffix.lower() != ".pdf":
                    continue
                conteudo = parte.get_payload(decode=True)
                if not conteudo:
                    continue
                documento_id, nome_seguro = salvar_documento(nome, conteudo, "EMAIL", proprietario_id)
                with conectar_db() as conn:
                    row = conn.execute("SELECT caminho FROM documentos WHERE id=?", (documento_id,)).fetchone()
                importados.append((documento_id, nome_seguro, row["caminho"]))
            cliente.store(mensagem_id, "+FLAGS", "\\Seen")
    finally:
        try:
            cliente.logout()
        except imaplib.IMAP4.error:
            pass
    return importados


async def monitorar_caixa_email():
    intervalo = max(60, int(os.getenv("IMAP_POLL_SECONDS", "300")))
    while True:
        try:
            anexos = await asyncio.to_thread(importar_anexos_email)
            for documento_id, nome, caminho in anexos:
                if extrator is None or classificar is None:
                    print(f"PDF recebido por e-mail aguardando agentes: {nome}")
                    continue
                with conectar_db() as conn:
                    documento = conn.execute(
                        "SELECT usuario_id FROM documentos WHERE id=?",
                        (documento_id,)
                    ).fetchone()
                if not documento:
                    raise sqlite3.Error(f"Documento de e-mail {documento_id} não encontrado.")
                trabalho_id = str(uuid.uuid4())
                criar_trabalho(trabalho_id, "aguardando", "PDF recebido por e-mail.", None)
                trabalhos[trabalho_id]["usuario_id"] = documento["usuario_id"]
                trabalhos[trabalho_id]["documento_id"] = documento_id
                trabalhos[trabalho_id]["nome_arquivo"] = nome
                asyncio.create_task(processar_trabalho(trabalho_id, caminho))
        except (OSError, ValueError, imaplib.IMAP4.error, sqlite3.Error) as erro:
            print(f"Falha ao monitorar a caixa de e-mail: {erro}")
        await asyncio.sleep(intervalo)


def enviar_alertas_vencimento(usuario_id=None):
    host = os.getenv("SMTP_HOST")
    remetente = os.getenv("SMTP_FROM")
    if not host or not remetente:
        return 0
    porta = int(os.getenv("SMTP_PORT", "587"))
    usuario_smtp = os.getenv("SMTP_USER", "")
    senha_smtp = os.getenv("SMTP_PASSWORD", "")
    email_padrao = os.getenv("NOTIFICATION_EMAIL", "")
    dias_aviso = max(0, int(os.getenv("ALERTA_DIAS", "3")))
    hoje = date.today()
    limite = (hoje + timedelta(days=dias_aviso)).isoformat()
    filtro, parametros = ("", ()) if usuario_id is None else (" AND m.usuario_id=?", (usuario_id,))
    with conectar_db() as conn:
        movimentos = conn.execute(
            "SELECT p.id AS parcela_id,p.numero,p.data_vencimento,p.valor,m.tipo,m.dados,m.usuario_id "
            "FROM parcelas p JOIN movimentos m ON m.id=p.movimento_id "
            f"WHERE p.status='ATIVO' AND m.status='ATIVO' AND p.data_vencimento<=?{filtro} "
            "ORDER BY p.data_vencimento",
            (limite, *parametros)
        ).fetchall()
        registros = conn.execute(
            "SELECT usuario_id,dados FROM registros WHERE entidade IN ('pessoas','clientes','faturados') AND status='ATIVO'"
        ).fetchall()
        usuarios = conn.execute(
            "SELECT u.id,r.dados FROM usuarios u JOIN registros r ON r.id=u.pessoa_id WHERE u.status='ATIVO'"
        ).fetchall()
        enviados = {
            (row["parcela_id"], row["email"])
            for row in conn.execute(
                "SELECT parcela_id,email FROM notificacoes_enviadas WHERE data_envio=?",
                (hoje.isoformat(),)
            ).fetchall()
        }
    email_por_nome = {}
    email_global_por_nome = {}
    for row in registros:
        dados = json.loads(row["dados"])
        email = str(dados.get("email", "")).strip()
        if email:
            for campo in ("nome", "nome_completo", "razao_social", "nome_fantasia"):
                if dados.get(campo):
                    chave = str(dados[campo]).strip().casefold()
                    email_global_por_nome[chave] = email
                    if row["usuario_id"] is not None:
                        email_por_nome[(row["usuario_id"], chave)] = email
    email_por_usuario = {}
    for row in usuarios:
        dados = json.loads(row["dados"])
        email = str(dados.get("email", "")).strip()
        if email:
            email_por_usuario[row["id"]] = email
    por_destinatario = {}
    for parcela in movimentos:
        dados = json.loads(parcela["dados"])
        nome = str(dados.get("pessoa", "")).strip()
        proprietario_id = parcela["usuario_id"]
        if proprietario_id is None:
            destinatario = email_global_por_nome.get(nome.casefold()) or email_padrao
        else:
            destinatario = (
                email_por_nome.get((proprietario_id, nome.casefold()))
                or email_por_usuario.get(proprietario_id)
            )
        if not destinatario or (parcela["parcela_id"], destinatario) in enviados:
            continue
        por_destinatario.setdefault(destinatario, []).append({
            "id": parcela["parcela_id"],
            "numero": parcela["numero"],
            "vencimento": parcela["data_vencimento"],
            "valor": parcela["valor"],
            "tipo": parcela["tipo"],
            "pessoa": nome,
        })
    if not por_destinatario:
        return 0
    mensagem_email = None
    conexao = None
    try:
        if porta == 465:
            conexao = smtplib.SMTP_SSL(host, porta, timeout=30)
        else:
            conexao = smtplib.SMTP(host, porta, timeout=30)
            conexao.starttls()
        if usuario_smtp:
            conexao.login(usuario_smtp, senha_smtp)
        for destinatario, parcelas in por_destinatario.items():
            mensagem_email = EmailMessage()
            mensagem_email["Subject"] = "Aviso de vencimento - Agente Financeiro"
            mensagem_email["From"] = remetente
            mensagem_email["To"] = destinatario
            linhas = [
                f"{item['tipo']} | parcela {item['numero']} | vencimento {item['vencimento']} | R$ {item['valor']:.2f}"
                for item in parcelas
            ]
            mensagem_email.set_content("Parcelas abertas próximas do vencimento ou vencidas:\n" + "\n".join(linhas))
            conexao.send_message(mensagem_email)
            with conectar_db() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO notificacoes_enviadas(parcela_id,data_envio,email) VALUES(?,?,?)",
                    [(item["id"], hoje.isoformat(), destinatario) for item in parcelas]
                )
    finally:
        if conexao is not None:
            try:
                conexao.quit()
            except smtplib.SMTPException:
                pass
    return sum(len(parcelas) for parcelas in por_destinatario.values())


async def monitorar_vencimentos():
    while True:
        try:
            await asyncio.to_thread(enviar_alertas_vencimento)
        except (OSError, ValueError, smtplib.SMTPException, sqlite3.Error) as erro:
            print(f"Falha ao enviar notificações de vencimento: {erro}")
        await asyncio.sleep(24 * 60 * 60)


@app.post("/api/notificacoes/enviar")
async def enviar_notificacoes(request: Request):
    if not autenticado(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado."})
    if not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM"):
        return JSONResponse(status_code=503, content={"detail": "Configure SMTP_HOST e SMTP_FROM para enviar os alertas."})
    try:
        quantidade = await asyncio.to_thread(enviar_alertas_vencimento, usuario_id_sessao(request))
    except (OSError, ValueError, smtplib.SMTPException, sqlite3.Error) as erro:
        return JSONResponse(status_code=502, content={"detail": f"Não foi possível enviar os alertas: {erro}"})
    return {"sucesso": True, "parcelas_notificadas": quantidade}


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)
