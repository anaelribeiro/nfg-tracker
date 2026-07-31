from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.alert import Alert
from webdriver_manager.chrome import ChromeDriverManager
import csv, time
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
FIELDS = ["chave","emissao","loja","municipio","codigo","descricao","quantidade","unidade","valor_unit","valor_total"]

JS_EXTRACT = """
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
"""

notas = []
with open(DATA_DIR / "notas_2026.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if len(row["chave"]) == 44:
            notas.append(row)
print(f"Total notas: {len(notas)}", flush=True)

opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--disable-gpu")
opts.add_argument("--ignore-certificate-errors")
opts.add_argument("--window-size=1280,900")
opts.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
ok = err = sem = 0

with open(DATA_DIR / "itens.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    writer.writeheader()
    for i, nota in enumerate(notas, 1):
        chave = nota["chave"]
        try:
            driver.get(f"https://www.sefaz.rs.gov.br/NFE/NFE-NFC.aspx?chaveNFe={chave}")
            time.sleep(1.5)
            try: Alert(driver).accept(); time.sleep(0.5)
            except: pass
            driver.switch_to.frame("iframeConteudo")
            time.sleep(0.5)
            driver.find_element(By.XPATH, "//input[@value='Avançar']").click()
            time.sleep(2.5)
            rows_data = driver.execute_script(JS_EXTRACT)
            if rows_data:
                for cols in rows_data:
                    writer.writerow({
                        "chave": chave, "emissao": nota["emissao"],
                        "loja": nota["loja"], "municipio": nota["municipio"],
                        "codigo": cols[0], "descricao": cols[1],
                        "quantidade": cols[2], "unidade": cols[3] if len(cols)>3 else "",
                        "valor_unit": cols[4] if len(cols)>4 else "",
                        "valor_total": cols[5] if len(cols)>5 else "",
                    })
                f.flush()
                ok += 1
                print(f"[{i:3d}/{len(notas)}] OK  {nota['loja'][:35]:35s} {len(rows_data):2d} itens", flush=True)
            else:
                sem += 1
                print(f"[{i:3d}/{len(notas)}] --- {nota['loja'][:35]:35s} sem itens", flush=True)
            driver.switch_to.default_content()
        except Exception as e:
            err += 1
            print(f"[{i:3d}/{len(notas)}] ERR {chave[:8]} {str(e)[:50]}", flush=True)
            try: driver.switch_to.default_content()
            except: pass
        time.sleep(0.3)

driver.quit()
print(f"\nFinalizado: {ok} OK | {sem} sem itens | {err} erros", flush=True)
