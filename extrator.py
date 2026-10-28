import os
import random
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from Modelos import NotaFiscal

load_dotenv(Path(__file__).with_name(".env"))


class ExtratorAgent:
    """Extrai campos estruturados de uma nota fiscal PDF usando Gemini."""

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY não encontrada. Configure essa variável no arquivo .env."
            )
        self.client = genai.Client(api_key=api_key)
        modelo_principal = os.getenv("GEMINI_MODEL", "gemini-3.3-flash").strip() or "gemini-3.3-flash"
        self.modelos = list(dict.fromkeys([
            modelo_principal,
            "gemini-3.3-flash",
            "gemini-3.8-flash",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ]))

    def extrator(self, caminho_pdf: str) -> NotaFiscal:
        print("Enviando PDF para o Gemini...")
        arquivo = self.client.files.upload(file=caminho_pdf)
        prompt = """
Extraia os dados estruturados da nota fiscal:
- fornecedor: razao_social, nome_fantasia, fantasia, cnpj
- faturado: nome, nome_completo, cpf, cnpj
- numero_nota_fiscal, tipo_documento, favorecido, data_emissao (YYYY-MM-DD) e
  data_vencimento (YYYY-MM-DD) quando informada
- descricao_produtos: lista de descrições dos produtos/serviços
- quantidade_parcelas e parcelas (cada uma com numero, data_vencimento YYYY-MM-DD e valor)
- valor_total
Retorne somente os dados compatíveis com o esquema JSON fornecido.
"""
        ultimo_erro = None
        for modelo in self.modelos:
            for tentativa in range(3):
                try:
                    resposta = self.client.models.generate_content(
                        model=modelo,
                        contents=[arquivo, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=NotaFiscal,
                        ),
                    )
                    if not resposta.text:
                        raise RuntimeError("O Gemini retornou uma resposta vazia.")
                    nota = NotaFiscal.model_validate_json(resposta.text)
                    if nota.fornecedor:
                        if not nota.fornecedor.nome_fantasia and nota.fornecedor.fantasia:
                            nota.fornecedor.nome_fantasia = nota.fornecedor.fantasia
                        elif not nota.fornecedor.fantasia and nota.fornecedor.nome_fantasia:
                            nota.fornecedor.fantasia = nota.fornecedor.nome_fantasia
                    return nota
                except Exception as exc:
                    ultimo_erro = exc
                    erro_texto = str(exc).upper()
                    modelo_indisponivel = any(s in erro_texto for s in ("404", "NOT_FOUND", "NO LONGER AVAILABLE"))
                    if modelo_indisponivel:
                        print(f"Modelo {modelo} indisponível; tentando próximo modelo...")
                        break
                    temporario = any(s in erro_texto for s in (
                        "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
                        "408", "TIMEOUT", "INTERNAL SERVER ERROR"
                    ))
                    if not temporario:
                        raise RuntimeError(f"Erro ao extrair os dados da nota fiscal: {exc}") from exc
                    if tentativa < 2:
                        espera = 2 ** (tentativa + 1) + random.uniform(0, 1.5)
                        print(f"Falha temporária em {modelo}; nova tentativa em {espera:.1f}s.")
                        time.sleep(espera)

        raise RuntimeError(f"O Gemini não conseguiu processar o PDF. Último erro: {ultimo_erro}")
