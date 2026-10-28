-- Banco de dados do projeto (SQLite) - identico ao que o main.py cria (inicializar_db)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS registros (id INTEGER PRIMARY KEY AUTOINCREMENT, entidade TEXT NOT NULL, dados TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ATIVO', criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL, usuario_id INTEGER REFERENCES usuarios(id));

CREATE TABLE IF NOT EXISTS movimentos (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, dados TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ATIVO', criado_em TEXT NOT NULL, usuario_id INTEGER REFERENCES usuarios(id));

CREATE TABLE IF NOT EXISTS parcelas (id INTEGER PRIMARY KEY AUTOINCREMENT, movimento_id INTEGER NOT NULL, identificacao TEXT NOT NULL UNIQUE, numero INTEGER NOT NULL, data_vencimento TEXT, valor REAL NOT NULL, status TEXT NOT NULL DEFAULT 'ATIVO', FOREIGN KEY(movimento_id) REFERENCES movimentos(id));

CREATE TABLE IF NOT EXISTS status_parcelas_arquivados (parcela_id INTEGER PRIMARY KEY, movimento_id INTEGER NOT NULL, status_anterior TEXT NOT NULL, FOREIGN KEY(parcela_id) REFERENCES parcelas(id), FOREIGN KEY(movimento_id) REFERENCES movimentos(id));

CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, pessoa_id INTEGER NOT NULL UNIQUE, cpf TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ATIVO', criado_em TEXT NOT NULL, login TEXT, documento TEXT, FOREIGN KEY(pessoa_id) REFERENCES registros(id));

CREATE TABLE IF NOT EXISTS movimentos_financeiros (id INTEGER PRIMARY KEY AUTOINCREMENT, parcela_id INTEGER NOT NULL, tipo TEXT NOT NULL, valor REAL NOT NULL, data_movimento TEXT NOT NULL, comprovante TEXT, criado_em TEXT NOT NULL, FOREIGN KEY(parcela_id) REFERENCES parcelas(id));

CREATE TABLE IF NOT EXISTS documentos (id INTEGER PRIMARY KEY AUTOINCREMENT, nome_arquivo TEXT NOT NULL, caminho TEXT NOT NULL, origem TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDENTE', recebido_em TEXT NOT NULL, movimento_id INTEGER, usuario_id INTEGER REFERENCES usuarios(id), FOREIGN KEY(movimento_id) REFERENCES movimentos(id));

CREATE TABLE IF NOT EXISTS notificacoes_enviadas (id INTEGER PRIMARY KEY AUTOINCREMENT, parcela_id INTEGER NOT NULL, data_envio TEXT NOT NULL, email TEXT NOT NULL, UNIQUE(parcela_id,data_envio,email), FOREIGN KEY(parcela_id) REFERENCES parcelas(id));

CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_login ON usuarios(login COLLATE NOCASE);

CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_documento ON usuarios(documento);

CREATE INDEX IF NOT EXISTS idx_registros_usuario ON registros(usuario_id,entidade,status);

CREATE INDEX IF NOT EXISTS idx_movimentos_usuario ON movimentos(usuario_id,status);

CREATE INDEX IF NOT EXISTS idx_documentos_usuario ON documentos(usuario_id,movimento_id);
