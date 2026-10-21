# 🌑 Shadow PC Optimizer

**Entenda o desempenho do seu PC e escolha o que melhorar.**

O Shadow é uma ferramenta para Windows que reúne diagnóstico, monitoramento e ajustes em uma interface com identidade violeta, gráficos e animações.

Sem promessas milagrosas: os resultados dependem do hardware, dos programas abertos e das condições do computador.

## ✨ Funcionalidades

### Dashboard e diagnóstico

- Monitoramento de CPU, memória, disco e processos.
- Identificação de hardware e sistema operacional.
- Pontuação explicável baseada nas leituras da análise — não representa FPS nem a potência do hardware.
- GPU e temperaturas quando houver sensores compatíveis.
- Recomendações para possíveis problemas de desempenho.

### Limpeza e ajustes

- Prévia e seleção de arquivos temporários antigos da pasta TEMP da conta.
- Gerenciamento dos programas da chave de inicialização da conta no Windows.
- Seleção dos planos de energia disponíveis.
- Pedido de fechamento de aplicativos selecionados, com confirmação e proteção de processos essenciais.

### Gaming Hub

- Detecção de jogos em bibliotecas compatíveis, como Steam e Epic Games.
- Preferências e checklist por jogo.
- Preparação com plano de energia escolhido pelo usuário.
- Cópia do plano anterior e restauração manual, inclusive após reabrir o Shadow.

### Performance Lab

- Coleta de CPU, RAM e GPU disponível durante uma sessão.
- Importação de capturas CSV compatíveis para consultar FPS e frametimes.
- Comparação e histórico de resultados.

As diferenças entre medições não provam, por si só, que um ajuste causou uma melhora.

### Network Lab

- Informações sobre adaptadores e conexão.
- Testes de latência e perda de pacotes.
- Diagnóstico básico de conectividade.

O Shadow não garante redução de ping: servidor, rota e qualidade da conexão também influenciam.

### Personalização e histórico

- Modo leve com menor frequência de atualização.
- Controle dos efeitos visuais e da apresentação inicial.
- Leitura do consumo do próprio Shadow.
- Histórico de diagnósticos e ajustes.
- Restauração das ações compatíveis.
- Logs de erros armazenados localmente.

## 🖥️ Compatibilidade

| Sistema | Situação |
|---|---|
| Windows 10 e 11 | Sistemas-alvo do projeto |
| Linux | Modo de desenvolvimento, com recursos limitados |

A disponibilidade de sensores depende do hardware, dos drivers e das permissões. Leituras ausentes aparecem como **indisponíveis**, não como zero.

NVIDIA pode ser consultada por `nvidia-smi`. No Windows, sensores adicionais podem ser obtidos pelo LibreHardwareMonitor quando estiver aberto e disponibilizando WMI. No Linux, são usados sensores expostos pelo sistema.

## 📦 Como executar

1. Baixe o pacote **Shadow-Windows** disponibilizado pelo projeto.
2. Extraia o arquivo ZIP.
3. Execute **Shadow.exe**.
4. Clique em **Analisar sistema** para iniciar o diagnóstico.

A versão compilada não exige Python nem pip. O Windows precisa ter o **Microsoft Edge WebView2 Runtime** instalado.

## 🛠️ Executar pelo código

Requer Python e as dependências do projeto.

### Windows — PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

### Linux — desenvolvimento

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Para executar o scanner no terminal:

```bash
python main.py --console
```

## 🏗️ Gerar o executável

Em um computador Windows, abra o PowerShell na pasta do projeto:

```powershell
.\build_windows.ps1
```

O script instala as dependências de compilação, executa os testes Python e gera:

```text
dist/Shadow.exe
```

Também é possível compilar pelo **GitHub Actions**:

1. Abra **Actions → Build Shadow for Windows**.
2. Clique em **Run workflow**.
3. Aguarde a conclusão.
4. Abra a execução e baixe **Shadow-Windows** em **Artifacts**.

## 🧪 Testes

```bash
python -m unittest discover -p "test_*.py" -v
node --check ui/app.js
node --test test_ui.cjs
```

Os testes usam simulações para as ações do Windows e arquivos temporários próprios para verificar a limpeza. A validação em um Windows real continua necessária antes de distribuir uma versão.

## 🔒 Cuidados e privacidade

- Nenhum processo é encerrado automaticamente.
- Alterações exigem ação e confirmação do usuário.
- Salve seu trabalho antes de pedir o fechamento de um aplicativo.
- A limpeza de arquivos não pode ser desfeita pelo Shadow.
- Somente ajustes compatíveis oferecem restauração.
- O Shadow não cria pontos de restauração do Windows.
- Históricos e logs ficam armazenados localmente. Testes de rede enviam tráfego ao destino consultado.

## ⚠️ Limitações

O Shadow não substitui upgrades de hardware, manutenção física ou reparos no sistema. Não garante aumento de FPS, redução de ping ou solução para todos os problemas de desempenho.

O projeto está em desenvolvimento. Ao relatar um problema, informe a versão do Windows, o que estava fazendo e a mensagem de erro, removendo dados pessoais dos registros.
