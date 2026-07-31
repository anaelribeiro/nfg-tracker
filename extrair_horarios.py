from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.alert import Alert
from webdriver_manager.chrome import ChromeDriverManager
import csv, time, re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

notas = []
with open(DATA_DIR / "notas_2026.csv", newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        notas.append(row)

# verifica se já temos coluna de hora
if "hora" in fieldnames:
    print("Coluna hora já existe. Verificando quais estão vazias...")
    pendentes = [n for n in notas if not n.get("hora","").strip()]
else:
    print("Adicionando coluna hora...")
    fieldnames = list(fieldnames) + ["hora"]
    for n in notas: n["hora"] = ""
    pendentes = notas

print(f"Notas para extrair hora: {len(pendentes)}")

opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--disable-gpu")
opts.add_argument("--ignore-certificate-errors")
opts.add_argument("--window-size=1280,900")
opts.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

# mapa chave -> hora
hora_map = {n["chave"]: n.get("hora","") for n in notas}

for i, nota in enumerate(pendentes, 1):
    chave = nota["chave"]
    if len(chave) != 44:
        continue
    try:
        driver.get(f"https://www.sefaz.rs.gov.br/NFE/NFE-NFC.aspx?chaveNFe={chave}")
        time.sleep(1.5)
        try: Alert(driver).accept(); time.sleep(0.5)
        except: pass
        driver.switch_to.frame("iframeConteudo")
        time.sleep(0.5)
        driver.find_element(By.XPATH, "//input[@value='Avançar']").click()
        time.sleep(2.5)
        
        body = driver.find_element(By.TAG_NAME, "body").text
        m = re.search(r'Data de Emiss[aã]o[:\s]+\d{2}/\d{2}/\d{4}\s+(\d{2}:\d{2}:\d{2})', body)
        if m:
            hora_map[chave] = m.group(1)
            print(f"[{i:3d}/{len(pendentes)}] {nota['loja'][:35]:35s} {m.group(1)}", flush=True)
        else:
            hora_map[chave] = ""
            print(f"[{i:3d}/{len(pendentes)}] {nota['loja'][:35]:35s} sem hora", flush=True)

        # salva incrementalmente a cada 10 notas
        if i % 10 == 0:
            for n in notas:
                n["hora"] = hora_map.get(n["chave"], "")
            with open(DATA_DIR / "notas_2026.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(notas)
            print(f"  [auto-save {i} notas]", flush=True)
        
        driver.switch_to.default_content()
    except Exception as e:
        print(f"[{i:3d}/{len(pendentes)}] ERR {str(e)[:50]}", flush=True)
        try: driver.switch_to.default_content()
        except: pass
    time.sleep(0.3)

driver.quit()

# salva notas_2026.csv com coluna hora
for n in notas:
    n["hora"] = hora_map.get(n["chave"], "")

with open(DATA_DIR / "notas_2026.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(notas)

print(f"\nConcluído. {sum(1 for n in notas if n.get('hora'))} notas com hora.")
