# Radar de Mercado — Freguesia/Jacarepaguá

Projeto pessoal para acompanhar preços online, comparar com o histórico, montar listas independentes para Dudu e Mãe e receber alertas no Telegram. As lojas presenciais ficam cadastradas por prioridade; só exibimos preço quando há uma fonte digital verificável.

## Começo rápido

1. Edite `config/products.json` e adicione os produtos que quer acompanhar.
2. No GitHub, envie todos os arquivos desta pasta mantendo os nomes e subpastas.
3. No repositório, abra **Settings → Secrets and variables → Actions** e crie `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
4. Abra **Actions → Radar de Mercado → Run workflow** para iniciar a primeira execução.
5. Depois disso, o GitHub Actions executa a cada seis horas e guarda o histórico no próprio repositório.

## Produtos monitorados

O radar global lê exclusivamente `config/products.json`. As listas de compras em `config/shopping_lists.json` não acrescentam produtos ao radar. Um produto precisa de `name` e pode ter `keywords`, `target_price` e `alert_below_average_percent`.

Exemplo:

```json
[
  {
    "name": "Café Pilão 500g",
    "keywords": ["cafe", "pilao", "500g"],
    "target_price": 22.00,
    "alert_below_average_percent": 15
  }
]
```

Deixe `[]` até decidir quais produtos monitorar.

## Lojas e deslocamento

`config/stores.json` contém as lojas prioritárias (Supermarket Freguesia, Mundial Freguesia, Armazém Urbano, Hortifruti e Rede Economia) e outras redes candidatas da região. O coletor também consulta o OpenStreetMap para descobrir supermercados próximos e salva o resultado em cache.

O bot não estima nem desconta Uber, combustível ou qualquer custo de deslocamento. Lojas sem preço online verificável continuam no cadastro, mas não recebem preço inventado. Quando uma oferta não pode ser ligada a uma filial específica, ela é identificada como preço da rede e deve ser confirmada na loja.

## Compras online

As fontes online iniciais são Mercado Livre (API pública de busca) e Amazon Brasil (página pública de busca, sujeita a bloqueios do site). Frete padrão considerado no comparador: **R$ 0,00**, conforme solicitado. Confirme frete, vendedor, estoque e preço final no anúncio antes de comprar.

## Histórico, alertas e painel

O histórico de preços e a memória de alertas ficam em `data/`; o workflow os versiona para persistirem entre execuções. O painel fica em `data/dashboard.html`. A primeira execução não classifica oferta como histórica antes de haver medições suficientes. Alertas Telegram exigem os dois Secrets citados acima; sem eles, a coleta e o painel continuam funcionando.

## Rodar no computador

Requer Python 3.11 ou mais recente. O projeto usa apenas bibliotecas que já vêm com Python:

```text
python src/radar.py
python -m unittest discover -s src -v
```

## Configurações

- `config/products.json`: radar global.
- `config/stores.json`: lojas próximas e prioridade de rota.
- `config/settings.json`: raio geográfico, fontes e frete online padrão.
- `config/shopping_lists.json`: listas separadas de Dudu e Mãe.
- `.env.example`: nomes dos Secrets necessários; nunca preencha o token neste arquivo.

Preços e estoque mudam. O histórico e o alerta são referências para decidir; sempre confirme as condições na loja ou no anúncio.
