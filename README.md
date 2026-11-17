# 🛒 Minhas Compras

Lista de compras com comparação de preços entre lojas.

- Cole o **link do produto** e pronto: o site busca sozinho **nome, foto, loja e preço**
  (o nome é opcional; se digitar, ele tem prioridade).
- Adicione **outros links** do mesmo produto em outras lojas para comparar.
- Informe o **frete** de cada loja: o site soma preço + frete e **destaca o menor valor total**, mostrando quanto você economiza.
- **Kits e tamanhos diferentes:** compara pelo **preço por unidade** (peça, kg, litro ou metro).
  Ex.: kit 10 peças por R$ 34,90 = **R$ 3,49/peça** × kit 5 peças por R$ 24,90 = R$ 4,98/peça.
  A quantidade é detectada no título do anúncio ("Kit 10 peças", "c/ 12", "12 x 350 ml",
  "1,6 kg"…) e pode ser corrigida na tabela. O frete entra na conta.
- **Juntar com…** une produtos do mesmo tipo cadastrados separados, para comparar as ofertas juntas.
- Marque **"Já comprei"** para tirar o produto da lista "A comprar".
- O topo mostra quanto falta gastar (pelo menor preço) e o que já foi comprado.
- **Modo escuro** por padrão, com botão para alternar para o claro (a escolha fica salva).

## Como rodar

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Abra http://localhost:5000

### Usar PostgreSQL (opcional)

Por padrão os dados ficam em `compras.db` (SQLite). Para PostgreSQL:

```bash
pip install "psycopg[binary]"
export DATABASE_URL="postgresql+psycopg://usuario:senha@localhost:5432/compras"
python app.py
```

As tabelas `produtos` e `links` são criadas automaticamente, então dá para consultar
tudo direto em SQL ou conectar no Power BI.

## Sobre a busca automática de preço

O preço é lido dos metadados da página (JSON-LD `schema.org/Product`, Open Graph,
`itemprop="price"`), que a maioria das lojas publica. Algumas lojas bloqueiam
leitura automática ou mostram o preço só depois de carregar a página. Nesses casos
o site avisa e você digita o preço na tabela. O botão **↻ preço** busca o valor de novo.

O **frete** depende do seu CEP e quase nenhuma loja o publica na página, por isso é
informado manualmente (vazio = frete grátis).
