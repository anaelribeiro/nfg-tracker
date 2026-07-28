NFG Tracker — Nota Fiscal Gaúcha
==================================

INSTALAÇÃO
----------
1. Instale Python 3.10+
2. Instale as dependências:
     pip install -r requirements.txt

3. Instale o ChromeDriver compatível com seu Chrome:
     https://googlechromelabs.github.io/chrome-for-testing/

CONFIGURAÇÃO
------------
python nfg_tracker.py --setup
(vai pedir CPF e senha do portal nfg.rs.gov.br)

USO
---
# Baixar todas as notas do ano atual + gerar CSV + dashboard
python nfg_tracker.py

# Baixar notas de um ano específico
python nfg_tracker.py --year=2025

# Só gerar/atualizar o dashboard (sem re-baixar)
python nfg_tracker.py --dashboard

SAÍDAS
------
data/itens.csv      — todos os itens de todas as notas
data/dashboard.html — abre no navegador com gráficos
data/*.xml          — cache dos XMLs (evita re-consultar SEFAZ)
