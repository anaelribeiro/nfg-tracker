#!/usr/bin/env python3
"""
NFG Tracker — Atualização incremental
Busca só as notas novas e atualiza o dashboard.
"""

import csv, json, time, subprocess, sys, warnings
import xml.etree.ElementTree as ET
import requests
from pathlib import Path

# ── Configuração Google Sheets ────────────────────────────────────
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbwpfWeHAm8_wBt-r6LVkCCXVTP3AyygtOTV1Dif7iIiJU712yGwV2_hybAwmJQzcgZ3-Q/exec"
SHEET_ID        = "1Z69HQfCHm_wW3aaP9mMyMa4zDNhqPbJd5NaIX9i3b-c"
SHEET_CSV_URL   = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=dados"
from datetime import datetime

try:
    import browser_cookie3
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.alert import Alert
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("[!] Dependências faltando. Rode: pip install browser-cookie3 selenium webdriver-manager")
    sys.exit(1)

warnings.filterwarnings("ignore")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

NOTAS_CSV  = DATA_DIR / "notas_2026.csv"
ITENS_CSV  = DATA_DIR / "itens.csv"
DASH_HTML  = DATA_DIR / "dashboard.html"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

FIELDS_NOTAS = ["municipio","loja","emissao","numero","tipo","chave","valor"]
FIELDS_ITENS = ["chave","emissao","loja","municipio","codigo","descricao","quantidade","unidade","valor_unit","valor_total"]

# ── Helpers ──────────────────────────────────────────────────────────────────

def chrome_opts(headless=True):
    opts = Options()
    opts.binary_location = CHROME_BIN
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--window-size=1280,900")
    if headless:
        opts.add_argument("--headless=new")
    return opts

def novo_driver(headless=True):
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_opts(headless)
    )

# ── Passo 1: verifica sessão NFG ─────────────────────────────────────────────

def sessao_ativa():
    jar = browser_cookie3.chrome(domain_name="sefaz.rs.gov.br")
    session = requests.Session()
    for c in jar:
        session.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
    hdrs = {"User-Agent": "Mozilla/5.0"}
    try:
        r = session.get("https://nfg.sefaz.rs.gov.br/cadastro/ConsultaDocumentos.aspx",
                        verify=False, headers=hdrs, timeout=8)
        return "ConsultaDocumentos" in r.url
    except:
        return False

def pedir_login():
    print("\n[!] Sessão NFG expirada. Abrindo Chrome para login...")
    print("    Faça login com GOV.BR e aguarde fechar automaticamente.\n")
    driver = novo_driver(headless=False)
    wait_time = 300
    from selenium.webdriver.support.ui import WebDriverWait
    wait = WebDriverWait(driver, wait_time)
    try:
        driver.get("https://nfg.sefaz.rs.gov.br/govbr-redirect.aspx")
        wait.until(lambda d: "nfg.sefaz.rs.gov.br" in d.current_url
                              and "govbr" not in d.current_url
                              and "sso.acesso" not in d.current_url
                              and "Login" not in d.current_url)
        print("[✓] Login detectado!")
        time.sleep(1)
    finally:
        driver.quit()

# ── Passo 2: busca notas novas via AJAX ──────────────────────────────────────

def buscar_notas_novas():
    from bs4 import BeautifulSoup

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
    html = (root.findtext("DadosRetorno") or "").encode("latin-1").decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    tabela = soup.find("table")
    if not tabela:
        return []

    notas = []
    for row in tabela.find_all("tr")[1:]:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 7:
            continue
        chave = cols[6].replace(" ", "").replace("\n", "")
        notas.append({
            "municipio": cols[1], "loja": cols[2], "emissao": cols[3],
            "numero": cols[4], "tipo": cols[5], "chave": chave, "valor": cols[7] if len(cols)>7 else "",
        })
    return notas

# ── Passo 3: extrai itens das notas novas ────────────────────────────────────

def extrair_itens_novas(notas_novas):
    if not notas_novas:
        return []

    opts = chrome_opts(headless=True)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    itens = []

    for i, nota in enumerate(notas_novas, 1):
        chave = nota["chave"]
        print(f"  [{i}/{len(notas_novas)}] {nota['loja'][:40]}", end=" ", flush=True)
        try:
            driver.get(f"https://www.sefaz.rs.gov.br/NFE/NFE-NFC.aspx?chaveNFe={chave}")
            time.sleep(1.5)
            try: Alert(driver).accept(); time.sleep(0.5)
            except: pass
            driver.switch_to.frame("iframeConteudo")
            time.sleep(0.5)
            driver.find_element(By.XPATH, "//input[@value='Avançar']").click()
            time.sleep(2.5)

            rows_data = driver.execute_script("""
                var result=[];var seen=new Set();
                document.querySelectorAll('tr').forEach(function(row){
                    var tds=row.querySelectorAll('td');
                    if(tds.length>=5&&/^\\d+$/.test(tds[0].innerText.trim())){
                        var key=tds[0].innerText.trim();
                        if(!seen.has(key)){seen.add(key);
                            result.push(Array.from(tds).slice(0,6).map(function(td){return td.innerText.trim();}));}
                    }
                });return result;
            """)

            for cols in rows_data:
                itens.append({
                    "chave": chave, "emissao": nota["emissao"],
                    "loja": nota["loja"], "municipio": nota["municipio"],
                    "codigo": cols[0], "descricao": cols[1],
                    "quantidade": cols[2], "unidade": cols[3] if len(cols)>3 else "",
                    "valor_unit": cols[4] if len(cols)>4 else "",
                    "valor_total": cols[5] if len(cols)>5 else "",
                })
            print(f"→ {len(rows_data)} itens")
            driver.switch_to.default_content()
        except Exception as e:
            print(f"→ ERR: {str(e)[:50]}")
            try: driver.switch_to.default_content()
            except: pass
        time.sleep(0.3)

    driver.quit()
    return itens

# ── Passo 4: salva e gera dashboard ──────────────────────────────────────────

def salvar_notas(notas):
    existe = NOTAS_CSV.exists()
    with open(NOTAS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS_NOTAS)
        if not existe: w.writeheader()
        w.writerows(notas)

def salvar_itens(itens):
    existe = ITENS_CSV.exists()
    with open(ITENS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS_ITENS)
        if not existe: w.writeheader()
        w.writerows(itens)

def gerar_dashboard():
    script_dir = Path(__file__).parent
    result = subprocess.run(
        ["python3", str(script_dir / "gerar_dashboard.py")],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"[✓] {result.stdout.strip() or 'Dashboard gerado'}")
    else:
        print(f"[!] Erro no dashboard: {result.stderr[:100]}")

def subir_sheets():
    """Sobe apenas os itens novos (diferencial) para o Google Sheets."""
    if not ITENS_CSV.exists():
        print("[!] itens.csv não encontrado")
        return

    # lê todos os itens locais
    with open(ITENS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    if len(all_rows) < 2:
        print("[!] itens.csv vazio")
        return

    header = all_rows[0]
    data_rows = all_rows[1:]

    # descobre quantas linhas já estão na planilha
    print("[*] Verificando planilha Google Sheets...")
    try:
        r = requests.get(SHEET_CSV_URL, timeout=10)
        if r.status_code == 200:
            existing = r.text.strip().split('\n')
            # desconta cabeçalho
            linhas_existentes = len(existing) - 1 if len(existing) > 1 else 0
        else:
            linhas_existentes = 0
    except Exception as e:
        print(f"[!] Não foi possível verificar Sheets: {e}")
        linhas_existentes = 0

    novas = data_rows[linhas_existentes:]

    if not novas:
        print(f"[✓] Sheets já atualizado ({linhas_existentes} linhas)")
        return

    print(f"    Sheets tem {linhas_existentes} linhas, local tem {len(data_rows)} — enviando {len(novas)} novas...")

    try:
        # se não tem cabeçalho ainda, manda primeiro
        if linhas_existentes == 0:
            requests.post(APPS_SCRIPT_URL, json={"action":"header","row":header}, timeout=30)

        # manda em lotes de 50
        BATCH = 50
        for i in range(0, len(novas), BATCH):
            batch = novas[i:i+BATCH]
            requests.post(APPS_SCRIPT_URL, json={"rows": batch}, timeout=60)
            sent = min(i+BATCH, len(novas))
            print(f"  {sent}/{len(novas)} linhas", flush=True)
            time.sleep(0.3)

        print(f"[✓] +{len(novas)} linhas enviadas para o Sheets")
        print(f"    docs.google.com/spreadsheets/d/{SHEET_ID}")
    except Exception as e:
        print(f"[!] Erro ao enviar para Sheets: {e}")

def publicar_github():
    """Faz git push do index.html existente (não sobrescreve)."""
    repo_dir = Path(__file__).parent

    # git push — apenas commita o index.html existente sem modificar
    try:
        subprocess.run(["git", "-C", str(repo_dir), "add", "index.html"], check=True)
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "commit", "-m",
             f"Atualiza dashboard — {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}"],
            capture_output=True, text=True
        )
        if "nothing to commit" in result.stdout + result.stderr:
            print("[✓] GitHub Pages já atualizado (sem mudanças)")
            return
        subprocess.run(["git", "-C", str(repo_dir), "push"], check=True)
        print("[✓] Publicado em anaelribeiro.github.io/nfg-tracker")
        print("     (atualiza em ~1 minuto)")
    except Exception as e:
        print(f"[!] Erro ao publicar no GitHub: {e}")

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 52)
    print("NFG Tracker — Atualização de compras")
    print(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 52)

    # chaves já processadas
    chaves_conhecidas = set()
    if NOTAS_CSV.exists():
        with open(NOTAS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                chaves_conhecidas.add(row["chave"])
    print(f"[*] Notas já registradas: {len(chaves_conhecidas)}")

    # passo 1: verifica login
    print("[1/4] Verificando sessão NFG...")
    if not sessao_ativa():
        pedir_login()
        if not sessao_ativa():
            print("[!] Login falhou.")
            return
    print("      Sessão OK")

    # passo 2: busca notas
    print("[2/4] Buscando notas no portal NFG...")
    todas_notas = buscar_notas_novas()
    novas = [n for n in todas_notas if n["chave"] not in chaves_conhecidas and len(n["chave"]) == 44]
    print(f"      {len(todas_notas)} notas no portal | {len(novas)} novas")

    if not novas:
        print("\n[✓] Nada de novo. Dashboard já está atualizado!")
        import os; os.system(f"open '{DASH_HTML}'")
        return

    # passo 3: extrai itens
    print(f"[3/4] Extraindo itens de {len(novas)} nota(s) nova(s)...")
    itens_novos = extrair_itens_novas(novas)

    # passo 4: salva e atualiza
    print("[4/4] Salvando e atualizando dashboard...")
    salvar_notas(novas)
    if itens_novos:
        salvar_itens(itens_novos)
    gerar_dashboard()
    subir_sheets()
    publicar_github()

    print(f"\n[✓] Concluído: +{len(novas)} notas, +{len(itens_novos)} itens")
    import os; os.system(f"open '{DASH_HTML}'")

if __name__ == "__main__":
    main()
