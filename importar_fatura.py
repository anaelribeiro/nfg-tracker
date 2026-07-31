#!/usr/bin/env python3
# importar_fatura.py — lê XLSX das faturas Itaú e sobe bruto na aba 'cartao' do Sheets

import glob, json, time, requests, openpyxl
from datetime import datetime

PASTA_FATURAS = 'faturas'
APPS_SCRIPT   = 'https://script.google.com/macros/s/AKfycbwpfWeHAm8_wBt-r6LVkCCXVTP3AyygtOTV1Dif7iIiJU712yGwV2_hybAwmJQzcgZ3-Q/exec'
ABA           = 'cartao'
HEADER_ROW    = 14  # linha onde ficam os cabeçalhos nos XLSX

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

COLUNAS_REMOVER = ['Nome', 'Número do cartão']

def ler_fatura(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    # linha 14 (índice 13) = cabeçalho
    header_raw = [str(c).strip() if c is not None else '' for c in rows[HEADER_ROW - 1]]
    # índices das colunas a manter
    keep = [i for i, h in enumerate(header_raw) if h not in COLUNAS_REMOVER]
    header = [header_raw[i] for i in keep]

    lancamentos = []
    for row in rows[HEADER_ROW:]:
        vals = list(row)
        if all(v is None for v in vals):
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

    # limpa a aba antes de subir
    print('Limpando aba cartao...')
    post_sheets({'aba': ABA, 'action': 'clear'})
    time.sleep(1)

    todos_lancamentos = []
    header_enviado = False

    for path in arquivos:
        nome = path.split('/')[-1]
        print(f'Lendo {nome}...')
        try:
            header, lancamentos = ler_fatura(path)
            if not header_enviado:
                post_sheets({'aba': ABA, 'action': 'header_aba', 'row': header})
                header_enviado = True
            todos_lancamentos.extend(lancamentos)
            print(f'  {len(lancamentos)} lançamentos')
        except Exception as e:
            print(f'  ERRO: {e}')

    # sobe em batches de 50
    print(f'\nSubindo {len(todos_lancamentos)} lançamentos para Sheets...')
    BATCH = 50
    for i in range(0, len(todos_lancamentos), BATCH):
        batch = todos_lancamentos[i:i+BATCH]
        ok = post_sheets({'aba': ABA, 'rows': batch})
        print(f'  Batch {i//BATCH + 1}: {"OK" if ok else "ERRO"}')
        time.sleep(0.3)

    print(f'\nConcluído! {len(todos_lancamentos)} lançamentos na aba "{ABA}".')

if __name__ == '__main__':
    main()
