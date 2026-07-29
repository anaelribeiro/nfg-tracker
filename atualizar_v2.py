#!/usr/bin/env python3
"""
NFG Tracker v2 — Atualização incremental
- Sem arquivos locais de dados
- Extrai todos os campos da nota (cabeçalho + itens + NCM)
- Sobe direto no Google Sheets
- Filiais populadas automaticamente via BrasilAPI
"""

import csv, json, time, subprocess, sys, warnings, re
import xml.etree.ElementTree as ET
import requests
from pathlib import Path
from datetime import datetime

warnings.filterwarnings("ignore")

# ── Configuração ──────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
CHROME_BIN      = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SHEET_ID        = "1Z69HQfCHm_wW3aaP9mMyMa4zDNhqPbJd5NaIX9i3b-c"
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbwpfWeHAm8_wBt-r6LVkCCXVTP3AyygtOTV1Dif7iIiJU712yGwV2_hybAwmJQzcgZ3-Q/exec"
FILIAIS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSa-dNrsETRbxEi0I6GIoFc6J6Hd2Tpm7w1Yo4kORWwyIauS4kcWDX20wxpkA5mfRTQHvW9fg-WFN72/pub?gid=1900593584&single=true&output=csv"

# Colunas da aba itens (v2)
CAMPOS_ITENS = [
    "chave", "numero", "serie", "emissao", "hora", "tipo_nota",
    "cnpj_emitente", "loja", "municipio",
    "valor_total_nota", "valor_desconto", "forma_pagamento",
    "codigo", "descricao", "ncm", "quantidade", "unidade",
    "valor_unit", "valor_total_item"
]

# Colunas da aba filiais
CAMPOS_FILIAIS = ["cnpj", "nome", "fantasia", "logradouro", "numero", "bairro", "municipio", "uf"]

# ── Login ─────────────────────────────────────────────────────────

def fazer_login():
    print("\n[*] Abrindo Chrome para login no NFG (GOV.BR)...")
    print("    Faça login e pressione ENTER aqui quando terminar.\n")
    subprocess.Popen([CHROME_BIN, "https://nfg.sefaz.rs.gov.br/govbr-redirect.aspx"])
    input("    [ENTER após login] ")
    print("[✓] Continuando...")

# ── Google Sheets ─────────────────────────────────────────────────

def sheets_get_chaves():
    """Retorna set de chaves já na aba itens."""
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&sheet=itens"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return set()
        text = r.text.replace('\r\n', '\n').replace('\r', '\n')
        lines = text.strip().split('\n')
        if not lines: return set()
        # verifica se tem cabeçalho
        first = lines[0].replace('"','').split(',')[0].strip()
        start = 1 if first == 'chave' else 0
        chaves = set()
        for line in lines[start:]:
            if line.strip():
                chave = line.split(',')[0].replace('"','').strip()
                if len(chave) == 44:
                    chaves.add(chave)
        return chaves
    except Exception as e:
        print(f"[!] Erro ao ler Sheets: {e}")
        return set()

def sheets_get_cnpjs_filiais():
    """Retorna set de CNPJs já na aba filiais."""
    url = FILIAIS_CSV_URL
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return set()
        text = r.text.replace('\r\n', '\n').replace('\r', '\n')
        lines = text.strip().split('\n')
        cnpjs = set()
        for line in lines[1:]:
            if line.strip():
                cnpj = line.split(',')[0].replace('"','').strip()
                if cnpj: cnpjs.add(cnpj)
        return cnpjs
    except:
        return set()

def sheets_post(aba, rows, header=None):
    """Sobe linhas para uma aba. Se aba vazia, manda cabeçalho primeiro."""
    try:
        if header:
            requests.post(APPS_SCRIPT_URL,
                json={"action": "header_aba", "aba": aba, "row": header},
                timeout=30)
        BATCH = 50
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i+BATCH]
            requests.post(APPS_SCRIPT_URL,
                json={"aba": aba, "rows": batch},
                timeout=60)
            print(f"  {min(i+BATCH, len(rows))}/{len(rows)}", flush=True)
            time.sleep(0.3)
    except Exception as e:
        print(f"[!] Erro ao subir para '{aba}': {e}")

# ── NFG — busca notas ─────────────────────────────────────────────

def buscar_notas_nfg():
    import browser_cookie3
    jar = browser_cookie3.chrome(domain_name="sefaz.rs.gov.br")
    session = requests.Session()
    for c in jar:
        session.cookies.set(c.name, c.value, domain=c.domain, path=c.path)

    hdrs = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://nfg.sefaz.rs.gov.br/cadastro/ConsultaDocumentos.aspx",
        "Origin": "https://nfg.sefaz.rs.gov.br",
    }
    ano = datetime.now().year
    resp = session.post(
        "https://nfg.sefaz.rs.gov.br/Cadastro/ConsultaDocumentos_Do.aspx",
        data=f"pDtInicial=0101{ano}&pDtFinal=3112{ano}&pTipoData=1&pCodMunicipio=0",
        headers=hdrs, verify=False
    )
    root = ET.fromstring(resp.content)
    if root.findtext("Sucesso") != "True":
        return []

    from bs4 import BeautifulSoup
    html = (root.findtext("DadosRetorno") or "").encode("latin-1").decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    tabela = soup.find("table")
    if not tabela: return []

    notas = []
    for row in tabela.find_all("tr")[1:]:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 7: continue
        chave = cols[6].replace(" ","").replace("\n","")
        if len(chave) != 44: continue
        notas.append({
            "chave": chave,
            "emissao": cols[3],
            "loja": cols[2],
            "municipio": cols[1],
            "tipo": cols[5],
        })
    return notas

# ── SEFAZ — extrai nota completa ──────────────────────────────────

def extrair_nota_sefaz(chave):
    """
    Abre a página NFC-e no SEFAZ, clica Avançar e extrai:
    - cabeçalho: número, série, data/hora, CNPJ, valor total, desconto, pagamento
    - itens: código, descrição, NCM, qtd, unidade, valor unit, valor total
    Retorna dict com 'cabecalho' e 'itens'.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.alert import Alert
        from webdriver_manager.chrome import ChromeDriverManager

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--window-size=1280,900")
        opts.binary_location = CHROME_BIN

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=opts)

        try:
            url = f"https://www.sefaz.rs.gov.br/NFE/NFE-NFC.aspx?chaveNFe={chave}"
            driver.get(url)
            time.sleep(1.5)
            try: Alert(driver).accept(); time.sleep(0.5)
            except: pass
            driver.switch_to.frame("iframeConteudo")
            time.sleep(0.5)
            driver.find_element(By.XPATH, "//input[@value='Avançar']").click()
            time.sleep(2.5)

            body = driver.find_element(By.TAG_NAME, "body").text

            # cabeçalho
            cab = {}
            m = re.search(r'NFC-e\s+n[oº°]+[:\s]*(\d+)\s+S[eé]rie[:\s]*(\d+)', body)
            if m: cab["numero"] = m.group(1); cab["serie"] = m.group(2)
            else: cab["numero"] = ""; cab["serie"] = ""

            m = re.search(r'Data de Emiss[aã]o[:\s]+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})', body)
            if m: cab["emissao"] = m.group(1); cab["hora"] = m.group(2)
            else: cab["emissao"] = ""; cab["hora"] = ""

            m = re.search(r'CNPJ[:\s]+([\d./-]+)', body)
            cab["cnpj"] = m.group(1).replace(".","").replace("/","").replace("-","") if m else ""

            m = re.search(r'Valor total R\$\s*([\d,.]+)', body)
            cab["valor_total"] = m.group(1).replace(".",",") if m else ""

            m = re.search(r'Valor descontos R\$\s*([\d,.]+)', body)
            cab["desconto"] = m.group(1).replace(".",",") if m else "0,00"

            # forma de pagamento — padrões com e sem acentos
            pagamentos = re.findall(
                r'(Cart[aã]o de Cr[eé]dito|Cart[aã]o de D[eé]bito|Dinheiro|Pix|Outros|D[eé]bito|Cr[eé]dito)\s+([\d,.]+)',
                body)
            cab["pagamento"] = "; ".join(f"{p[0]}:{p[1]}" for p in pagamentos) if pagamentos else ""

            # tipo nota
            if "NFC-e" in body: cab["tipo"] = "NFC-e"
            elif "NF-e" in body: cab["tipo"] = "NF-e"
            else: cab["tipo"] = ""

            # itens via JS (primeira tabela)
            rows_data = driver.execute_script("""
                var tables=document.querySelectorAll('table');
                for(var i=0;i<tables.length;i++){
                    var rows=tables[i].querySelectorAll('tr');
                    var hasItem=false;
                    for(var j=0;j<rows.length;j++){
                        var tds=rows[j].querySelectorAll('td');
                        if(tds.length>=5&&/^\\d+$/.test(tds[0].innerText.trim())){hasItem=true;break;}
                    }
                    if(hasItem){
                        var result=[];
                        for(var j=0;j<rows.length;j++){
                            var tds=rows[j].querySelectorAll('td');
                            if(tds.length>=5&&/^\\d+$/.test(tds[0].innerText.trim())){
                                result.push(Array.from(tds).slice(0,6).map(function(td){return td.innerText.trim();}));
                            }
                        }
                        return result;
                    }
                }
                return [];
            """)

            # NCM via XML da página (se disponível)
            ncm_map = {}
            try:
                page_src = driver.page_source
                ncm_matches = re.findall(r'<NCM>(\d+)</NCM>.*?<cProd>(\d+)</cProd>', page_src)
                for ncm, cod in ncm_matches:
                    ncm_map[cod] = ncm
            except: pass

            itens = []
            for cols in rows_data:
                cod = cols[0] if cols else ""
                itens.append({
                    "codigo":      cod,
                    "descricao":   cols[1] if len(cols)>1 else "",
                    "quantidade":  cols[2] if len(cols)>2 else "",
                    "unidade":     cols[3] if len(cols)>3 else "",
                    "valor_unit":  cols[4] if len(cols)>4 else "",
                    "valor_total": cols[5] if len(cols)>5 else "",
                    "ncm":         ncm_map.get(cod, ""),
                })

            return {"cabecalho": cab, "itens": itens}

        finally:
            driver.quit()

    except Exception as e:
        print(f"    ERR SEFAZ: {e}")
        return None

# ── BrasilAPI — filial ────────────────────────────────────────────

def buscar_filial(cnpj):
    try:
        r = requests.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
                         timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            d = r.json()
            return {
                "cnpj":       cnpj,
                "nome":       d.get("razao_social",""),
                "fantasia":   d.get("nome_fantasia",""),
                "logradouro": d.get("logradouro",""),
                "numero":     d.get("numero",""),
                "bairro":     d.get("bairro",""),
                "municipio":  d.get("municipio",""),
                "uf":         d.get("uf",""),
            }
    except: pass
    return None

# ── Main ──────────────────────────────────────────────────────────

def main():
    print("=" * 52)
    print("NFG Tracker v2 — Atualização")
    print(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    # 1. Login
    print("\n[1/5] Login no NFG...")
    fazer_login()

    # 2. Chaves existentes no Sheets
    print("[2/5] Verificando chaves no Google Sheets...")
    chaves_existentes = sheets_get_chaves()
    cnpjs_existentes  = sheets_get_cnpjs_filiais()
    print(f"      {len(chaves_existentes)} chaves existentes | {len(cnpjs_existentes)} filiais")

    # 3. Busca notas no NFG
    print("[3/5] Buscando notas no portal NFG...")
    todas_notas = buscar_notas_nfg()
    novas = [n for n in todas_notas if n["chave"] not in chaves_existentes]
    print(f"      {len(todas_notas)} no portal | {len(novas)} novas")

    if not novas:
        print("\n[✓] Nada de novo!")
        return

    # 4. Extrai dados completos do SEFAZ
    print(f"[4/5] Extraindo dados de {len(novas)} nota(s) do SEFAZ...")
    linhas_itens   = []
    filiais_novas  = {}  # cnpj -> dados

    # cabeçalho da aba itens (só na primeira vez)
    precisa_header = len(chaves_existentes) == 0

    for i, nota in enumerate(novas, 1):
        chave = nota["chave"]
        print(f"  [{i:3d}/{len(novas)}] {nota['loja'][:40]}", end=" ", flush=True)

        resultado = extrair_nota_sefaz(chave)
        if not resultado:
            print("→ erro, pulando")
            continue

        cab   = resultado["cabecalho"]
        itens = resultado["itens"]

        # filial nova?
        cnpj = cab.get("cnpj","") or chave[6:20]
        if cnpj and cnpj not in cnpjs_existentes and cnpj not in filiais_novas:
            filial = buscar_filial(cnpj)
            if filial:
                filiais_novas[cnpj] = filial
                time.sleep(0.4)

        # monta linhas
        for item in itens:
            linhas_itens.append([
                chave,
                cab.get("numero",""),
                cab.get("serie",""),
                cab.get("emissao","") or nota["emissao"],
                cab.get("hora",""),
                cab.get("tipo","") or nota["tipo"],
                cnpj,
                nota["loja"],
                nota["municipio"],
                cab.get("valor_total",""),
                cab.get("desconto","0,00"),
                cab.get("pagamento",""),
                item["codigo"],
                item["descricao"],
                item["ncm"],
                item["quantidade"],
                item["unidade"],
                item["valor_unit"],
                item["valor_total"],
            ])

        print(f"→ {len(itens)} itens")
        time.sleep(0.3)

    # 5. Sobe para o Sheets
    print(f"\n[5/5] Subindo para Google Sheets...")

    # filiais novas
    if filiais_novas:
        print(f"  → {len(filiais_novas)} filiais novas...")
        precisa_header_filiais = len(cnpjs_existentes) == 0
        linhas_filiais = [[v[k] for k in CAMPOS_FILIAIS] for v in filiais_novas.values()]
        sheets_post("filiais", linhas_filiais,
                    header=CAMPOS_FILIAIS if precisa_header_filiais else None)

    # itens novos
    if linhas_itens:
        print(f"  → {len(linhas_itens)} itens novos...")
        sheets_post("itens", linhas_itens,
                    header=CAMPOS_ITENS if precisa_header else None)

    print(f"\n[✓] Concluído: +{len(novas)} notas, +{len(linhas_itens)} itens")

if __name__ == "__main__":
    main()
