#!/usr/bin/env python3
# importar_pix.py — extrai PIX enviados dos OFX (Nubank + Itaú) e sobe para Supabase

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

CONTAS_PROPRIAS = ['031.326.770-78','03132677078','0295997399','99739-9',
                   'Anael d','Anael D','anael d','ANAEL D']

def supa_upsert(rows, batch=100):
    for i in range(0, len(rows), batch):
        b = rows[i:i+batch]
        r = requests.post(
            f'{SUPA_URL}/rest/v1/pix?on_conflict=data,destinatario,valor',
            headers=SUPA_HEADERS, json=b, timeout=30
        )
        if r.status_code not in (200, 201):
            print(f'  ERRO {r.status_code}: {r.text[:150]}')
        print(f'  {min(i+batch, len(rows))}/{len(rows)}', flush=True)
        time.sleep(0.3)

def buscar_existentes():
    print('Buscando PIX existentes no Supabase...')
    existentes = set()
    offset = 0
    while True:
        r = requests.get(
            f'{SUPA_URL}/rest/v1/pix?select=data,destinatario,valor&limit=1000&offset={offset}',
            headers=SUPA_HEADERS, timeout=20
        )
        rows = r.json()
        if not rows: break
        for row in rows:
            existentes.add(f"{row['data']}|{row['destinatario']}|{row['valor']}")
        if len(rows) < 1000: break
        offset += 1000
    print(f'  {len(existentes)} registros já existentes')
    return existentes

def parse_data(dt_str):
    # 20260102000000[-3:BRT] ou 20260106100000[-03:EST]
    dt_str = dt_str.strip()[:8]
    try:
        d = datetime.strptime(dt_str, '%Y%m%d')
        return d.strftime('%d/%m/%Y')
    except:
        return dt_str

def parse_ofx(path):
    # tenta UTF-8 primeiro (Nubank), fallback latin-1 (Itaú)
    for enc in ('utf-8', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc, errors='strict') as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
    else:
        with open(path, 'r', encoding='latin-1', errors='replace') as f:
            content = f.read()

    nome = path.split('/')[-1].upper()
    banco = 'Nubank' if nome.startswith('NU_') else 'Itaú'

    transacoes = []
    blocos = re.findall(r'<STMTTRN>(.*?)</STMTTRN>', content, re.DOTALL)

    for bloco in blocos:
        def get(tag):
            m = re.search(rf'<{tag}>(.*?)(?:</{tag}>|[\r\n])', bloco, re.IGNORECASE)
            return m.group(1).strip() if m else ''

        tipo    = get('TRNTYPE')
        dt      = get('DTPOSTED')
        valor   = get('TRNAMT')
        memo    = get('MEMO')

        # só débitos (PIX enviados)
        try:
            v = float(valor)
        except:
            continue
        if v >= 0:
            continue

        # filtra transferências entre contas próprias
        eh_propria = any(c in memo for c in CONTAS_PROPRIAS)
        if eh_propria:
            continue

        # filtra pagamento de fatura e outros não-PIX
        memo_lower = memo.lower()
        is_pix = ('pix' in memo_lower or 'transferência' in memo_lower or 'transferencia' in memo_lower)
        if not is_pix:
            continue

        # extrai destinatário e documento do MEMO
        # Nubank: "Transferência enviada pelo Pix - NOME - CPF - BANCO Agência: X Conta: Y"
        # Itaú:   "PIX TRANSF NOME DD MM"
        destinatario = ''
        doc          = ''
        banco_dest   = ''

        # padrão Nubank
        m_nu = re.match(r'(?:Transfer\xeancia enviada pelo Pix|Pix enviado)\s*[–\-]\s*([^–\-]+)\s*[–\-]\s*([^\s–\-]+)\s*[–\-]\s*(.+?)(?:Ag\xeancia|$)', memo, re.IGNORECASE)
        if m_nu:
            destinatario = m_nu.group(1).strip()
            doc          = m_nu.group(2).strip()
            banco_dest   = m_nu.group(3).strip().split('Agência')[0].strip()
        else:
            # padrão Itaú: "PIX TRANSF NOME DD MM"
            m_itau = re.match(r'PIX TRANSF\s+(.+?)(?:\d{2} \d{2})?$', memo, re.IGNORECASE)
            if m_itau:
                destinatario = m_itau.group(1).strip()
            else:
                destinatario = memo[:60]

        transacoes.append([
            parse_data(dt),
            banco,
            'PIX enviado',
            abs(v),
            destinatario,
            doc,
            banco_dest,
            memo[:100]
        ])

    return transacoes

def buscar_existentes():
    print('Buscando PIX existentes no Supabase...')
    existentes = set()
    offset = 0
    while True:
        r = requests.get(
            f'{SUPA_URL}/rest/v1/pix?select=data,destinatario,valor&limit=1000&offset={offset}',
            headers=SUPA_HEADERS, timeout=20
        )
        rows = r.json()
        if not rows: break
        for row in rows:
            existentes.add(f"{row['data']}|{row['destinatario']}|{row['valor']}")
        if len(rows) < 1000: break
        offset += 1000
    print(f'  {len(existentes)} registros já existentes')
    return existentes

def main():
    arquivos = sorted(glob.glob(f'{PASTA_PIX}/*.ofx') + glob.glob(f'{PASTA_PIX}/*.OFX'))
    if not arquivos:
        print('Nenhum arquivo OFX encontrado em', PASTA_PIX)
        return

    print(f'{len(arquivos)} arquivo(s) encontrado(s)\n')

    existentes = buscar_existentes()

    novos = []
    for path in arquivos:
        nome = path.split('/')[-1]
        print(f'Lendo {nome}...')
        try:
            trans = parse_ofx(path)
            n = 0
            for t in trans:
                chave = f"{t[0]}|{t[4]}|{t[3]}"
                if chave not in existentes:
                    novos.append(t)
                    existentes.add(chave)
                    n += 1
            print(f'  {len(trans)} PIX enviados, {n} novos')
        except Exception as e:
            print(f'  ERRO: {e}')

    if not novos:
        print('\nNenhum PIX novo. Supabase já está atualizado.')
        return

    CAMPOS = ['data','banco','tipo','valor','destinatario','doc','banco_dest','memo']
    rows_dict = [dict(zip(CAMPOS, t)) for t in novos]

    print(f'\nSubindo {len(novos)} PIX para Supabase...')
    supa_upsert(rows_dict)
    print(f'\nConcluído! {len(novos)} PIX no Supabase.')

if __name__ == '__main__':
    main()
