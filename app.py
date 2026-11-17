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

import scraper

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(app.root_path, "compras.db")
)
db = SQLAlchemy(app)


def agora():
    return datetime.now(timezone.utc)


class Produto(db.Model):
    __tablename__ = "produtos"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    foto_url = db.Column(db.Text)
    observacao = db.Column(db.Text)
    quantidade = db.Column(db.Integer, nullable=False, default=1)
    comprado = db.Column(db.Boolean, nullable=False, default=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=agora)
    links = db.relationship(
        "Link", backref="produto", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self):
        links = sorted(
            (l.to_dict() for l in self.links),
            key=lambda l: (l["total"] is None, l["total"] or 0),
        )
        com_preco = [l for l in links if l["total"] is not None]
        melhor = com_preco[0] if com_preco else None
        if melhor:
            melhor["melhor"] = True
        pior = com_preco[-1] if com_preco else None
        foto = self.foto_url or next((l["imagem"] for l in links if l["imagem"]), None)
        return {
            "id": self.id,
            "nome": self.nome,
            "foto_url": self.foto_url,
            "foto": foto,
            "observacao": self.observacao,
            "quantidade": self.quantidade,
            "comprado": self.comprado,
            "criado_em": self.criado_em.isoformat() if self.criado_em else None,
            "links": links,
            "melhor_total": melhor["total"] if melhor else None,
            "economia": round(pior["total"] - melhor["total"], 2) if melhor and pior else 0,
        }


class Link(db.Model):
    __tablename__ = "links"
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id"), nullable=False)
    url = db.Column(db.Text, nullable=False)
    loja = db.Column(db.String(100))
    preco = db.Column(db.Numeric(12, 2))
    frete = db.Column(db.Numeric(12, 2))
    imagem = db.Column(db.Text)
    atualizado_em = db.Column(db.DateTime(timezone=True), default=agora)

    def to_dict(self):
        preco = float(self.preco) if self.preco is not None else None
        frete = float(self.frete) if self.frete is not None else 0.0
        return {
            "id": self.id,
            "url": self.url,
            "loja": self.loja,
            "preco": preco,
            "frete": frete,
            "total": round(preco + frete, 2) if preco is not None else None,
            "imagem": self.imagem,
            "atualizado_em": self.atualizado_em.isoformat() if self.atualizado_em else None,
            "melhor": False,
        }


def _num(valor):
    if valor in (None, ""):
        return None
    return scraper.parse_preco(valor) if isinstance(valor, str) else float(valor)


# ---------------------------------------------------------------- páginas
@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------- API
@app.get("/api/produtos")
def listar_produtos():
    produtos = db.session.scalars(db.select(Produto).order_by(Produto.criado_em.desc()))
    return jsonify([p.to_dict() for p in produtos])


@app.post("/api/produtos")
def criar_produto():
    dados = request.get_json(force=True)
    nome = (dados.get("nome") or "").strip()
    if not nome:
        return jsonify(erro="Informe o nome do produto."), 400
    produto = Produto(
        nome=nome,
        foto_url=(dados.get("foto_url") or "").strip() or None,
        observacao=(dados.get("observacao") or "").strip() or None,
        quantidade=int(dados.get("quantidade") or 1),
    )
    db.session.add(produto)
    db.session.commit()
    return jsonify(produto.to_dict()), 201


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
    if not produto.nome:
        abort(400)
    db.session.commit()
    return jsonify(produto.to_dict())


@app.delete("/api/produtos/<int:pid>")
def excluir_produto(pid):
    db.session.delete(db.get_or_404(Produto, pid))
    db.session.commit()
    return "", 204


@app.post("/api/produtos/<int:pid>/links")
def criar_link(pid):
    produto = db.get_or_404(Produto, pid)
    dados = request.get_json(force=True)
    url = (dados.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify(erro="Informe um link começando com http:// ou https://"), 400

    preco = _num(dados.get("preco"))
    imagem = dados.get("imagem") or None
    loja = (dados.get("loja") or "").strip() or None
    aviso = None
    if preco is None or not imagem or not loja:
        info = scraper.extrair(url)
        preco = preco if preco is not None else info["preco"]
        imagem = imagem or info["imagem"]
        loja = loja or info["loja"]
        aviso = info["erro"] if preco is None else None

    link = Link(
        produto=produto, url=url, loja=loja, preco=preco,
        frete=_num(dados.get("frete")), imagem=imagem,
    )
    db.session.add(link)
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
    return jsonify(scraper.extrair(url))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
