# Shadow PC Optimizer

O Shadow usa Python para coletar os dados do computador e HTML/CSS/JavaScript para desenhar a interface. A análise começa somente depois do clique em **Analisar**.

Na lista de processos, a pessoa pode pedir para encerrar um aplicativo específico. O Shadow pede confirmação, valida que o processo ainda é o mesmo e não força o encerramento se ele não responder. Salve o trabalho antes: encerrar um aplicativo pode causar perda de dados. Nenhum processo é encerrado automaticamente.

O painel também mostra o espaço livre nas unidades e oferece monitoramento ao vivo de CPU, RAM, processos e atividade do disco. No Windows, inclui uma prévia de temporários com mais de sete dias na pasta TEMP da conta, uma lista reversível dos itens da chave de inicialização da conta atual e a consulta/seleção de planos de energia. Limpeza, inicialização e plano de energia exigem confirmação. Arquivos temporários em uso são ignorados. O Shadow não promete aumento de FPS.

Na página **Configurações**, o Shadow identifica o sistema e marca recursos disponíveis, limitados ou indisponíveis. O suporte da versão distribuída tem como alvo Windows 10/11; o Linux serve como ambiente de desenvolvimento. O início junto com o Windows é opcional e fica desligado por padrão. Erros ficam em um log local rotativo, que pode ser lido ou apagado na própria página; o Shadow não envia esse arquivo.

O histórico local de diagnósticos e ações fica em `%LOCALAPPDATA%\Shadow` no Windows ou em `~/.local/share/shadow` no Linux. O Shadow não cria ponto de restauração do Windows. A inicialização automática do próprio Shadow só pode ser configurada pelo executável compilado para Windows.

## Windows 10/11

### Para desenvolver

No PowerShell, abra a pasta do projeto e execute:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Se o Windows pedir o runtime do WebView, instale o Microsoft Edge WebView2 Runtime.

### Para gerar a versão para distribuir

Para compilar manualmente, use um computador Windows com Python 3. Abra o PowerShell na pasta do projeto e rode:

```powershell
.\build_windows.ps1
```

Será gerado um único arquivo em `dist\Shadow.exe`. O ambiente de compilação é recriado limpo e usa o Edge WebView2 do Windows, sem empacotar Qt ou GTK. O próprio script mostra o tamanho final em MB. O computador da pessoa não precisa de Python nem pip; precisa do Microsoft Edge WebView2 Runtime, que não é incluído para manter o download menor.

### Gerar pelo GitHub sem ter Windows

O fluxo `.github/workflows/build-windows.yml` compila o aplicativo em um runner Windows do GitHub Actions. Envie o projeto ao GitHub, abra a aba **Actions**, selecione **Build Shadow for Windows** e clique em **Run workflow**. Quando terminar, abra a execução e baixe o artefato **Shadow-Windows** na seção **Artifacts**. O arquivo baixado é um ZIP contendo `Shadow.exe`; o GitHub mantém o artefato por 14 dias.

O repositório precisa conter o código, `requirements.txt`, `requirements-build.txt`, `test_*.py`, `test_ui.cjs`, `build_windows.ps1`, esta pasta `.github` e a pasta `ui`. Não envie `.venv`, `dist` ou `build`; eles são excluídos pelo `.gitignore`.

## Linux de desenvolvimento

No VS Code, selecione o interpretador `/home/lcm_z/.venv/bin/python` para que o depurador use o ambiente em que o pywebview foi instalado.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

O arquivo `requirements.txt` escolhe o renderizador Qt do pywebview no Linux. Em sistemas Arch/CachyOS, instale primeiro o pacote de pip do sistema se `python -m pip` não estiver disponível.

Para usar o scanner no terminal:

```bash
python main.py --console
```


## Modo leve, sensores e preparação por jogo

- **Configurações → Modo leve e aparência:** intervalos de 1, 3 ou 5 segundos; modo leve usa pelo menos 3 segundos, reduz efeitos e remove algumas camadas decorativas. Efeitos completos seguem como padrão. A apresentação pode ser desligada. Preferências ficam em `settings.json` na pasta de dados do Shadow.
- **Consumo do próprio Shadow:** CPU do processo e descendentes normalizada pelo total de núcleos lógicos; a primeira leitura fica indisponível até haver intervalo medido. RAM é a soma RSS e pode contar páginas compartilhadas mais de uma vez. Não é uma promessa de consumo máximo.
- **Visão geral → Ler sensores:** GPU/VRAM/temperaturas com fonte e horário. Atualização de 5 segundos, ou 10 no modo leve; para ao ocultar a janela ou sair das páginas relevantes. O Performance Lab continua coletando durante a sessão, inclusive com a janela oculta, e usa a mesma cache de sensores. GPU no gráfico é o maior uso entre as placas com leitura. CPU/RAM seguem o intervalo escolhido; temperaturas e horário da GPU acompanham as amostras salvas.
- **Gaming Hub:** checklist e plano de energia salvos por jogo detectado. “Revisar e aplicar” mostra a troca e exige confirmação. A cópia do plano anterior é gravada antes de aplicar; **Restaurar plano anterior** funciona após reabrir o app. Se outro programa ou a pessoa trocar o plano depois, o Shadow preserva essa escolha. A restauração é manual. Perfis de qualidade/desempenho continuam sendo preferências; não alteram arquivos dos jogos.

### Fontes opcionais dos sensores

NVIDIA usa `nvidia-smi` já disponível com o driver. No Windows, AMD/Intel e temperaturas adicionais podem ser lidas pelo WMI do **LibreHardwareMonitor**, quando ele já estiver aberto e expondo sensores. O Shadow não instala esse programa ou drivers. No Linux usa sysfs e sensores disponibilizados ao psutil. Leituras ausentes aparecem como **indisponível**, nunca como zero. Não há limite térmico universal aplicado a todos os componentes.

Referências dos provedores: [NVIDIA](https://docs.nvidia.com/deploy/nvidia-smi/index.html), [AMDGPU no Linux](https://www.kernel.org/doc/html/latest/gpu/amdgpu/thermal.html), [WMI do LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/master/LibreHardwareMonitor.Windows.Forms/TestScripts/basicwmi.py).

### Verificações antes de distribuir

```bash
python -m unittest discover -p 'test_*.py' -v
node --check ui/app.js
node --test test_ui.cjs
```

Os testes simulam ações do Windows: falhas de backup, inicialização da conta, planos de energia, restauração, proteção de processos e encerramento da janela. A limpeza usa arquivos criados em uma pasta temporária dos testes. Eles não alteram o plano real nem o registro do computador. Testes de interface verificam funções e referências aos elementos, sem renderizar uma janela.

O GitHub Actions verifica JavaScript antes de compilar. O script Windows executa os testes Python e interrompe a compilação em caso de falha. As dependências diretas e o PyInstaller estão fixados; dependências transitivas ainda são resolvidas pelo pip. O ajuste de encerramento Qt foi escrito para pywebview 6.2.1: reveja os testes ao atualizar essa versão.

Antes de publicar uma versão, valide também a janela, sensores e restauração em um Windows 10/11 real. Os testes simulados no Linux não substituem essa validação. Não há geração de frames no Shadow.
