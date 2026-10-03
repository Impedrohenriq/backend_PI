# Coleta de novas lojas

## Amostra de dados

`../database_sample.sql` contem uma amostra pequena de produtos e URLs de
imagens do banco local, sem usuarios, alertas, feedbacks ou credenciais.
Execute `database_setup.sql` primeiro e depois importe a amostra com psql:

```powershell
psql -U postgres -d hunter_db -f backend/database_setup.sql
psql -U postgres -d hunter_db -f backend/database_sample.sql
```

Os comandos acima sao executados na raiz do projeto. As imagens continuam
hospedadas nas lojas; a amostra armazena os links, sem baixar arquivos.
Para regenerar a amostra, execute `python exportar_amostra.py` nesta pasta.
O exportador tenta o banco local e usa o dump local como alternativa.

## Executar coleta

Adaptadores iniciais: Amazon Brasil, Magazine Luiza, Pichau e Terabyte.
Usam a dependencia Scrapling ja presente no projeto; nao copie o repositorio
do framework para esta pasta.

Com o ambiente virtual ativo e PostgreSQL configurado no `backend/.env`:

```powershell
cd backend/scraping
scrapling install
python buscar_produtoslojas.py --lojas amazon magalu pichau terabyte --termos "teclado" "mouse" --paginas 1 --limite 10
```

Sem `--termos`, coleta as categorias de hardware existentes, teclado, mouse
e pendrive. `--limite` vale por termo e loja. A categoria e inferida pelo
titulo do produto, usando a mesma classificacao dos filtros; titulos nao
reconhecidos ficam sem categoria.

O coletor prepara `produtos_lojas` antes da coleta. Para atualizar um banco
existente antes de iniciar a API, execute tambem `backend/database_setup.sql`.
A API `/buscar-produtos` inclui esta tabela junto de Kabum e Mercado Livre.
As variaveis `SCRAPER_*` e `PG_*` existentes continuam sendo usadas.

Cada detalhe valido e salvo imediatamente; links repetidos atualizam o registro.
Precos ausentes, nao positivos ou sem moeda BRL nas ofertas sao descartados.
As fotos vem do JSON-LD Product da pagina; Amazon tambem usa a foto principal
da galeria. Ha fallback por microdados e seletores de detalhe das lojas.
Open Graph e usado quando nao ha fotos estruturadas.
URLs de rastreamento sao removidas antes da deduplicacao.

Os adaptadores sao iniciais e ainda nao foram validados em coleta ao vivo.
Mudancas de HTML, ausencia de JSON-LD e bloqueios podem impedir a extracao.
Bloqueios interrompem a busca atual e salvam HTML de diagnostico, conforme
`SCRAPER_SAVE_FAILURE_HTML`. Nao ha agendamento automatico.

Para adicionar outra loja, cadastre uma entrada em `LOJAS` com dominio,
URL de busca paginada e padrao de URL de produto. Se ela nao fornecer JSON-LD
Product, adicione extracao especifica em `extrair_produto`, limitada ao
titulo, preco e galeria do produto principal.
