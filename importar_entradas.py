#!/usr/bin/env python3
# importar_entradas.py — extrai entradas reais dos OFXs (salário Itaú + PIX recebidos Nubank)

import glob, json, re, time, requests
from datetime import datetime
from pathlib import Path

PASTA_PIX = 'pix'

with open(Path(__file__).parent / 'config_privado.json') as f:
    _cfg = json.load(f)
SUPA_URL    = _cfg['supabase_url']
SUPA_SECRET = _cfg['supabase_secret']
SUPA_HEADERS = {
    'apikey': SUPA_SECRET,
    'Authorization': f'Bearer {SUPA_SECRET}',
    'Content-Type': 'application/json',
    'Prefer': 'resolution=ignore-duplicates,return=minimal'
}

# Filtros
CONTAS_PROPRIAS = ['031.326.770-78','03132677078','0295997399','99739-9','anael d','anael d']
IGNORAR_MEMO    = ['resgate rdb','resgate cdb','pagamento recebido','estorno','cashback','rendimento','resgate']

def supa_upsert(rows, batch=100):
    for i in range(0, len(rows), batch):
        b = rows[i:i+batch]
        r = requests.post(
            f'{SUPA_URL}/rest/v1/entradas?on_conflict=data,descricao,valor',
            headers=SUPA_HEADERS, json=b, timeout=30
        )
        if r.status_code not in (200, 201):
            print(f'  ERRO {r.status_code}: {r.text[:150]}')
        print(f'  {min(i+batch, len(rows))}/{len(rows)}', flush=True)
        time.sleep(0.3)

def buscar_existentes():
    print('Buscando entradas existentes no Supabase...')
    existentes = set()
    offset = 0
    while True:
        r = requests.get(
            f'{SUPA_URL}/rest/v1/entradas?select=data,descricao,valor&limit=1000&offset={offset}',
            headers=SUPA_HEADERS, timeout=20
        )
        rows = r.json()
        if not rows: break
        for row in rows:
            existentes.add(f"{row['data']}|{row['descricao']}|{row['valor']}")
        if len(rows) < 1000: break
        offset += 1000
    print(f'  {len(existentes)} registros já existentes')
    return existentes

def parse_data(dt_str):
    try:
        return datetime.strptime(dt_str[:8], '%Y%m%d').strftime('%d/%m/%Y')
    except:
        return dt_str[:8]

def classifica_tipo(memo):
    m = memo.lower()
    if any(x in m for x in ['salario','remuneracao','folha']): return 'Salário'
    if any(x in m for x in ['transferência recebida','transferencia recebida','pix recebido']): return 'PIX recebido'
    if 'devolucao' in m or 'estorno' in m: return 'Devolução'
    return 'Outros'

def ler_ofx_entradas(path):
    banco = 'Nubank' if 'NU_' in path.upper() else 'Itaú'
    with open(path, 'r', encoding='utf-8' if 'NU_' in path.upper() else 'latin-1', errors='replace') as f:
        content = f.read()

    entradas = []
    for bloco in re.findall(r'<STMTTRN>(.*?)</STMTTRN>', content, re.DOTALL):
        def get(tag):
            m = re.search(rf'<{tag}>(.*?)(?:</{tag}>|[\r\n])', bloco, re.IGNORECASE)
            return m.group(1).strip() if m else ''

        try: valor = float(get('TRNAMT'))
        except: continue
        if valor <= 0: continue  # só créditos

        memo = get('MEMO')
        ml   = memo.lower()

        # ignora transferências entre contas próprias
        if any(c.lower() in ml for c in CONTAS_PROPRIAS): continue
        # ignora resgates e rendimentos
        if any(x in ml for x in IGNORAR_MEMO): continue
        # ignora pagamento de fatura
        if 'pagamento' in ml and 'recebid' not in ml: continue

        tipo = classifica_tipo(memo)
        data = parse_data(get('DTPOSTED'))

        entradas.append({
            'data': data,
            'banco': banco,
            'tipo': tipo,
            'valor': valor,
            'descricao': memo[:80],
            'memo': memo[:200]
        })

    return entradas

def main():
    arquivos = sorted(glob.glob(f'{PASTA_PIX}/*.ofx') + glob.glob(f'{PASTA_PIX}/*.OFX'))
    # adiciona OFX do Itaú conta corrente se existir
    itau_cc = sorted(glob.glob('pix/Extrato*.ofx'))
    todos_arq = arquivos  # já inclui Extrato se estiver na pasta pix

    if not todos_arq:
        print('Nenhum OFX encontrado.')
        return

    print(f'{len(todos_arq)} arquivo(s)\n')
    existentes = buscar_existentes()
    novos = []

    for path in todos_arq:
        nome = path.split('/')[-1]
        print(f'Lendo {nome}...')
        try:
            entradas = ler_ofx_entradas(path)
            n = 0
            for e in entradas:
                chave = f"{e['data']}|{e['descricao']}|{e['valor']}"
                if chave not in existentes:
                    novos.append(e)
                    existentes.add(chave)
                    n += 1
            print(f'  {len(entradas)} entradas encontradas, {n} novas')
        except Exception as ex:
            print(f'  ERRO: {ex}')

    if not novos:
        print('\nNenhuma entrada nova.')
        return

    print(f'\nSubindo {len(novos)} entradas...')
    supa_upsert(novos)
    print(f'\nConcluído! {len(novos)} entradas no Supabase.')

if __name__ == '__main__':
    main()
