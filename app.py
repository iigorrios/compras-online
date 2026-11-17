"""Lista de Compras com comparação de preços.

Rodar:  python app.py   →  http://localhost:5000

Banco: SQLite (arquivo compras.db) por padrão. Para usar PostgreSQL, defina
DATABASE_URL, ex.: postgresql+psycopg://usuario:senha@localhost:5432/compras
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import Flask, abort, jsonify, render_template, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

import scraper

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(app.root_path, "compras.db")
)
db = SQLAlchemy(app)


def agora():
    return datetime.now(timezone.utc)


class Produto(db.Model):
    """Um 'tipo' de produto (ex.: Calcinhas). Cada link é uma oferta dele."""

    __tablename__ = "produtos"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    foto_url = db.Column(db.Text)
    observacao = db.Column(db.Text)
    quantidade = db.Column(db.Integer, nullable=False, default=1)
    # unidade usada para comparar ofertas: un (peças), kg, L ou m
    unidade = db.Column(db.String(10), nullable=False, default="un")
    comprado = db.Column(db.Boolean, nullable=False, default=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=agora)
    links = db.relationship(
        "Link", backref="produto", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self):
        links = sorted(
            (l.to_dict() for l in self.links),
            key=lambda l: (l["por_unidade"] is None, l["por_unidade"] or 0),
        )
        com_preco = [l for l in links if l["por_unidade"] is not None]
        melhor = com_preco[0] if com_preco else None
        pior = com_preco[-1] if com_preco else None
        if melhor:
            melhor["melhor"] = True
            for l in com_preco:
                l["mais_caro_pct"] = round((l["por_unidade"] / melhor["por_unidade"] - 1) * 100, 1)
        # economia: quanto custaria a mesma quantidade da melhor oferta
        # se comprada pelo preço por unidade da pior oferta
        economia = 0.0
        if melhor and pior:
            economia = round((pior["por_unidade"] - melhor["por_unidade"]) * melhor["quantidade"], 2)
        foto = self.foto_url or next((l["imagem"] for l in links if l["imagem"]), None)
        return {
            "id": self.id,
            "nome": self.nome,
            "foto_url": self.foto_url,
            "foto": foto,
            "observacao": self.observacao,
            "quantidade": self.quantidade,
            "unidade": self.unidade,
            "comprado": self.comprado,
            "criado_em": self.criado_em.isoformat() if self.criado_em else None,
            "links": links,
            "compara_kits": any(l["quantidade"] != 1 for l in links) or self.unidade != "un",
            "melhor_total": melhor["total"] if melhor else None,
            "melhor_por_unidade": melhor["por_unidade"] if melhor else None,
            "economia": economia,
        }


class Link(db.Model):
    """Uma oferta: link da loja, preço, frete e quantas unidades vêm nela."""

    __tablename__ = "links"
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id"), nullable=False)
    url = db.Column(db.Text, nullable=False)
    loja = db.Column(db.String(100))
    titulo = db.Column(db.String(300))
    preco = db.Column(db.Numeric(12, 2))
    frete = db.Column(db.Numeric(12, 2))
    quantidade = db.Column(db.Numeric(12, 3), nullable=False, default=1)
    imagem = db.Column(db.Text)
    atualizado_em = db.Column(db.DateTime(timezone=True), default=agora)

    def to_dict(self):
        preco = float(self.preco) if self.preco is not None else None
        frete = float(self.frete) if self.frete is not None else 0.0
        qtd = float(self.quantidade or 1)
        total = round(preco + frete, 2) if preco is not None else None
        return {
            "id": self.id,
            "url": self.url,
            "loja": self.loja,
            "titulo": self.titulo,
            "preco": preco,
            "frete": frete,
            "quantidade": qtd,
            "total": total,
            "por_unidade": round(total / qtd, 4) if total is not None and qtd > 0 else None,
            "imagem": self.imagem,
            "atualizado_em": self.atualizado_em.isoformat() if self.atualizado_em else None,
            "melhor": False,
            "mais_caro_pct": None,
        }

    def detectar_quantidade(self):
        """Preenche a quantidade a partir do título, na unidade do produto."""
        qtd = scraper.quantidade_para(self.titulo, self.produto.unidade)
        if qtd:
            self.quantidade = qtd
        elif self.produto.unidade == "un":
            self.quantidade = 1


def _num(valor):
    if valor in (None, ""):
        return None
    return scraper.parse_preco(valor) if isinstance(valor, str) else float(valor)


def _qtd(valor):
    """Quantidade aceita decimais com vírgula (ex.: 1,6 kg)."""
    if valor in (None, ""):
        return None
    try:
        q = float(str(valor).replace(",", "."))
    except ValueError:
        return None
    return q if q > 0 else None


def _unidade(valor):
    return valor if valor in scraper.UNIDADES else "un"


# ---------------------------------------------------------------- páginas
@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------- API
@app.get("/api/produtos")
def listar_produtos():
    produtos = db.session.scalars(db.select(Produto).order_by(Produto.criado_em.desc()))
    return jsonify([p.to_dict() for p in produtos])


def _novo_link(produto, url, dados, info=None):
    """Cria uma oferta; busca na loja o que não veio preenchido."""
    preco = _num(dados.get("preco"))
    aviso = None
    if info is None and (preco is None or not dados.get("loja")):
        info = scraper.extrair(url)
    info = info or {}
    preco = preco if preco is not None else info.get("preco")
    if preco is None:
        aviso = info.get("erro") or "Não encontrei o preço — preencha manualmente."
    link = Link(
        produto=produto, url=url,
        loja=(dados.get("loja") or "").strip() or info.get("loja") or scraper.nome_loja(url),
        titulo=info.get("nome"), preco=preco, frete=_num(dados.get("frete")),
        imagem=dados.get("imagem") or info.get("imagem"),
    )
    qtd = _qtd(dados.get("quantidade_oferta"))
    if qtd:
        link.quantidade = qtd
    else:
        link.detectar_quantidade()
    db.session.add(link)
    return link, aviso


@app.post("/api/produtos")
def criar_produto():
    """Cria um produto. Se vier um link, o nome/foto/preço são lidos da loja
    (o nome digitado, se houver, tem prioridade)."""
    dados = request.get_json(force=True)
    nome = (dados.get("nome") or "").strip()
    url = (dados.get("url") or "").strip()
    if url and not url.startswith(("http://", "https://")):
        return jsonify(erro="Informe um link começando com http:// ou https://"), 400
    if not nome and not url:
        return jsonify(erro="Informe o nome do produto ou cole um link de compra."), 400

    info = None
    if url:
        info = scraper.extrair(url)
        nome = nome or info["nome"]
        if not nome:
            return jsonify(erro="Não consegui ler o nome do produto nesse link — digite o nome."), 400

    produto = Produto(
        nome=nome[:200],
        foto_url=(dados.get("foto_url") or "").strip() or None,
        observacao=(dados.get("observacao") or "").strip() or None,
        quantidade=int(dados.get("quantidade") or 1),
        unidade=_unidade(dados.get("unidade")),
    )
    db.session.add(produto)
    aviso = None
    if info:
        _, aviso = _novo_link(produto, url, dados, info)
    db.session.commit()
    return jsonify(produto=produto.to_dict(), aviso=aviso), 201


@app.patch("/api/produtos/<int:pid>")
def editar_produto(pid):
    produto = db.get_or_404(Produto, pid)
    dados = request.get_json(force=True)
    for campo in ("nome", "foto_url", "observacao"):
        if campo in dados:
            setattr(produto, campo, (dados[campo] or "").strip() or None)
    if "quantidade" in dados:
        produto.quantidade = max(1, int(dados["quantidade"] or 1))
    if "comprado" in dados:
        produto.comprado = bool(dados["comprado"])
    if "unidade" in dados and _unidade(dados["unidade"]) != produto.unidade:
        produto.unidade = _unidade(dados["unidade"])
        for link in produto.links:  # recalcula a quantidade na nova unidade
            link.detectar_quantidade()
    if not produto.nome:
        abort(400)
    db.session.commit()
    return jsonify(produto.to_dict())


@app.delete("/api/produtos/<int:pid>")
def excluir_produto(pid):
    db.session.delete(db.get_or_404(Produto, pid))
    db.session.commit()
    return "", 204


@app.post("/api/produtos/<int:pid>/juntar")
def juntar_produtos(pid):
    """Move as ofertas deste produto para outro e apaga este."""
    origem = db.get_or_404(Produto, pid)
    destino = db.get_or_404(Produto, int(request.get_json(force=True).get("destino") or 0))
    if origem.id == destino.id:
        return jsonify(erro="Escolha outro produto."), 400
    for link in list(origem.links):
        link.produto = destino
        if destino.unidade != origem.unidade:
            link.detectar_quantidade()
    destino.foto_url = destino.foto_url or origem.foto_url
    db.session.flush()
    db.session.delete(origem)
    db.session.commit()
    return jsonify(produto=destino.to_dict())


@app.post("/api/produtos/<int:pid>/links")
def criar_link(pid):
    produto = db.get_or_404(Produto, pid)
    dados = request.get_json(force=True)
    url = (dados.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify(erro="Informe um link começando com http:// ou https://"), 400
    _, aviso = _novo_link(produto, url, dados)
    db.session.commit()
    return jsonify(produto=produto.to_dict(), aviso=aviso), 201


@app.patch("/api/links/<int:lid>")
def editar_link(lid):
    link = db.get_or_404(Link, lid)
    dados = request.get_json(force=True)
    if "preco" in dados:
        link.preco = _num(dados["preco"])
    if "frete" in dados:
        link.frete = _num(dados["frete"])
    if "quantidade" in dados:
        link.quantidade = _qtd(dados["quantidade"]) or 1
    if "loja" in dados:
        link.loja = (dados["loja"] or "").strip() or link.loja
    link.atualizado_em = agora()
    db.session.commit()
    return jsonify(produto=link.produto.to_dict())


@app.post("/api/links/<int:lid>/atualizar")
def atualizar_link(lid):
    """Busca de novo o preço na loja."""
    link = db.get_or_404(Link, lid)
    info = scraper.extrair(link.url)
    if info["preco"]:
        link.preco = info["preco"]
        link.atualizado_em = agora()
    link.imagem = link.imagem or info["imagem"]
    link.titulo = link.titulo or info["nome"]
    db.session.commit()
    return jsonify(produto=link.produto.to_dict(), aviso=info["erro"])


@app.delete("/api/links/<int:lid>")
def excluir_link(lid):
    link = db.get_or_404(Link, lid)
    produto = link.produto
    db.session.delete(link)
    db.session.commit()
    return jsonify(produto=produto.to_dict())


@app.get("/api/extrair")
def extrair():
    """Pré-visualiza os dados de um link antes de salvar."""
    url = request.args.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify(erro="Link inválido."), 400
    info = scraper.extrair(url)
    info["quantidades"] = scraper.detectar_quantidades(info["nome"])
    return jsonify(info)


# ---------------------------------------------------------------- banco
COLUNAS_NOVAS = {
    "produtos": {"unidade": "VARCHAR(10) NOT NULL DEFAULT 'un'"},
    "links": {
        "titulo": "VARCHAR(300)",
        "quantidade": "NUMERIC(12, 3) NOT NULL DEFAULT 1",
    },
}


def migrar():
    """Cria as tabelas e adiciona colunas novas em bancos já existentes."""
    db.create_all()
    insp = inspect(db.engine)
    with db.engine.begin() as conn:
        for tabela, colunas in COLUNAS_NOVAS.items():
            existentes = {c["name"] for c in insp.get_columns(tabela)}
            for coluna, ddl in colunas.items():
                if coluna not in existentes:
                    conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {ddl}"))


with app.app_context():
    migrar()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
