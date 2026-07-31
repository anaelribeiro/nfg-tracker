#!/usr/bin/env python3
# importar_fatura.py — lê XLSX das faturas Itaú e sobe diferencial na aba 'cartao' do Sheets

import glob, time, requests, openpyxl
from datetime import datetime

PASTA_FATURAS   = 'faturas'
APPS_SCRIPT     = 'https://script.google.com/macros/s/AKfycbwpfWeHAm8_wBt-r6LVkCCXVTP3AyygtOTV1Dif7iIiJU712yGwV2_hybAwmJQzcgZ3-Q/exec'
URL_CARTAO_CSV  = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vSa-dNrsETRbxEi0I6GIoFc6J6Hd2Tpm7w1Yo4kORWwyIauS4kcWDX20wxpkA5mfRTQHvW9fg-WFN72/pub?gid=431304116&single=true&output=csv'
ABA             = 'cartao'
HEADER_ROW      = 14
COLUNAS_REMOVER = ['Nome', 'Número do cartão']

def post_sheets(payload, tentativas=3):
    for i in range(tentativas):
        try:
            r = requests.post(APPS_SCRIPT, json=payload, timeout=30)
            if r.status_code == 200:
                return True
            print(f'  HTTP {r.status_code}, tentativa {i+1}')
        except Exception as e:
            print(f'  Erro: {e}, tentativa {i+1}')
        time.sleep(2)
    return False

def chave_lancamento(linha, header):
    """Chave única: data + lançamento + valor"""
    idx = {h: i for i, h in enumerate(header)}
    data  = linha[idx.get('Data', 0)] if 'Data' in idx else ''
    desc  = linha[idx.get('Lançamento', 1)] if 'Lançamento' in idx else ''
    valor = linha[idx.get('Valor', 3)] if 'Valor' in idx else ''
    return f'{data}|{desc}|{valor}'

def buscar_existentes():
    """Lê a aba cartao publicada e retorna set de chaves já existentes."""
    print('Buscando lançamentos existentes no Sheets...')
    try:
        r = requests.get(URL_CARTAO_CSV, timeout=20, allow_redirects=True)
        linhas = r.text.strip().split('\n')
        if len(linhas) < 2:
            return set(), []
        import csv, io
        reader = csv.reader(io.StringIO(r.text))
        rows = list(reader)
        header = [h.strip() for h in rows[0]]
        existentes = set()
        for row in rows[1:]:
            if len(row) >= len(header):
                ln = [v.strip() for v in row]
                existentes.add(chave_lancamento(ln, header))
        print(f'  {len(existentes)} lançamentos já existentes')
        return existentes, header
    except Exception as e:
        print(f'  Erro ao buscar existentes: {e}')
        return set(), []

def ler_fatura(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    header_raw = [str(c).strip() if c is not None else '' for c in rows[HEADER_ROW - 1]]
    keep = [i for i, h in enumerate(header_raw) if h not in COLUNAS_REMOVER]
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

def main():
    arquivos = sorted(glob.glob(f'{PASTA_FATURAS}/fatura*.xlsx'))
    if not arquivos:
        print('Nenhum arquivo encontrado em', PASTA_FATURAS)
        return

    print(f'{len(arquivos)} arquivo(s) encontrado(s)\n')

    existentes, header_sheets = buscar_existentes()
    aba_vazia = len(existentes) == 0

    todos_novos = []
    header_local = None

    for path in arquivos:
        nome = path.split('/')[-1]
        print(f'Lendo {nome}...')
        try:
            header, lancamentos = ler_fatura(path)
            if header_local is None:
                header_local = header

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
        print('\nNenhum lançamento novo. Sheets já está atualizado.')
        return

    # sobe header só se aba estava vazia
    if aba_vazia and header_local:
        post_sheets({'aba': ABA, 'action': 'header_aba', 'row': header_local})
        time.sleep(0.5)

    print(f'\nSubindo {len(todos_novos)} novos lançamentos...')
    BATCH = 50
    for i in range(0, len(todos_novos), BATCH):
        batch = todos_novos[i:i+BATCH]
        ok = post_sheets({'aba': ABA, 'rows': batch})
        print(f'  Batch {i//BATCH + 1}: {"OK" if ok else "ERRO"}')
        time.sleep(0.3)

    print(f'\nConcluído! {len(todos_novos)} novos lançamentos na aba "{ABA}".')

if __name__ == '__main__':
    main()
