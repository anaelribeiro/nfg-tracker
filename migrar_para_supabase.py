#!/usr/bin/env python3
# migrar_para_supabase.py — migra dados do Google Sheets para o Supabase

import json, requests, csv, io, time

with open('config_privado.json') as f:
    cfg = json.load(f)

SUPA_URL    = cfg['supabase_url']
SUPA_SECRET = cfg['supabase_secret']
SHEET_ID    = '1Z69HQfCHm_wW3aaP9mMyMa4zDNhqPbJd5NaIX9i3b-c'

HEADERS = {
    'apikey': SUPA_SECRET,
    'Authorization': f'Bearer {SUPA_SECRET}',
    'Content-Type': 'application/json',
    'Prefer': 'resolution=ignore-duplicates'
}

CONFLICT_COLS = {
    'itens': 'chave,codigo',
    'filiais': 'cnpj',
    'cartao': 'data,lancamento,valor',
    'pix': 'data,destinatario,valor'
}

def supa_upsert(tabela, rows, batch=100):
    total = 0
    conflict = CONFLICT_COLS.get(tabela,'')
    for i in range(0, len(rows), batch):
        batch_rows = rows[i:i+batch]
        url = f'{SUPA_URL}/rest/v1/{tabela}'
        if conflict:
            url += f'?on_conflict={conflict}'
        r = requests.post(
            url,
            headers={**HEADERS, 'Prefer': 'resolution=ignore-duplicates,return=minimal'},
            json=batch_rows,
            timeout=30
        )
        if r.status_code in (200, 201):
            total += len(batch_rows)
            print(f'  {tabela}: {total}/{len(rows)} OK')
        else:
            print(f'  ERRO {r.status_code}: {r.text[:150]}')
        time.sleep(0.3)
    return total

def fetch_csv(url):
    r = requests.get(url, timeout=30, allow_redirects=True)
    r.encoding = 'utf-8'
    reader = csv.DictReader(io.StringIO(r.text))
    return list(reader)

def parse_num(v):
    if not v: return None
    try: return float(v.replace(',','.'))
    except: return None

# ── itens ─────────────────────────────────────────────────────────
print('\n=== Migrando itens ===')
url_itens = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&sheet=itens'
rows_itens = fetch_csv(url_itens)
print(f'  {len(rows_itens)} linhas lidas do Sheets')

itens = []
for r in rows_itens:
    itens.append({
        'chave': r.get('chave',''),
        'numero': r.get('numero',''),
        'serie': r.get('serie',''),
        'emissao': r.get('emissao',''),
        'hora': r.get('hora',''),
        'tipo_nota': r.get('tipo_nota',''),
        'cnpj_emitente': r.get('cnpj_emitente',''),
        'loja': r.get('loja',''),
        'municipio': r.get('municipio',''),
        'valor_total_nota': parse_num(r.get('valor_total_nota','')),
        'valor_desconto': parse_num(r.get('valor_desconto','')),
        'forma_pagamento': r.get('forma_pagamento',''),
        'codigo': r.get('codigo',''),
        'descricao': r.get('descricao',''),
        'ncm': r.get('ncm',''),
        'quantidade': parse_num(r.get('quantidade','')),
        'unidade': r.get('unidade',''),
        'valor_unit': parse_num(r.get('valor_unit','')),
        'valor_total_item': parse_num(r.get('valor_total_item',''))
    })
supa_upsert('itens', itens)

# ── filiais ────────────────────────────────────────────────────────
print('\n=== Migrando filiais ===')
url_filiais = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vSa-dNrsETRbxEi0I6GIoFc6J6Hd2Tpm7w1Yo4kORWwyIauS4kcWDX20wxpkA5mfRTQHvW9fg-WFN72/pub?gid=1900593584&single=true&output=csv'
rows_filiais = fetch_csv(url_filiais)
print(f'  {len(rows_filiais)} linhas lidas do Sheets')

filiais = [{'cnpj': r.get('cnpj',''), 'nome': r.get('nome',''), 'fantasia': r.get('fantasia',''),
             'logradouro': r.get('logradouro',''), 'numero': r.get('numero',''),
             'bairro': r.get('bairro',''), 'municipio': r.get('municipio',''), 'uf': r.get('uf','')}
           for r in rows_filiais if r.get('cnpj','')]
supa_upsert('filiais', filiais)

# ── cartao ─────────────────────────────────────────────────────────
print('\n=== Migrando cartao ===')
url_cartao = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vSa-dNrsETRbxEi0I6GIoFc6J6Hd2Tpm7w1Yo4kORWwyIauS4kcWDX20wxpkA5mfRTQHvW9fg-WFN72/pub?gid=431304116&single=true&output=csv'
r_cartao = requests.get(url_cartao, timeout=30, allow_redirects=True)
r_cartao.encoding = 'latin-1'
rows_cartao = list(csv.DictReader(io.StringIO(r_cartao.text)))
print(f'  {len(rows_cartao)} linhas lidas do Sheets')

import re as _re
def data_ok(d): return bool(_re.match(r'^\d{2}/\d{2}/\d{4}$', (d or '').strip()))

cartao = []
for r in rows_cartao:
    data = r.get('Data','').strip()
    lanc = r.get('LanÃ§amento', r.get('Lançamento','')).strip()
    val  = parse_num(r.get('Valor',''))
    if not data_ok(data) or not val or val <= 0 or 'Pagamento' in lanc:
        continue
    cartao.append({
        'data': data, 'lancamento': lanc,
        'parcelamento': r.get('Parcelamento','').strip(),
        'valor': val,
        'titularidade': r.get('Titularidade','').strip(),
        'tipo_cartao': r.get('Tipo do cart\xe3o', r.get('Tipo do cartão','')).strip()
    })
supa_upsert('cartao', cartao)

# ── pix ────────────────────────────────────────────────────────────
print('\n=== Migrando pix (dos OFX locais) ===')
import glob, re

PASTA_PIX = 'pix'
CONTAS_PROPRIAS = ['031.326.770-78','03132677078','0295997399','99739-9']

def parse_data_ofx(dt_str):
    dt_str = dt_str.strip()[:8]
    try:
        from datetime import datetime
        return datetime.strptime(dt_str, '%Y%m%d').strftime('%d/%m/%Y')
    except: return dt_str

pix_rows = []
for path in sorted(glob.glob(f'{PASTA_PIX}/*.ofx')):
    nome = path.split('/')[-1].upper()
    banco = 'Nubank' if nome.startswith('NU_') else 'Itaú'
    with open(path, 'r', encoding='latin-1', errors='replace') as f:
        content = f.read()
    for bloco in re.findall(r'<STMTTRN>(.*?)</STMTTRN>', content, re.DOTALL):
        def get(tag):
            m = re.search(rf'<{tag}>(.*?)(?:</{tag}>|[\r\n])', bloco, re.IGNORECASE)
            return m.group(1).strip() if m else ''
        try: v = float(get('TRNAMT'))
        except: continue
        if v >= 0: continue
        memo = get('MEMO')
        if any(c in memo for c in CONTAS_PROPRIAS): continue
        ml = memo.lower()
        if not ('pix' in ml or 'transfer' in ml): continue
        dest, doc, banco_dest = '', '', ''
        m_nu = re.match(r'(?:Transfer\xeancia enviada pelo Pix|Pix enviado)\s*[–\-]\s*([^–\-]+)\s*[–\-]\s*([^\s–\-]+)\s*[–\-]\s*(.+?)(?:Ag\xeancia|$)', memo, re.IGNORECASE)
        if m_nu:
            dest = m_nu.group(1).strip()
            doc  = m_nu.group(2).strip()
            banco_dest = m_nu.group(3).strip().split('Agência')[0].strip()
        else:
            m_i = re.match(r'PIX TRANSF\s+(.+?)(?:\d{2} \d{2})?$', memo, re.IGNORECASE)
            dest = m_i.group(1).strip() if m_i else memo[:60]
        pix_rows.append({
            'data': parse_data_ofx(get('DTPOSTED')),
            'banco': banco, 'tipo': 'PIX enviado',
            'valor': abs(v), 'destinatario': dest,
            'doc': doc, 'banco_dest': banco_dest,
            'memo': memo[:200]
        })

print(f'  {len(pix_rows)} PIX encontrados nos OFX')
supa_upsert('pix', pix_rows)

print('\n✓ Migração concluída!')
