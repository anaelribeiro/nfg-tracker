#!/usr/bin/env python3
"""
NFG Tracker — Nota Fiscal Gaúcha
Faz login no portal NFG via GOV.BR, baixa CSV de notas,
busca XMLs no SEFAZ RS e gera CSV de itens + dashboard HTML.
"""

import os
import csv
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ─── Caminhos ────────────────────────────────────────────────────────────────

BASE_DIR     = Path(__file__).parent
DATA_DIR     = BASE_DIR / "data"
SESSION_DIR  = BASE_DIR / "session"   # perfil Chrome persistente
DATA_DIR.mkdir(exist_ok=True)
SESSION_DIR.mkdir(exist_ok=True)

CHROME_BIN   = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
NFG_NOTAS    = "https://nfg.sefaz.rs.gov.br/cadastro/ConsultaDocumentos.aspx"
NFG_GOVBR    = "https://nfg.sefaz.rs.gov.br/govbr-redirect.aspx"

# ─── Chrome helpers ───────────────────────────────────────────────────────────

def _opts(headless: bool = True) -> Options:
    opts = Options()
    opts.add_argument(f"--user-data-dir={SESSION_DIR}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--window-size=1280,900")
    opts.binary_location = CHROME_BIN
    if headless:
        opts.add_argument("--headless=new")
    return opts

def _driver(headless: bool = True):
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=_opts(headless)
    )

def _logado(driver) -> bool:
    return "nfg.sefaz.rs.gov.br" in driver.current_url and \
           "govbr" not in driver.current_url and \
           "sso.acesso" not in driver.current_url

# ─── Login ────────────────────────────────────────────────────────────────────

def fazer_login():
    """
    Abre Chrome visível para o usuário fazer login via GOV.BR (com CAPTCHA).
    Aguarda até detectar o login bem-sucedido e fecha o browser.
    A sessão fica salva em SESSION_DIR para usos futuros.
    """
    print("=" * 50)
    print("NFG Tracker — Login")
    print("=" * 50)
    print("Abrindo Chrome para login no GOV.BR...")
    print("Complete o login (CPF + senha + CAPTCHA) no browser.")
    print("O script continua automaticamente após o login.")
    print("=" * 50)

    driver = _driver(headless=False)
    wait   = WebDriverWait(driver, 300)  # 5 min para o usuário logar

    try:
        driver.get(NFG_GOVBR)

        # aguarda até estar no portal NFG logado
        wait.until(lambda d: "nfg.sefaz.rs.gov.br" in d.current_url
                              and "govbr" not in d.current_url
                              and "sso.acesso" not in d.current_url)

        print(f"[✓] Login detectado! URL: {driver.current_url}")
        print("[✓] Sessão salva. Pode fechar o browser ou aguardar...")
        time.sleep(2)
    finally:
        driver.quit()

# ─── Download CSV do portal NFG ───────────────────────────────────────────────

def baixar_csv_notas(ano: str = None) -> Path:
    """
    Acessa a página de consulta de documentos, filtra pelo ano,
    clica em CSV e salva o arquivo. Retorna o path do CSV.
    """
    if ano is None:
        ano = str(datetime.now().year)

    csv_path = DATA_DIR / f"notas_{ano}.csv"

    # configura download para DATA_DIR
    prefs = {
        "download.default_directory": str(DATA_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    opts = _opts(headless=True)
    opts.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts
    )
    wait = WebDriverWait(driver, 20)

    try:
        driver.get(NFG_NOTAS)
        time.sleep(3)

        # verifica se está logado
        if not _logado(driver):
            driver.quit()
            print("[!] Sessão expirada. Rode: python nfg_tracker.py --login")
            return None

        print(f"[✓] Logado no portal NFG")
        print(f"[*] Consultando notas de {ano}...")

        # preenche data inicial e final
        try:
            di = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_dtpDataInicial_dateInput")
            df = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_dtpDataFinal_dateInput")
            di.clear(); di.send_keys(f"01/01/{ano}")
            df.clear(); df.send_keys(f"31/12/{ano}")
        except Exception:
            # tenta campos genéricos de data
            datas = driver.find_elements(By.XPATH, "//input[@type='text' and contains(@id,'Data')]")
            if len(datas) >= 2:
                datas[0].clear(); datas[0].send_keys(f"01/01/{ano}")
                datas[1].clear(); datas[1].send_keys(f"31/12/{ano}")

        # clica Consultar
        try:
            btn_consultar = driver.find_element(By.XPATH,
                "//input[@value='Consultar' or @id[contains(.,'Consultar')]] | //button[contains(text(),'Consultar')]")
            btn_consultar.click()
            time.sleep(3)
        except Exception as e:
            print(f"  [!] Botão consultar: {e}")

        driver.save_screenshot("/tmp/nfg_notas.png")
        print("[*] Screenshot salvo em /tmp/nfg_notas.png")

        # clica CSV
        try:
            btn_csv = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//input[@value='CSV' or @title='CSV'] | //button[text()='CSV'] | //a[text()='CSV']")))
            btn_csv.click()
            print("[*] Clicou em CSV, aguardando download...")
            time.sleep(5)
        except Exception as e:
            print(f"  [!] Botão CSV não encontrado: {e}")
            # tenta pelo texto da página
            driver.save_screenshot("/tmp/nfg_notas_debug.png")
            return None

        # localiza o arquivo baixado (mais recente em DATA_DIR)
        csvs = sorted(DATA_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if csvs:
            baixado = csvs[0]
            baixado.rename(csv_path)
            print(f"[✓] CSV salvo em {csv_path}")
            return csv_path
        else:
            print("[!] Arquivo CSV não encontrado após download")
            return None

    finally:
        driver.quit()

# ─── Parsing do CSV do NFG ────────────────────────────────────────────────────

def parse_csv_nfg(csv_path: Path) -> list[dict]:
    """Lê o CSV baixado do portal NFG e retorna lista de notas com chave de acesso."""
    notas = []
    encodings = ["utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(csv_path, newline="", encoding=enc) as f:
                # tenta detectar delimitador
                sample = f.read(2048)
                f.seek(0)
                delim = ";" if sample.count(";") > sample.count(",") else ","
                reader = csv.DictReader(f, delimiter=delim)
                for row in reader:
                    # normaliza nomes de colunas
                    row_lower = {k.strip().lower(): v.strip() for k, v in row.items() if k}
                    chave = (row_lower.get("chave de acesso") or
                             row_lower.get("chave") or
                             row_lower.get("chaveacesso") or "").replace(" ", "")
                    notas.append({
                        "chave":   chave,
                        "emissao": row_lower.get("emissão", row_lower.get("emissao", "")),
                        "loja":    row_lower.get("razão social", row_lower.get("razao social",
                                   row_lower.get("estabelecimento", ""))),
                        "valor":   row_lower.get("valor", ""),
                    })
            print(f"[✓] {len(notas)} notas lidas do CSV (encoding: {enc})")
            return notas
        except UnicodeDecodeError:
            continue
    print("[!] Não foi possível ler o CSV")
    return []

# ─── SEFAZ — consulta XML por chave ──────────────────────────────────────────

NFE_NS = "http://www.portalfiscal.inf.br/nfe"
SEFAZ_URL = "https://www.sefaz.rs.gov.br/WS/NfeConsulta/NfeConsulta2.asmx"
SOAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:nfe="http://www.portalfiscal.inf.br/nfe/wsdl/NfeConsulta2">
  <soapenv:Header>
    <nfeCabecMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NfeConsulta2">
      <cUF>43</cUF><versaoDados>3.10</versaoDados>
    </nfeCabecMsg>
  </soapenv:Header>
  <soapenv:Body>
    <nfe:nfeConsultaNF>
      <nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NfeConsulta2">
        <consSitNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="3.10">
          <tpAmb>1</tpAmb><xServ>CONSULTAR</xServ>
          <chNFe>{chave}</chNFe>
        </consSitNFe>
      </nfeDadosMsg>
    </nfe:nfeConsultaNF>
  </soapenv:Body>
</soapenv:Envelope>"""

def consultar_xml_sefaz(chave: str) -> ET.Element | None:
    cache = DATA_DIR / f"{chave}.xml"
    if cache.exists():
        return ET.parse(cache).getroot()
    headers = {
        "Content-Type": "text/xml; charset=UTF-8",
        "SOAPAction": "http://www.portalfiscal.inf.br/nfe/wsdl/NfeConsulta2/nfeConsultaNF",
    }
    try:
        resp = requests.post(SEFAZ_URL, data=SOAP_TEMPLATE.format(chave=chave).encode("utf-8"),
                             headers=headers, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        cache.write_text(resp.text, encoding="utf-8")
        return root
    except Exception as e:
        print(f"  [!] SEFAZ ({chave[:8]}...): {e}")
        return None

def extrair_itens(root: ET.Element, chave: str, emissao: str, loja: str) -> list[dict]:
    itens = []
    for ns in [f"{{{NFE_NS}}}", ""]:
        dets = root.findall(f".//{ns}det")
        if not dets:
            continue
        for det in dets:
            prod = det.find(f"{ns}prod")
            if prod is None:
                continue
            def t(tag):
                el = prod.find(f"{ns}{tag}")
                return el.text.strip() if el is not None and el.text else ""
            itens.append({
                "chave": chave, "emissao": emissao, "loja": loja,
                "codigo": t("cProd"), "descricao": t("xProd"), "ncm": t("NCM"),
                "unidade": t("uCom"), "quantidade": t("qCom"),
                "valor_unit": t("vUnCom"), "valor_total": t("vProd"),
            })
        break
    return itens

# ─── CSV de itens ─────────────────────────────────────────────────────────────

ITENS_CSV = DATA_DIR / "itens.csv"
FIELDS    = ["chave","emissao","loja","codigo","descricao","ncm",
             "unidade","quantidade","valor_unit","valor_total"]

def salvar_itens_csv(itens: list[dict]):
    existe = ITENS_CSV.exists()
    # evita duplicatas por chave+codigo
    existentes = set()
    if existe:
        with open(ITENS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existentes.add((row["chave"], row["codigo"]))
    novos = [it for it in itens if (it["chave"], it["codigo"]) not in existentes]
    with open(ITENS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not existe:
            w.writeheader()
        w.writerows(novos)
    print(f"[✓] {len(novos)} itens novos salvos (total acumulado no CSV)")

def ler_itens_csv() -> list[dict]:
    if not ITENS_CSV.exists():
        return []
    with open(ITENS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

# ─── Dashboard HTML ───────────────────────────────────────────────────────────

def gerar_dashboard(itens: list[dict]):
    from collections import defaultdict

    produtos = defaultdict(lambda: {"qtd": 0.0, "total": 0.0, "compras": 0})
    por_loja = defaultdict(float)
    por_mes  = defaultdict(float)

    for it in itens:
        desc = (it["descricao"] or "Desconhecido").title()
        try:
            qtd = float(it["quantidade"].replace(",", ".") or 0)
            tot = float(it["valor_total"].replace(",", ".") or 0)
        except ValueError:
            qtd, tot = 0, 0
        produtos[desc]["qtd"]     += qtd
        produtos[desc]["total"]   += tot
        produtos[desc]["compras"] += 1
        por_loja[it["loja"] or "Desconhecida"] += tot
        data = it["emissao"][:7] if len(it["emissao"]) >= 7 else "?"
        por_mes[data] += tot

    top_prod  = sorted(produtos.items(), key=lambda x: x[1]["total"], reverse=True)[:20]
    top_lojas = sorted(por_loja.items(), key=lambda x: x[1], reverse=True)[:10]
    meses     = sorted(por_mes.items())

    jl = lambda lst: json.dumps([x[0] for x in lst])
    jv = lambda lst: json.dumps([round(x[1] if isinstance(x[1], float) else x[1]["total"], 2) for x in lst])

    total_gasto = sum(por_loja.values())
    total_notas = len({it["chave"] for it in itens})

    linhas_prod = "".join(
        f'<tr><td>{i+1}</td><td>{d}</td><td>{v["compras"]}</td>'
        f'<td>{v["qtd"]:.2f}</td><td>R$ {v["total"]:,.2f}</td></tr>'
        for i, (d, v) in enumerate(top_prod)
    )

    js = (
        "const C=(id,cfg)=>new Chart(document.getElementById(id),cfg);\n"
        f"const LAB_MES={jl(meses)}, VAL_MES={jv(meses)};\n"
        f"const LAB_LOJAS={jl(top_lojas)}, VAL_LOJAS={jv(top_lojas)};\n"
        "C('cMes',{type:'bar',data:{labels:LAB_MES,datasets:[{label:'R$',data:VAL_MES,"
        "backgroundColor:'#38bdf8',borderRadius:4}]},options:{plugins:{legend:{display:false}},"
        "scales:{x:{ticks:{color:'#94a3b8'},grid:{color:'#1a1e2e'}},"
        "y:{ticks:{color:'#94a3b8'},grid:{color:'#1a1e2e'}}}}});\n"
        "C('cLojas',{type:'doughnut',data:{labels:LAB_LOJAS,datasets:[{data:VAL_LOJAS,"
        "backgroundColor:['#38bdf8','#34d399','#a78bfa','#f472b6','#fb923c','#facc15',"
        "'#4ade80','#60a5fa','#e879f9','#94a3b8']}]},options:{plugins:{legend:"
        "{position:'right',labels:{color:'#e2e8f0',font:{size:11}}}}}}})"
    )

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>NFG Tracker</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#0f1117;color:#e2e8f0;padding:24px}}
h1{{font-size:1.5rem;margin-bottom:4px;color:#fff}}
.sub{{color:#94a3b8;font-size:.875rem;margin-bottom:24px}}
.cards{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
.card{{background:#1e2130;border-radius:10px;padding:20px 24px;flex:1;min-width:160px}}
.card .label{{font-size:.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}}
.card .value{{font-size:1.75rem;font-weight:700;color:#38bdf8;margin-top:4px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px}}
.box{{background:#1e2130;border-radius:10px;padding:20px}}
.box h2{{font-size:.85rem;color:#94a3b8;margin-bottom:16px;text-transform:uppercase;letter-spacing:.05em}}
canvas{{max-height:280px}}
table{{width:100%;border-collapse:collapse;font-size:.8rem}}
th{{text-align:left;padding:8px 12px;color:#94a3b8;border-bottom:1px solid #2d3148}}
td{{padding:8px 12px;border-bottom:1px solid #1a1e2e}}
tr:hover td{{background:#252840}}
@media(max-width:700px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<h1>NFG Tracker</h1>
<div class="sub">Nota Fiscal Gaúcha · detalhamento de compras · gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")}</div>
<div class="cards">
  <div class="card"><div class="label">Total gasto</div><div class="value">R$ {total_gasto:,.2f}</div></div>
  <div class="card"><div class="label">Notas fiscais</div><div class="value">{total_notas}</div></div>
  <div class="card"><div class="label">Itens registrados</div><div class="value">{len(itens)}</div></div>
</div>
<div class="grid">
  <div class="box"><h2>Gastos por mês (R$)</h2><canvas id="cMes"></canvas></div>
  <div class="box"><h2>Top lojas</h2><canvas id="cLojas"></canvas></div>
</div>
<div class="box" style="margin-bottom:24px">
  <h2>Top 20 produtos mais comprados</h2>
  <table>
    <thead><tr><th>#</th><th>Produto</th><th>Compras</th><th>Qtd total</th><th>Total R$</th></tr></thead>
    <tbody>{linhas_prod}</tbody>
  </table>
</div>
<script>{js}</script>
</body></html>"""

    out = DATA_DIR / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    print(f"[✓] Dashboard: {out}")
    return out

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import sys
    args = sys.argv[1:]
    ano = next((a.split("=")[1] for a in args if a.startswith("--year=")),
               str(datetime.now().year))

    # ── modo login ──
    if "--login" in args:
        fazer_login()
        return

    # ── modo só dashboard ──
    if "--dashboard" in args:
        itens = ler_itens_csv()
        if not itens:
            print("[!] Sem itens. Rode o script normalmente primeiro.")
            return
        path = gerar_dashboard(itens)
        os.system(f"open '{path}'")
        return

    print("=" * 50)
    print(f"NFG Tracker — Baixando notas de {ano}")
    print("=" * 50)

    # ── passo 1: verifica sessão / baixa CSV ──
    csv_notas = DATA_DIR / f"notas_{ano}.csv"
    if not csv_notas.exists():
        print(f"[1/3] Baixando CSV de notas do portal NFG...")
        csv_notas = baixar_csv_notas(ano)
        if csv_notas is None:
            print("\n[!] Sessão não encontrada ou expirada.")
            print("[!] Execute primeiro: python nfg_tracker.py --login")
            return
    else:
        print(f"[1/3] CSV de notas já existe: {csv_notas}")

    notas = parse_csv_nfg(csv_notas)
    notas_validas = [n for n in notas if len(n.get("chave","")) == 44]
    print(f"      {len(notas_validas)} notas com chave de acesso válida")

    if not notas_validas:
        print("[!] Nenhuma nota válida encontrada no CSV.")
        return

    # ── passo 2: busca XMLs no SEFAZ ──
    print(f"\n[2/3] Consultando {len(notas_validas)} notas no SEFAZ RS...")
    todos_itens = []
    for i, nota in enumerate(notas_validas, 1):
        chave = nota["chave"]
        print(f"  [{i:3d}/{len(notas_validas)}] {chave[:8]}... — {nota.get('loja','?')[:35]}")
        root = consultar_xml_sefaz(chave)
        if root is None:
            continue
        itens = extrair_itens(root, chave, nota.get("emissao",""), nota.get("loja",""))
        todos_itens.extend(itens)
        time.sleep(0.3)

    # ── passo 3: salva e abre dashboard ──
    print(f"\n[3/3] {len(todos_itens)} itens extraídos")
    if todos_itens:
        salvar_itens_csv(todos_itens)
        path = gerar_dashboard(ler_itens_csv())
        os.system(f"open '{path}'")
    else:
        print("[!] Nenhum item extraído. Os XMLs podem não ter detalhamento de itens.")

if __name__ == "__main__":
    main()
