import json
import os
import random
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).with_name(".env"))

CATEGORIAS_DESPESA = """
INSUMOS AGRÍCOLAS: Sementes; Fertilizantes; Defensivos Agrícolas; Corretivos.
MANUTENÇÃO E OPERAÇÃO: Combustíveis/Lubrificantes; Peças/Parafusos/Componentes Mecânicos;
Manutenção de Máquinas/Equipamentos; Pneus/Filtros/Correias; Ferramentas/Utensílios.
RECURSOS HUMANOS: Mão de Obra Temporária; Salários e Encargos.
SERVIÇOS OPERACIONAIS: Frete/Transporte; Colheita Terceirizada; Secagem/Armazenagem;
Pulverização/Aplicação.
INFRAESTRUTURA E UTILIDADES: Energia Elétrica; Arrendamento de Terras; Construções/Reformas;
Materiais de Construção.
ADMINISTRATIVAS: Honorários Contábeis/Advocatícios/Agronômicos; Despesas Bancárias/Financeiras.
SEGUROS E PROTEÇÃO: Seguro Agrícola; Seguro de Ativos; Seguro Prestamista.
IMPOSTOS E TAXAS: ITR; IPTU; IPVA; INCRA-CCIR.
INVESTIMENTOS: Aquisição de Máquinas/Implementos; Veículos; Imóveis; Infraestrutura Rural.
"""


class ClassificarAgent:
    """Classifica documentos financeiros e identifica casos que precisam de revisão."""

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não encontrada. Configure o arquivo .env.")
        self.client = genai.Client(api_key=api_key)
        modelo_principal = os.getenv("GEMINI_MODEL", "gemini-3.3-flash").strip() or "gemini-3.3-flash"
        self.modelos = list(dict.fromkeys([
            modelo_principal,
            "gemini-3.3-flash",
            "gemini-3.8-flash",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ]))

    def classificar(self, nota):
        produtos = getattr(nota, "descricao_produtos", None) or []
        if isinstance(nota, dict):
            produtos = nota.get("descricao_produtos", nota.get("produtos", [])) or []
        prompt = f"""
Classifique o documento como despesa ou receita e escolha uma subcategoria.
Use somente estas subcategorias: "Insumos", "Operacional" ou "Venda de Produção".
Estime a confiança entre 0 e 1 com base nos dados disponíveis; use valor baixo
quando o tipo ou a subcategoria não estiverem claros.
Retorne JSON com tipo_movimento ("APAGAR" ou "ARECEBER"), subcategoria,
confianca (número entre 0 e 1), tipo_despesa (lista de categorias da taxonomia
abaixo, ou lista vazia para receita) e tipo_documento.
Não invente valores ausentes.

Categorias disponíveis:
{CATEGORIAS_DESPESA}

Produtos/serviços:
{json.dumps(produtos, ensure_ascii=False)}
"""
        ultimo_erro = None
        for modelo in self.modelos:
            for tentativa in range(3):
                try:
                    resposta = self.client.models.generate_content(
                        model=modelo,
                        contents=[prompt],
                        config=types.GenerateContentConfig(response_mime_type="application/json"),
                    )
                    if not resposta.text:
                        raise RuntimeError("O Gemini retornou uma resposta vazia.")
                    dados = json.loads(resposta.text)
                    tipos = dados.get("tipo_despesa", [])
                    if isinstance(tipos, str):
                        tipos = [tipos]
                    if not isinstance(tipos, list):
                        tipos = []
                    try:
                        confianca = float(dados.get("confianca", 0))
                    except (TypeError, ValueError):
                        confianca = 0
                    if not 0 <= confianca <= 1:
                        confianca = 0
                    tipo_movimento = str(dados.get("tipo_movimento", "")).upper()
                    if tipo_movimento not in {"APAGAR", "ARECEBER"}:
                        tipo_movimento = "APAGAR"
                        confianca = min(confianca, 0.49)
                    subcategoria = str(dados.get("subcategoria", "")).strip()
                    if subcategoria not in {"Insumos", "Operacional", "Venda de Produção"}:
                        subcategoria = ""
                        confianca = min(confianca, 0.49)
                    return {
                        "tipo_despesa": tipos,
                        "tipo_movimento": tipo_movimento,
                        "subcategoria": subcategoria,
                        "confianca": confianca,
                        "requer_revisao": confianca < 0.65,
                        "tipo_documento": str(dados.get("tipo_documento", "")).strip(),
                    }
                except Exception as exc:
                    ultimo_erro = exc
                    texto = str(exc).upper()
                    modelo_indisponivel = any(s in texto for s in ("404", "NOT_FOUND", "NO LONGER AVAILABLE"))
                    if modelo_indisponivel:
                        print(f"Modelo {modelo} indisponível; tentando próximo modelo...")
                        break
                    temporario = any(s in texto for s in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "408", "TIMEOUT"))
                    if not temporario:
                        raise RuntimeError(f"Erro ao classificar a despesa: {exc}") from exc
                    if tentativa < 2:
                        espera = 2 ** (tentativa + 1) + random.uniform(0, 1.5)
                        print(f"Falha temporária em {modelo}; nova tentativa em {espera:.1f}s.")
                        time.sleep(espera)
        raise RuntimeError(f"O Gemini não conseguiu classificar a despesa. Último erro: {ultimo_erro}")
