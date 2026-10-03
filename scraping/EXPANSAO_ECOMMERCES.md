# Expansão para outros e-commerces — avaliação (não implementado)

Este documento avalia a viabilidade de adicionar novas lojas ao Hunter,
seguindo a mesma arquitetura usada em `buscar_produtoskabum.py` (listagem via
navegador real quando necessário + detalhe via HTTP simples quando o site
expõe dados estruturados). Nenhuma dessas lojas foi implementada — é só o
levantamento pedido, para decidir prioridade depois.

Metodologia: requisição HTTP simples (sem navegador, sem login, um único
acesso por site) à página de categoria/busca de "placa de vídeo", em
29/08/2026, verificando: renderização client-side vs. servidor, presença de
JSON estruturado (`__NEXT_DATA__`, JSON-LD), e sinais de bloqueio.

## Já implementado

### Mercado Livre — `buscar_produtosmercadolivre.py`
Já existe e já é usado pela API (`/buscar-produtos` combina Kabum + Mercado
Livre). Qualidade atual é baixa comparada ao novo scraper da Kabum:
- Seletores CSS com múltiplos fallbacks manuais (`ui-search-layout__item`,
  `ui-search-result__wrapper`, ...) — sintoma de que a Mercado Livre muda o
  HTML com frequência e o scraper já quebrou antes.
- Só busca 1 termo fixo (`"teclado"`), não por categoria.
- Usa a senha antiga do Postgres hardcoded (`postgresql://postgres:0608@...`)
  — **está quebrado agora** que a senha local foi trocada; ou é corrigido ou
  falha silenciosamente se alguém tentar rodá-lo.
- Sem galeria de imagens (só uma `imagem_url`), sem deduplicação em lote.

Se a prioridade for melhorar cobertura, migrar o Mercado Livre para a mesma
arquitetura do Kabum (Scrapling + `db_produtos.py` + índice único por link)
é o próximo passo natural — mesmo padrão, sem inventar nada novo.

## Candidatas avaliadas

| Loja | Renderização | Dados estruturados | Sinais de bloqueio | Viabilidade |
|---|---|---|---|---|
| **Terabyte** | Servidor (HTML puro já traz os links de produto: 153 links `/produto/...` numa única página) | JSON-LD presente (4 blocos) | Nenhum na requisição simples; o site exibe selo Cloudflare e usa reCAPTCHA (provavelmente só em login/checkout) | **Alta** — o caso mais simples dos quatro. Não precisa de navegador para a listagem; dá para usar `requests` + BeautifulSoup como o scraper do Mercado Livre, só que num site mais estável. |
| **Pichau** | Client-side (SPA; não achei link de produto no HTML bruto, nem `__NEXT_DATA__`) | 3 blocos JSON-LD (metadados, não a listagem completa) | Nenhum sinal de bloqueio na requisição simples | **Média** — provavelmente precisa de navegador real (Scrapling) para a listagem, igual à Kabum. Não investiguei o framework a fundo; antes de implementar, repetir a mesma investigação de rede (DevTools/Playwright) feita na Kabum para achar o padrão de dados do produto. |
| **Amazon.com.br** | Servidor (60 cards de produto no HTML puro de uma busca simples, sem login) | Não verificado a fundo | Nenhum bloqueio nesta única requisição | **Tecnicamente fácil, mas arriscado.** Amazon é conhecida por bloquear IPs que fazem scraping recorrente (rate limiting agressivo, títulos "Robot Check"/CAPTCHA aparecem after a few requests) e os Termos de Uso proíbem explicitamente coleta automatizada de dados. Existe API oficial (Amazon Product Advertising API) que exige conta de afiliado — caminho mais seguro se a Amazon entrar no escopo. |
| **Magazine Luiza** | N/A | N/A | **Bloqueado imediatamente** — HTTP 403 já na primeira requisição, sem navegador | **Baixa** sem investimento extra. Indica proteção anti-bot ativa (WAF) na camada de borda; provavelmente exigiria sessão de navegador real com fingerprint anti-detecção (o modo `stealthy` do Scrapling, baseado em Camoufox) e ainda assim não há garantia. |

## Recomendação de ordem, se for expandir

1. **Terabyte** — melhor custo-benefício: HTML já vem pronto no servidor,
   sem necessidade de navegador para a listagem, reduzindo custo/latência
   comparado à Kabum.
2. **Mercado Livre (retrabalho)** — já está no ar, só precisa do mesmo
   tratamento de robustez que a Kabum recebeu agora (categorias fixas,
   dedup por link, galeria de imagens).
3. **Pichau** — viável, mas exige a mesma etapa de engenharia reversa de
   rede que foi feita para a Kabum antes de escrever o scraper.
4. **Amazon** — tecnicamente simples, mas o risco de bloqueio/ToS pesa;
   só valeria a pena via API oficial de afiliados.
5. **Magazine Luiza** — não recomendado no momento; WAF bloqueia de cara.

Cada nova loja soma uma linha em `produtos_<loja>` seguindo o mesmo padrão
de schema (`link` único, `imagens_urls`, `categoria`, índice trigram) e
uma entrada a mais no `UNION ALL` de `/buscar-produtos` em `app.py`.
