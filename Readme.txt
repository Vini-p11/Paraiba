PROJETO 
1. OBJETIVO
Sistema web desenvolvido em Python com FastAPI
para processamento de notas fiscais em PDF
utilizando agentes de inteligência artificial.

O sistema recebe uma nota fiscal em PDF e utiliza
agentes de IA para interpretar os dados.

O sistema identifica:

- Fornecedor
- Razão Social
- Nome Fantasia
- CNPJ
- Faturado
- Nome Completo
- CPF
- Número da Nota Fiscal
- Data de Emissão
- Produtos
- Quantidade de Parcelas
- Data de Vencimento
- Valor das Parcelas
- Valor Total
- Classificação da Despesa

CPF aceita até 11 dígitos e CNPJ até 14 dígitos.
Quando a nota não informa o vencimento, o sistema usa a data de emissão
como vencimento da nota e das parcelas sem data informada.

2. AGENTES
AGENTE 1
Nome:
ExtractorAgent
Responsabilidade:
Interpretar o PDF da nota fiscal e extrair
as informações estruturadas.

AGENTE 2
Nome:
ClassifierAgent
Responsabilidade:
Interpretar os produtos e classificar
o tipo de despesa.

3. FLUXO
Usuário
↓
Login
↓
Upload do PDF
↓
Agente 1
↓
Extração das informações
↓
Agente 2
↓
Classificação da despesa
↓
JSON final
↓
Tela Web

4. ESTRUTURA

main.py
extrator.py
classificar.py
modelos.py
index.html
login.html
requirements.txt
README.txt
.env

6. HOSPEDAGEM
O projeto possui Procfile preparado para
serviços de hospedagem como Render.

7. CATEGORIAS DE DESPESA

INSUMOS AGRÍCOLAS
MANUTENÇÃO E OPERAÇÃO
RECURSOS HUMANOS
SERVIÇOS OPERACIONAIS
INFRAESTRUTURA E UTILIDADES
ADMINISTRATIVAS
SEGUROS E PROTEÇÃO
IMPOSTOS E TAXAS
INVESTIMENTOS

8. EXEMPLOS
Óleo Diesel
→ MANUTENÇÃO E OPERAÇÃO

Material Hidráulico
→ INFRAESTRUTURA E UTILIDADES

Sementes
→ INSUMOS AGRÍCOLAS

Fertilizantes
→ INSUMOS AGRÍCOLAS

Frete
→ SERVIÇOS OPERACIONAIS

Seguro Agrícola
→ SEGUROS E PROTEÇÃO

9. LIMITE DO PDF
O sistema permite PDF de até 50 MB.

10. PROCESSAMENTO EM TEMPO REAL
A interface consulta o servidor enquanto
o processamento está acontecendo.
Mensagens apresentadas:
Enviando PDF
Agente 1 processando
Agente 2 classificando
Processamento concluído

11. CADASTRO E ACESSO
Cada conta usa um login único e senha; a senha é armazenada com hash PBKDF2.
No acesso, são solicitados somente login e senha. No cadastro, login, senha,
e-mail, CPF ou CNPJ, nome completo e data de nascimento do titular são
obrigatórios; a idade é calculada e exibida automaticamente.
Para menores de 18 anos, são exigidos nome e CPF do responsável e uma
confirmação de autorização. Essa confirmação é uma declaração registrada
no sistema; o sistema não verifica a identidade do responsável.
CPF e CNPJ são armazenados somente com dígitos. Na atualização do banco, o CPF
das contas existentes é mantido como login para preservar o acesso.
Cada conta vê e altera apenas os próprios cadastros, documentos, movimentos,
baixas e relatórios; a conta administrativa mantém acesso completo.
Registros antigos sem proprietário permanecem visíveis somente à administração,
pois o sistema não consegue atribuí-los a uma pessoa com segurança.

12. FINANCEIRO E RELATÓRIOS
Despesas e receitas são lançamentos associados a um cadastro ativo de pessoa,
cliente ou faturado, além de subcategoria, documento de origem e parcelas
com vencimento. Pagamentos e recebimentos
exigem comprovante PDF ou imagem e ficam registrados separadamente.
O relatório de fluxo de caixa agrega valores por pessoa, categoria e mês.
Os relatórios de contas mostram parcelas abertas e sinalizam as vencidas.
As subcategorias disponíveis são Insumos, Operacional e Venda de Produção.
Classificações com confiança abaixo de 0,65 ficam sinalizadas para revisão
humana e só podem ser registradas após confirmação.

13. E-MAIL E ALERTAS
Para monitorar anexos PDF recebidos, configure no ambiente:
IMAP_HOST, IMAP_PORT (opcional; padrão 993), IMAP_USER, IMAP_PASSWORD,
IMAP_OWNER_CPF (CPF da conta proprietária dos anexos), IMAP_FOLDER
(opcional; padrão INBOX) e IMAP_POLL_SECONDS (opcional; padrão 300 segundos).
Os anexos importados ficam visíveis apenas para essa conta e para a
administração.
Use [.env.example](.env.example) como modelo e preencha os valores no arquivo
.env local. Os avisos de serviço desativado não são exibidos; confira
/api/health para verificar se cada integração está configurada.

Para alertas automáticos de vencimento, configure:
SMTP_HOST, SMTP_PORT (opcional; padrão 587), SMTP_FROM, SMTP_USER,
SMTP_PASSWORD e, quando os cadastros não tiverem e-mail correspondente,
NOTIFICATION_EMAIL. SMTP_PORT 465 usa conexão SSL; outras portas usam
STARTTLS. ALERTA_DIAS define quantos dias antes do vencimento avisar
(padrão 3). As notificações são enviadas diariamente.

Alertas de dados de uma conta são enviados ao e-mail cadastrado nela ou
no contato do lançamento; NOTIFICATION_EMAIL é usado apenas para movimentos
administrativos sem proprietário.

Os serviços de e-mail permanecem desativados enquanto as variáveis
necessárias não estiverem definidas. Os documentos enviados e recebidos
por e-mail são armazenados na pasta documentos. DATABASE_PATH pode ser
definido para escolher outro arquivo SQLite.