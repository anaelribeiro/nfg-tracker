#!/usr/bin/env python3
# importar_fatura.py — lê XLSX (Itaú) e OFX (Nubank) e sobe diferencial no Supabase (tabela cartao)

import glob, json, re, time, requests, openpyxl
from datetime import datetime
from pathlib import Path

PASTA_FATURAS = 'faturas'
HEADER_ROW    = 14
COLUNAS_REMOVER = ['Nome', 'Número do cartão']

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

def supa_upsert(rows, batch=100):
    for i in range(0, len(rows), batch):
        b = rows[i:i+batch]
        r = requests.post(
            f'{SUPA_URL}/rest/v1/cartao?on_conflict=data,lancamento,valor',
            headers=SUPA_HEADERS, json=b, timeout=30
        )
        if r.status_code not in (200, 201):
            print(f'  ERRO {r.status_code}: {r.text[:150]}')
        print(f'  {min(i+batch, len(rows))}/{len(rows)}', flush=True)
        time.sleep(0.3)

def buscar_existentes():
    """Retorna set de chaves data|lancamento|valor já no Supabase."""
    print('Buscando lançamentos existentes no Supabase...')
    existentes = set()
    offset = 0
    while True:
        r = requests.get(
            f'{SUPA_URL}/rest/v1/cartao?select=data,lancamento,valor&limit=1000&offset={offset}',
            headers=SUPA_HEADERS, timeout=20
        )
        rows = r.json()
        if not rows: break
        for row in rows:
            existentes.add(f"{row['data']}|{row['lancamento']}|{row['valor']}")
        if len(rows) < 1000: break
        offset += 1000
    print(f'  {len(existentes)} lançamentos já existentes')
    return existentes

def chave_lancamento(linha, header):
    """Chave única: data + lançamento + valor"""
    idx = {h: i for i, h in enumerate(header)}
    data  = linha[idx.get('Data', 0)] if 'Data' in idx else ''
    desc  = linha[idx.get('Lançamento', 1)] if 'Lançamento' in idx else ''
    valor = linha[idx.get('Valor', 3)] if 'Valor' in idx else ''
    return f'{data}|{desc}|{valor}'

def buscar_existentes():
    """Retorna set de chaves já no Supabase."""
    print('Buscando lançamentos existentes no Supabase...')
    existentes = set()
    offset = 0
    while True:
        r = requests.get(
            f'{SUPA_URL}/rest/v1/cartao?select=data,lancamento,valor&limit=1000&offset={offset}',
            headers=SUPA_HEADERS, timeout=20
        )
        rows = r.json()
        if not rows: break
        for row in rows:
            existentes.add(f"{row['data']}|{row['lancamento']}|{row['valor']}")
        if len(rows) < 1000: break
        offset += 1000
    print(f'  {len(existentes)} lançamentos já existentes')
    return existentes

def ler_fatura(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    header_raw = [str(c).strip() if c is not None else '' for c in rows[HEADER_ROW - 1]]
    keep = [i for i, h in enumerate(header_raw) if h and h not in COLUNAS_REMOVER]
    header = [header_raw[i] for i in keep]

    lancamentos = []
    for row in rows[HEADER_ROW:]:
        vals = list(row)
        if all(v is None for v in vals):
            continue
        # filtra só datas reais
        data_raw = vals[keep[0]] if keep else None
        if not isinstance(data_raw, datetime) and not (isinstance(data_raw, str) and len(data_raw) == 10):
            continue
        linha = []
        for i in keep:
            v = vals[i] if i < len(vals) else None
            if isinstance(v, datetime):
                linha.append(v.strftime('%d/%m/%Y'))
            elif v is None:
                linha.append('')
            else:
                linha.append(str(v))
        lancamentos.append(linha)

    return header, lancamentos

def ler_fatura_ofx(path):
    """Lê OFX do cartão de crédito Nubank — retorna lista de dicts no mesmo formato do Itaú."""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    lancamentos = []
    for bloco in re.findall(r'<STMTTRN>(.*?)</STMTTRN>', content, re.DOTALL):
        def get(tag):
            m = re.search(rf'<{tag}>(.*?)(?:</{tag}>|[\r\n])', bloco, re.IGNORECASE)
            return m.group(1).strip() if m else ''

        tipo  = get('TRNTYPE')
        dt    = get('DTPOSTED')[:8]
        valor = get('TRNAMT')
        memo  = get('MEMO')

        # só débitos (compras) — ignora pagamentos
        try:
            v = float(valor)
        except:
            continue
        if v >= 0:
            continue
        if 'pagamento' in memo.lower():
            continue

        try:
            d = datetime.strptime(dt, '%Y%m%d')
            data_fmt = d.strftime('%d/%m/%Y')
        except:
            continue

        lancamentos.append({
            'data': data_fmt,
            'lancamento': memo,
            'parcelamento': '',
            'valor': abs(v),
            'titularidade': 'Titular',
            'tipo_cartao': 'Nubank'
        })

    return lancamentos

def main():
    arquivos_xlsx = sorted(glob.glob(f'{PASTA_FATURAS}/fatura*.xlsx'))
    arquivos_ofx  = sorted(glob.glob(f'{PASTA_FATURAS}/Nubank*.ofx'))
    arquivos = arquivos_xlsx + arquivos_ofx

    if not arquivos:
        print('Nenhum arquivo encontrado em', PASTA_FATURAS)
        return

    print(f'{len(arquivos_xlsx)} XLSX + {len(arquivos_ofx)} OFX encontrados\n')

    existentes = buscar_existentes()

    todos_novos = []

    for path in arquivos:
        nome = path.split('/')[-1]
        print(f'Lendo {nome}...')
        try:
            if path.endswith('.ofx'):
                lancamentos_raw = ler_fatura_ofx(path)
                novos = []
                for l in lancamentos_raw:
                    chave = f"{l['data']}|{l['lancamento']}|{l['valor']}"
                    if chave not in existentes:
                        novos.append(l)
                        existentes.add(chave)
                todos_novos.extend(novos)
                print(f'  {len(lancamentos_raw)} lidos, {len(novos)} novos')
            else:
                header, lancamentos = ler_fatura(path)
            novos = []
            for ln in lancamentos:
                chave = chave_lancamento(ln, header)
                if chave not in existentes:
                    novos.append(ln)
                    existentes.add(chave)
            todos_novos.extend(novos)
            print(f'  {len(lancamentos)} lidos, {len(novos)} novos')
        except Exception as e:
            print(f'  ERRO: {e}')

    if not todos_novos:
        print('\nNenhum lançamento novo. Supabase já está atualizado.')
        return

    # converte listas para dicts usando header do primeiro arquivo
    header_ref = None
    for path in arquivos:
        try:
            h, _ = ler_fatura(path)
            header_ref = h
            break
        except: pass

    print(f'\nSubindo {len(todos_novos)} novos lançamentos...')
    col_map = {'Data':'data','Lançamento':'lancamento','Parcelamento':'parcelamento',
               'Valor':'valor','Titularidade':'titularidade','Tipo do cartão':'tipo_cartao'}
    rows_dict = []
    for ln in todos_novos:
        if isinstance(ln, dict):
            d = ln
        elif header_ref:
            d = {col_map.get(header_ref[i], header_ref[i].lower()): ln[i] for i in range(min(len(ln),len(header_ref)))}
        else:
            d = {'data': ln[0], 'lancamento': ln[1], 'parcelamento': ln[2],
                 'valor': ln[3], 'titularidade': ln[4], 'tipo_cartao': ln[5]}
        try: d['valor'] = float(str(d.get('valor',0)).replace(',','.'))
        except: d['valor'] = 0
        # remove chaves vazias
        d = {k:v for k,v in d.items() if k}
        rows_dict.append(d)

    supa_upsert(rows_dict)
    print(f'\nConcluído! {len(todos_novos)} novos lançamentos no Supabase.')

if __name__ == '__main__':
    main()
