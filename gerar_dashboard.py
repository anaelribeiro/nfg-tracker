#!/usr/bin/env python3
"""
Gera dashboard.html completo a partir dos CSVs.
Chamado pelo atualizar.py após cada extração de dados.
"""
import csv, json, os, subprocess
from pathlib import Path
from datetime import datetime
from collections import defaultdict

BASE_DIR = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"

CATEGORIAS = [
    ("🥩 Carnes",["carne","fraldinha","patinho","alcatra","bife","file","coxa","scx","fgo","frango","suino","ling suina","filezinho","picanha","costela","bov","vac","linguica","salame","copa","bacon","mortadela","presunto","peito","sassami","sobrecoxa","espeto"]),
    ("🥛 Laticínios",["leite","requeijao","queij","quei","iogurte","iog","creme de leite","cr leite","nata","manteig","mussarela","muss","parmesao","ricota","danette","chandelle"]),
    ("🥤 Bebidas",["refri","agua min","suco","nect","beb lac","cerveja","chopp","vinho","energetico","beb energ","monster","agua coco","leite cond","drops halls"]),
    ("🍞 Padaria",["pao","rosca","cuca","torta","bolo","bolinho","biscoito","wafer","cookie","crackers","broa","wickbold","seven boys"]),
    ("🥦 Hortifruti",["tomate","batata","cebola","alho","cenoura","pepino","laranja","bergamota","limao","abacaxi","beterraba","repolho","couve","brocolis","alface","rucula","morango","uva","maca","pera","manga","mamao","melao","melancia","banana","hortalica","verdur","fruta","piment","berinjela","abobrinha","pinhao","semente","erva mate"]),
    ("🍫 Doces&Snacks",["choc","achoc","bala","bombom","chiclete","doce","geleia","salg","batata palha","salgad","amendoim","castanha","granola","bisc rech","rocklets","baklawa"]),
    ("🍝 Mercearia",["arroz","feijao","massa","macarrao","espaguete","farinha","polvilho","fuba","aveia","azeite","oleo","vinagre","molho","catchup","maion","mostarda","tempero","acucar","cafe","extrato","caldo","ervilha","milho","lentilha","grao","substrato"]),
    ("🧴 Higiene",["sabao","deterg","desinfet","limpa","limpol","pap hig","absorv","desodor","creme dent","cr dent","shampoo","condic","sabonete","sabt","escova","esc den","alcool","lav louca","amaciante","esponja","saco lixo","inseticida","cloro"]),
    ("💊 Saúde",["farma","medic","remedio","vitamina","suplemento","diclof","resfben","sundown","pomada","prot sun"]),
    ("👗 Vestuário",["camiseta","calca","vestido","blusa","shorts","tenis","sapato","sandalia","meia","cueca","polo","bermuda","moletom","manga curta"]),
    ("🔧 Casa",["lamp","plaf","disco","broca","paraf","ferro solda","solda","cabo","tomada","fita","conec","nipel","prat ","can ","rotetor","braco chuv","engate","valv","sifao","vedarosca","lixa","refletor","elet corru"]),
    ("🏗️ Outros",[]),
]

ULTRA_KW = ['REFRI','ENERGETICO','MONSTER','BALA','BOMBOM','WAFER','SALGAD','BATATA PALHA',
            'LINGUICA','LING SUINA','PRESUNTO','MORTADELA','BACON','SALAME','SALSICHA',
            'NUGGET','EMPANADO','FRANKFURT','HOT DOG','MACARRAO INST','MIOJO']
SAUD_KW  = ['FRALDINHA','PATINHO','ALCATRA','BIFE','FILE ','COXA','FRANGO','SUINO',
            'FILEZINHO','PICANHA','COSTELA','PEITO BOV','SASSAMI','SOBRECOXA',
            'LEITE','REQUEIJAO','QUEIJ','QUEI ','IOGURTE','IOG ','MUSSARELA',
            'RICOTA','OVO ','OVOS','TOMATE','CENOURA','PEPINO','BROCOLIS',
            'ALFACE','RUCULA','LARANJA','BANANA','MANGA','MORANGO','UVA',
            'HORTALICA','VERDUR','FRUTA','ARROZ','FEIJAO','AVEIA',
            'PAO FRANCES','PAO QUEI','BATATA BCA','BATATA COR']

def nutri(desc):
    d = desc.upper()
    if any(k in d for k in ULTRA_KW): return 'ultra'
    if any(k in d for k in SAUD_KW):  return 'saud'
    return 'neutro'

def categorizar(desc):
    d = desc.upper()
    for c, kws in CATEGORIAS[:-1]:
        if any(k.upper() in d for k in kws): return c
    return CATEGORIAS[-1][0]

def filial_label(chave, loja):
    enderecos = _get_enderecos()
    cnpj = chave[6:20] if len(chave) >= 20 else ""
    info = enderecos.get(cnpj, {})
    nome = info.get("fantasia","").strip() or info.get("nome","").strip() or loja
    addr = info.get("endereco","")
    parts = [p.strip() for p in addr.split(",")]
    short = ", ".join(parts[:3]) if len(parts) >= 3 else addr
    return f"{nome} — {short}" if short else nome

_enderecos_cache = None
def _get_enderecos():
    global _enderecos_cache
    if _enderecos_cache is None:
        ef = DATA_DIR / "cnpj_enderecos.json"
        _enderecos_cache = json.loads(ef.read_text(encoding="utf-8")) if ef.exists() else {}
    return _enderecos_cache

def gerar():
    hora_map = {}
    notas_csv = DATA_DIR / "notas_2026.csv"
    if notas_csv.exists():
        with open(notas_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                hora_map[row["chave"]] = row.get("hora","")

    itens = []
    with open(DATA_DIR/"itens.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try: row["valor_num"] = float(row["valor_total"].replace(",",".") or 0)
            except: row["valor_num"] = 0.0
            try: row["qtd_num"] = float(row["quantidade"].replace(",",".") or 0)
            except: row["qtd_num"] = 0.0
            try:
                d = datetime.strptime(row["emissao"], "%d/%m/%y")
                row["mes"] = d.strftime("%Y-%m"); row["dia"] = d.strftime("%Y-%m-%d")
                row["dia_fmt"] = d.strftime("%d/%m/%Y"); row["dia_sort"] = d
            except: row["mes"]="?"; row["dia"]="?"; row["dia_fmt"]="?"; row["dia_sort"]=datetime.min
            row["hora"] = hora_map.get(row["chave"],"")
            row["datetime_fmt"] = (row["dia_fmt"]+" "+row["hora"]).strip() if row["hora"] else row["dia_fmt"]
            row["categoria"] = categorizar(row["descricao"])
            row["filial_label"] = filial_label(row["chave"], row["loja"])
            cnpj = row["chave"][6:20] if len(row["chave"]) >= 20 else ""
            info = _get_enderecos().get(cnpj, {})
            row["loja_curta"] = (info.get("fantasia","").strip() or info.get("nome","").strip() or row["loja"])[:25]
            itens.append(row)

    total_notas = len({r["chave"] for r in itens})
    total_gasto = sum(r["valor_num"] for r in itens)

    por_cat = defaultdict(float); por_prod = defaultdict(lambda:{"total":0.0,"qtd":0.0,"compras":0,"unidade":"","cat":"","lojas":set(),"datas":[],"chaves":[]})
    por_loja = defaultdict(float); por_filial = defaultdict(float); por_mes = defaultdict(float)
    por_muni = defaultdict(float); por_dia = defaultdict(float); cat_mes = defaultdict(lambda: defaultdict(float))
    notas_por_dia = defaultdict(list); chaves_vistas = set()

    for r in itens:
        d = r["descricao"].strip().title()
        por_cat[r["categoria"]] += r["valor_num"]
        por_prod[d]["total"] += r["valor_num"]; por_prod[d]["qtd"] += r["qtd_num"]
        por_prod[d]["compras"] += 1; por_prod[d]["unidade"] = r["unidade"]; por_prod[d]["cat"] = r["categoria"]
        por_prod[d]["lojas"].add(r["loja_curta"])
        por_prod[d]["datas"].append((r["dia_sort"], r["datetime_fmt"]))
        por_prod[d]["chaves"].append(r["chave"])
        por_loja[r["loja"]] += r["valor_num"]; por_filial[r["filial_label"]] += r["valor_num"]
        por_mes[r["mes"]] += r["valor_num"]; por_muni[r["municipio"]] += r["valor_num"]
        por_dia[r["dia"]] += r["valor_num"]
        cat_mes[r["categoria"]][r["mes"]] += r["valor_num"]

    if notas_csv.exists():
        with open(notas_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["chave"] in chaves_vistas: continue
                chaves_vistas.add(row["chave"])
                try:
                    d = datetime.strptime(row["emissao"], "%d/%m/%y")
                    dia = d.strftime("%Y-%m-%d"); dia_fmt = d.strftime("%d/%m/%Y")
                except: dia="?"; dia_fmt="?"
                try: val = float(row["valor"].replace("R$","").replace(".","").replace(",",".").strip())
                except: val = 0
                cnpj = row["chave"][6:20] if len(row["chave"]) >= 20 else ""
                info = _get_enderecos().get(cnpj, {})
                loja_c = (info.get("fantasia","").strip() or info.get("nome","").strip() or row["loja"])[:30]
                notas_por_dia[dia].append({"loja":loja_c,"val":val,"dia_fmt":dia_fmt})

    cat_sorted = sorted(por_cat.items(), key=lambda x:x[1], reverse=True)
    top_prod = sorted(por_prod.items(), key=lambda x:x[1]["total"], reverse=True)[:60]
    top_lojas = sorted(por_loja.items(), key=lambda x:x[1], reverse=True)[:12]
    top_filiais = sorted(por_filial.items(), key=lambda x:x[1], reverse=True)
    meses_ord = sorted(por_mes.items()); top_muni = sorted(por_muni.items(), key=lambda x:x[1], reverse=True)[:10]
    dias_ord = sorted(por_dia.items()); meses_all = sorted(por_mes.keys()); cats_list = [c[0] for c in cat_sorted]
    dias_tabela = sorted(notas_por_dia.items(), reverse=True)

    stacked_sets = [{"label":c.split(" ",1)[1] if " " in c else c,
        "data":[round(cat_mes[c].get(m,0),2) for m in meses_all],
        "backgroundColor":["#38bdf8","#34d399","#a78bfa","#f472b6","#fb923c","#facc15","#4ade80","#60a5fa"][i],
        "borderRadius":2,"stack":"s"} for i,c in enumerate(cats_list[:8])]

    prod_notas_all = defaultdict(list); prod_notas_seen = defaultdict(set)
    for r in itens:
        d = r["descricao"].strip().title()
        chave = r["chave"]
        if chave not in prod_notas_seen[d]:
            prod_notas_seen[d].add(chave)
            prod_notas_all[d].append({"chave":chave,"data":r["datetime_fmt"],"loja":r["loja_curta"],"filial":r["filial_label"],"mes":r["mes"],"val":r["valor_num"]})
    for d in prod_notas_all:
        prod_notas_all[d].sort(key=lambda x:x["data"],reverse=True)

    jl = lambda lst: json.dumps([x[0] for x in lst])
    jv = lambda lst: json.dumps([round(x[1] if isinstance(x[1],float) else x[1]["total"],2) for x in lst])

    js_vars = "\n".join([
        f"const ALL_ITENS={json.dumps([{'desc':r['descricao'].strip().title(),'loja':r['loja'],'filial':r['filial_label'],'muni':r['municipio'],'mes':r['mes'],'dia':r['dia'],'val':r['valor_num'],'qtd':r['qtd_num'],'un':r['unidade'],'data':r['datetime_fmt'],'cat':r['categoria'],'nutri':nutri(r['descricao']),'loja_c':r['loja_curta'],'chave':r['chave']} for r in itens])};",
        f"const PROD_NOTAS={json.dumps(dict(prod_notas_all))};",
        f"const LAB_MES_I={json.dumps([x[0] for x in meses_ord])},VAL_MES_I={json.dumps([round(x[1],2) for x in meses_ord])};",
        f"const LAB_DIA_I={json.dumps([x[0] for x in dias_ord])},VAL_DIA_I={json.dumps([round(x[1],2) for x in dias_ord])};",
        f"const LAB_LOJAS_I={jl(top_lojas)},VAL_LOJAS_I={jv(top_lojas)};",
        f"const LAB_FILIAIS_I={jl(top_filiais)},VAL_FILIAIS_I={jv(top_filiais)};",
        f"const LAB_MUNI={jl(top_muni)},VAL_MUNI={jv(top_muni)};",
        f"const LAB_CAT={json.dumps([c.split(' ',1)[1] if ' ' in c else c for c,_ in cat_sorted])},VAL_CAT={json.dumps([round(v,2) for _,v in cat_sorted])};",
        f"const CATS_FULL={json.dumps(cats_list)};",
        f"const CAT_MES_DATA={json.dumps({c:dict(mv) for c,mv in cat_mes.items()})};",
        f"const MESES_ALL={json.dumps(meses_all)};",
        f"const STACKED_SETS={json.dumps(stacked_sets)};",
        f"const LOJAS_LIST={json.dumps(sorted(por_loja.keys()))};",
        f"const MESES_LIST={json.dumps(sorted(por_mes.keys()))};",
        f"const MUNI_LIST={json.dumps(sorted(por_muni.keys()))};",
        f"const FILIAIS_LIST={json.dumps([x[0] for x in top_filiais])};",
        f"const CATS_LIST={json.dumps(cats_list)};",
        f"const TOTAL_GASTO={total_gasto:.2f};",
    ])

    # salva dados.js
    dados_js = "// NFG Tracker dados — não commitar\n" + js_vars + "\n"
    (DATA_DIR/"dados.js").write_text(dados_js, encoding="utf-8")

    # lê template do index.html (que tem o código JS completo)
    # extrai só o HTML+código sem os dados
    index = BASE_DIR/"index.html"
    if not index.exists():
        print("[!] index.html não encontrado, não foi possível gerar dashboard.html")
        return

    html = index.read_text(encoding="utf-8")

    # o index.html carrega dados do Sheets — para o dashboard local,
    # substituímos o loader por <script src="dados.js"></script>
    import re
    # remove o loader script (entre primeiro <script> e </script>)
    lines = html.split('\n')
    script_tags = [(i,l) for i,l in enumerate(lines) if l.strip() in ('<script>','</script>')]
    if len(script_tags) >= 2:
        loader_start = script_tags[0][0]
        loader_end   = script_tags[1][0]
        # substitui loader por dados.js
        new_lines = (lines[:loader_start]
            + ['<script src="dados.js"></script>']
            + lines[loader_end+1:])
        dash_html = '\n'.join(new_lines)
    else:
        dash_html = html

    # atualiza data no topbar
    dash_html = re.sub(r'NFG Tracker · [\d/]+ [\d:]+',
        f'NFG Tracker · {datetime.now().strftime("%d/%m/%Y %H:%M")}', dash_html)

    (DATA_DIR/"dashboard.html").write_text(dash_html, encoding="utf-8")
    print(f"[✓] Dashboard: {DATA_DIR}/dashboard.html ({total_notas} notas, {len(itens)} itens)")
    os.system(f"open '{DATA_DIR}/dashboard.html'")

if __name__ == "__main__":
    gerar()
