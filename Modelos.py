from pydantic import BaseModel, Field
from typing import Optional, List


class Parcela(BaseModel):
    identificacao: Optional[str] = None
    numero: int = 1
    data_vencimento: Optional[str] = None
    valor: float = 0.0


class Fornecedor(BaseModel):
    razao_social: str = ""
    nome_fantasia: Optional[str] = ""
    fantasia: Optional[str] = ""
    cnpj: str = ""


class Faturado(BaseModel):
    nome: str = ""
    nome_completo: str = ""
    cpf: str = ""
    cnpj: str = ""


class Classificacao(BaseModel):
    descricao: str = ""
    tipo: str = "DESPESA"


class NotaFiscal(BaseModel):
    numero_nota_fiscal: Optional[str] = None
    tipo_documento: Optional[str] = None
    favorecido: Optional[str] = None
    data_emissao: Optional[str] = None
    data_vencimento: Optional[str] = None
    valor_total: float = 0.0
    quantidade_parcelas: Optional[int] = None
    descricao_produtos: List[str] = Field(default_factory=list)
    fornecedor: Fornecedor = Field(default_factory=Fornecedor)
    faturado: Faturado = Field(default_factory=Faturado)
    tipo_despesa: List[Classificacao] = Field(default_factory=list)
    parcelas: List[Parcela] = Field(default_factory=list)
