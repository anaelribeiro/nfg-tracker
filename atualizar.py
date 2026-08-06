#!/usr/bin/env python3
"""
atualizar.py — Script unificado NFG Tracker
Detecta automaticamente os arquivos nas pastas faturas/ e pix/
e executa os importadores corretos + atualiza as notas NFG.
"""

import os, glob, sys, subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
PASTA_FATURAS = BASE_DIR / 'faturas'
PASTA_PIX = BASE_DIR / 'pix'
VENV_PYTHON = BASE_DIR / 'venv' / 'bin' / 'python3'
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

def detectar_tipo_ofx(path):
    """Detecta o tipo de OFX pelo nome e conteúdo."""
    nome = Path(path).name.upper()

    # pelo nome
    if nome.startswith('NUBANK_'):
        return 'cartao_nubank'
    if nome.startswith('NU_') and 'AGO' in nome or nome.startswith('NU_'):
        return 'pix_nubank'
    if 'EXTRATO CONTA CORRENTE' in nome or nome.startswith('EXTRATO'):
        return 'pix_itau'

    # pelo conteúdo se nome ambíguo
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read(2000)
        if 'CREDITCARDMSGSRSV1' in content:
            return 'cartao_nubank'
        if 'STMTRS' in content:
            return 'pix_nubank' if 'NU' in nome else 'pix_itau'
    except:
        pass
    return 'desconhecido'

def listar_arquivos():
    """Lista todos os arquivos e detecta seus tipos."""
    arquivos = []

    # XLSX na pasta faturas = cartão Itaú
    for f in sorted(glob.glob(str(PASTA_FATURAS / '*.xlsx'))):
        arquivos.append({'path': f, 'tipo': 'cartao_itau', 'nome': Path(f).name})

    # OFX na pasta faturas = cartão Nubank
    for f in sorted(glob.glob(str(PASTA_FATURAS / '*.ofx'))):
        arquivos.append({'path': f, 'tipo': 'cartao_nubank', 'nome': Path(f).name})

    # OFX na pasta pix
    for f in sorted(glob.glob(str(PASTA_PIX / '*.ofx')) + glob.glob(str(PASTA_PIX / '*.OFX'))):
        tipo = detectar_tipo_ofx(f)
        arquivos.append({'path': f, 'tipo': tipo, 'nome': Path(f).name})

    return arquivos

def mostrar_plano(arquivos):
    """Mostra o que vai ser importado e pede confirmação."""
    grupos = {
        'cartao_itau': [],
        'cartao_nubank': [],
        'pix_itau': [],
        'pix_nubank': [],
        'desconhecido': [],
    }
    for a in arquivos:
        grupos[a['tipo']].append(a['nome'])

    print('\n' + '='*55)
    print('NFG Tracker — Importação Unificada')
    print('='*55)

    labels = {
        'cartao_itau':    '💳 Cartão Itaú      (XLSX)',
        'cartao_nubank':  '💜 Cartão Nubank    (OFX)',
        'pix_itau':       '🧡 Conta corrente Itaú (OFX)',
        'pix_nubank':     '💚 Conta corrente Nubank (OFX)',
        'desconhecido':   '❓ Tipo desconhecido',
    }

    total = 0
    for tipo, nomes in grupos.items():
        if nomes:
            print(f'\n{labels[tipo]}:')
            for n in nomes:
                print(f'  • {n}')
            total += len(nomes)

    if not total:
        print('\nNenhum arquivo encontrado nas pastas faturas/ e pix/')
        return False

    if grupos['desconhecido']:
        print(f'\n⚠️  {len(grupos["desconhecido"])} arquivo(s) com tipo desconhecido serão ignorados.')

    print(f'\nTotal: {total} arquivo(s) para processar')
    print('\nDeseja importar agora? Após isso, o script vai buscar novas notas NFG (requer login).')
    resp = input('\n[S/n] ').strip().lower()
    return resp in ('', 's', 'sim', 'y', 'yes')

def rodar_script(nome_script, descricao):
    """Roda um script Python e exibe o output em tempo real."""
    script = BASE_DIR / nome_script
    if not script.exists():
        print(f'  ⚠️  Script {nome_script} não encontrado, pulando.')
        return True
    print(f'\n{"─"*55}')
    print(f'▶ {descricao}')
    print(f'{"─"*55}')
    result = subprocess.run([PYTHON, str(script)], cwd=str(BASE_DIR))
    return result.returncode == 0

def main():
    os.chdir(BASE_DIR)

    arquivos = listar_arquivos()

    if not mostrar_plano(arquivos):
        print('\nCancelado.')
        return

    # determina quais scripts rodar
    tipos = {a['tipo'] for a in arquivos}
    scripts_rodar = []

    if 'cartao_itau' in tipos or 'cartao_nubank' in tipos:
        scripts_rodar.append(('importar_fatura.py', 'Importando faturas de cartão (Itaú + Nubank)'))

    if 'pix_itau' in tipos or 'pix_nubank' in tipos:
        scripts_rodar.append(('importar_pix.py', 'Importando PIX enviados (Itaú + Nubank)'))
        scripts_rodar.append(('importar_entradas.py', 'Importando entradas (salário + PIX recebidos)'))

    # roda os importadores
    erros = []
    for script, descricao in scripts_rodar:
        ok = rodar_script(script, descricao)
        if not ok:
            erros.append(script)

    # busca novas notas NFG
    print(f'\n{"─"*55}')
    print('▶ Buscando novas notas NFG (requer login no GOV.BR)')
    print(f'{"─"*55}')
    result = subprocess.run([PYTHON, str(BASE_DIR / 'atualizar_v2.py')], cwd=str(BASE_DIR))
    if result.returncode != 0:
        erros.append('atualizar_v2.py')

    # resumo final
    print(f'\n{"="*55}')
    if erros:
        print(f'⚠️  Concluído com erros em: {", ".join(erros)}')
    else:
        print('✅ Todos os dados atualizados com sucesso!')
    print(f'{"="*55}\n')

if __name__ == '__main__':
    main()
