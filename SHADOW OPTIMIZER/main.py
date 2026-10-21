"""Shadow: análise informativa com encerramento manual de aplicativos escolhidos."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import time

import psutil


IS_WINDOWS = platform.system() == "Windows"
BYTES_PER_GB = 1024 ** 3
BYTES_PER_MB = 1024 ** 2

# Processos essenciais do Windows/Linux que o Shadow nunca oferece para encerrar.
PROTECTED_PROCESS_NAMES = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "services.exe", "lsass.exe", "svchost.exe", "winlogon.exe",
    "explorer.exe", "dwm.exe", "fontdrvhost.exe", "systemd", "init",
    "kthreadd", "kernel",
}


def collect_hardware_info():
    """Identifica dados básicos; GPU fica indisponível quando não há uma fonte confiável."""
    cpu_name = platform.processor() or platform.uname().processor or "Não identificado"
    gpu_names = []

    if IS_WINDOWS:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if powershell:
            command = (
                "$cpu=(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name);"
                "$gpu=@(Get-CimInstance Win32_VideoController | ForEach-Object {$_.Name});"
                "[pscustomobject]@{cpu=$cpu;gpu=$gpu} | ConvertTo-Json -Compress"
            )
            try:
                result = subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=6,
                )
                if result.returncode == 0 and result.stdout.strip():
                    details = json.loads(result.stdout)
                    cpu_name = details.get("cpu") or cpu_name
                    names = details.get("gpu") or []
                    gpu_names = [names] if isinstance(names, str) else names
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass
    elif platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as cpuinfo:
                for line in cpuinfo:
                    key, separator, value = line.partition(":")
                    if separator and key.strip().lower() in {"model name", "hardware"}:
                        cpu_name = value.strip()
                        break
        except OSError:
            pass

        lspci = shutil.which("lspci")
        if lspci:
            try:
                result = subprocess.run(
                    [lspci, "-mm"], check=False, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=3,
                )
                for line in result.stdout.splitlines():
                    if any(category in line.lower() for category in ("vga compatible controller", "3d controller", "display controller")):
                        parts = line.split('"')
                        if len(parts) >= 6:
                            gpu_names.append(f"{parts[3]} {parts[5]}".strip())
            except (OSError, subprocess.TimeoutExpired):
                pass

    return {
        "cpu_name": cpu_name,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "architecture": platform.machine() or "Não identificada",
        "gpu_names": gpu_names,
        "gpu_available": bool(gpu_names),
    }


def collect_system_info():
    """Retorna o nome amigável do sistema sem confundir Windows 10 e 11."""
    system_name = platform.system()
    release = platform.release()
    version = platform.version()
    display_name = system_name

    if IS_WINDOWS:
        try:
            build = int(version.split(".")[-1])
        except (ValueError, IndexError):
            build = 0
        display_name = "Windows 11" if build >= 22000 else "Windows 10" if build else "Windows"
    elif system_name == "Linux":
        try:
            display_name = platform.freedesktop_os_release().get("PRETTY_NAME") or "Linux"
        except (AttributeError, OSError):
            display_name = "Linux"

    return {
        "name": system_name,
        "display_name": display_name,
        "release": release,
        "version": version,
        "is_windows": IS_WINDOWS,
    }


def scan_system(monitor_duration=5, progress_callback=None):
    """Executa uma leitura completa e devolve um relatório que pode ser reutilizado pela GUI."""
    if monitor_duration < 1:
        raise ValueError("A duração do monitoramento deve ser de pelo menos 1 segundo.")

    def report_progress(stage, status):
        if progress_callback is not None:
            try:
                progress_callback(stage, status)
            except Exception:
                # Uma falha visual não deve interromper uma medição do sistema.
                pass

    report_progress("Preparando leitura", "active")

    memory = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=1)
    report_progress("Preparando leitura", "complete")

    report_progress("Identificando sistema e hardware", "active")
    system = collect_system_info()
    hardware = collect_hardware_info()
    report_progress("Identificando sistema e hardware", "complete")

    report = {
        "system": system,
        "hardware": hardware,
        "cpu_percent": cpu,
        "memory": {
            "total_gb": memory.total / BYTES_PER_GB,
            "used_percent": memory.percent,
            "available_gb": memory.available / BYTES_PER_GB,
        },
    }
    print_report_header(report)

    report_progress("Analisando memória e processos", "active")
    diagnosis = diagnose_system(memory, cpu)
    top_ram = show_top_processes()
    top_cpu = show_top_cpu_processes()
    recommendations = recommend_actions(memory, cpu)
    report_progress("Analisando memória e processos", "complete")

    report_progress(f"Amostrando CPU e RAM por {monitor_duration} segundos", "active")
    monitoring = monitor_system(monitor_duration)
    report_progress(f"Amostrando CPU e RAM por {monitor_duration} segundos", "complete")

    report_progress("Consolidando o relatório", "active")
    report.update({
        "diagnosis": diagnosis,
        "top_ram_processes": top_ram,
        "top_cpu_processes": top_cpu,
        "recommendations": recommendations,
        "monitoring": monitoring,
    })
    report_progress("Consolidando o relatório", "complete")
    return report


def build_diagnostic_findings(report, overview=None):
    """Converte medições explícitas em achados com gravidade e sugestão segura."""
    overview = overview or {}
    monitoring = report.get("monitoring", {})
    findings = []

    cpu_average = monitoring.get("average_cpu", report.get("cpu_percent", 0))
    ram_average = monitoring.get("average_ram", report.get("memory", {}).get("used_percent", 0))
    available_gb = report.get("memory", {}).get("available_gb", 0)

    if cpu_average >= 85:
        findings.append({
            "severity": "ALTA",
            "title": "CPU muito ocupada durante a amostra",
            "evidence": f"Uso médio de CPU: {cpu_average:.1f}% nos últimos segundos medidos.",
            "suggestion": "Confira os maiores consumidores de CPU e feche apenas aplicativos que você reconhece, depois de salvar seu trabalho.",
        })
    elif cpu_average >= 70:
        findings.append({
            "severity": "MÉDIA",
            "title": "Uso elevado de CPU na amostra",
            "evidence": f"Uso médio de CPU: {cpu_average:.1f}% durante a análise.",
            "suggestion": "Veja se um programa está executando uma tarefa esperada; repita a análise se essa atividade passar.",
        })

    if ram_average >= 92 or (available_gb < 1 and ram_average >= 85):
        findings.append({
            "severity": "ALTA",
            "title": "Pouca memória disponível",
            "evidence": f"RAM média usada: {ram_average:.1f}%; disponível na leitura: {available_gb:.1f} GB.",
            "suggestion": "Revise os aplicativos que usam mais RAM e salve seu trabalho antes de fechar qualquer um.",
        })
    elif ram_average >= 82:
        findings.append({
            "severity": "MÉDIA",
            "title": "Memória RAM bastante ocupada",
            "evidence": f"RAM média usada: {ram_average:.1f}% durante a análise.",
            "suggestion": "Confira os maiores consumidores de memória e encerre somente aplicativos dispensáveis que você reconhece.",
        })

    for disk in overview.get("disks", []):
        used = disk.get("used_percent", 0)
        if used >= 97:
            severity = "ALTA"
        elif used >= 90:
            severity = "MÉDIA"
        else:
            continue
        findings.append({
            "severity": severity,
            "title": f"Pouco espaço livre em {disk.get('name', 'uma unidade')}",
            "evidence": f"{used:.0f}% usado; {disk.get('free_gb', 0):.1f} GB livres.",
            "suggestion": "Revise arquivos grandes e aplicativos que você não usa. Confira cada item antes de removê-lo.",
        })

    if not findings:
        findings.append({
            "severity": "INFO",
            "title": "Nenhuma pressão elevada identificada",
            "evidence": f"CPU média {cpu_average:.1f}% e RAM média {ram_average:.1f}% nesta amostra.",
            "suggestion": "O resultado é um retrato breve do uso atual. Repita a análise se o problema ocorrer em outro momento.",
        })

    top_cpu = (report.get("top_cpu_processes") or [None])[0]
    if top_cpu:
        findings.append({
            "severity": "INFO",
            "title": "Maior uso de CPU observado em um processo",
            "evidence": f"{top_cpu.get('name', 'Processo desconhecido')}: {top_cpu.get('cpu_percent', 0):.1f}% na amostra curta por processo.",
            "suggestion": "Confira a página Processos. Um pico isolado pode ser normal; investigue se continuar acontecendo quando o PC estiver lento.",
        })

    top_ram = (report.get("top_ram_processes") or [None])[0]
    total_ram_mb = report.get("memory", {}).get("total_gb", 0) * 1024
    if top_ram:
        share = top_ram.get("ram_mb", 0) / total_ram_mb * 100 if total_ram_mb else 0
        findings.append({
            "severity": "INFO",
            "title": "Maior consumidor de RAM observado",
            "evidence": f"{top_ram.get('name', 'Processo desconhecido')}: {top_ram.get('ram_mb', 0):.0f} MB ({share:.1f}% da RAM total).",
            "suggestion": "Veja se o aplicativo está sendo usado e se esse consumo é esperado. O Shadow não fecha processos automaticamente.",
        })

    startup = overview.get("startup", {})
    if startup.get("supported"):
        enabled_count = sum(1 for item in startup.get("items", []) if item.get("enabled"))
        findings.append({
            "severity": "INFO",
            "title": "Aplicativos configurados para iniciar com sua conta",
            "evidence": f"{enabled_count} item(ns) na lista de inicialização da conta atual.",
            "suggestion": "Revise a página Inicialização; desative somente aplicativos conhecidos que você não precisa abrir ao entrar no Windows.",
        })

    return findings


def print_report_header(report):
    """Mostra o resumo principal da leitura."""
    if not report["system"]["is_windows"]:
        print("Aviso: o sistema-alvo deste projeto é Windows 10/11.")
        print("O scanner está rodando em modo de desenvolvimento.")

    print("\n=== SHADOW PC OPTIMIZER ===")
    print(f"Sistema: {report['system']['display_name']} ({report['system']['version']})")
    hardware = report["hardware"]
    print(
        f"CPU: {hardware['cpu_name']} | "
        f"{hardware['physical_cores'] or '?'} núcleos / "
        f"{hardware['logical_cores'] or '?'} threads"
    )
    gpu_text = ", ".join(hardware["gpu_names"]) if hardware["gpu_names"] else "não identificada nesta leitura"
    print(f"GPU: {gpu_text}")
    print(f"CPU em uso: {report['cpu_percent']:.1f}%")
    print(f"RAM total: {report['memory']['total_gb']:.2f} GB")
    print(f"RAM em uso: {report['memory']['used_percent']:.1f}%")
    print(f"RAM disponível: {report['memory']['available_gb']:.2f} GB")


def monitor_system(duration=5):
    """Coleta amostras de CPU e RAM; retorna listas e estatísticas para uso futuro em gráficos."""
    if not isinstance(duration, int) or duration < 1:
        raise ValueError("duration deve ser um número inteiro maior que zero.")

    print(f"\n=== MONITORAMENTO ({duration} SEGUNDOS) ===")
    cpu_samples = []
    ram_samples = []

    for second in range(duration):
        cpu = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent
        cpu_samples.append(cpu)
        ram_samples.append(memory_percent)
        print(f"Segundo {second + 1}: CPU {cpu:.1f}% | RAM {memory_percent:.1f}%")

    summary = {
        "cpu_samples": cpu_samples,
        "ram_samples": ram_samples,
        "average_cpu": sum(cpu_samples) / len(cpu_samples),
        "peak_cpu": max(cpu_samples),
        "average_ram": sum(ram_samples) / len(ram_samples),
        "peak_ram": max(ram_samples),
    }

    print("\n=== RESUMO DO MONITORAMENTO ===")
    print(f"CPU média: {summary['average_cpu']:.1f}%")
    print(f"Pico de CPU: {summary['peak_cpu']:.1f}%")
    print(f"RAM média: {summary['average_ram']:.1f}%")
    print(f"Pico de RAM: {summary['peak_ram']:.1f}%")
    return summary


def diagnose_system(memory, cpu):
    """Classifica pressão de recursos com critérios simples e retorna os dados."""
    available_gb = memory.available / BYTES_PER_GB

    if available_gb < 1 and memory.percent >= 90:
        level = "ALTO"
        message = "Pouca memória disponível; investigue os aplicativos que consomem RAM."
    elif memory.percent >= 80 or cpu >= 85:
        level = "MÉDIO"
        message = "Recursos bastante ocupados; verifique quais programas estão trabalhando."
    else:
        level = "BAIXO"
        message = "Não foi detectada pressão elevada pelos critérios atuais."

    print("\n=== DIAGNÓSTICO ===")
    print(f"Nível {level}: {message}")
    if level == "BAIXO":
        print("Seu PC não precisa de uma otimização só por otimizar.")
    print("\nEste diagnóstico é preliminar e não mede o desempenho em jogos.")
    return {"level": level, "message": message}


def show_top_processes(limit=10):
    """Lista processos por memória residente (RAM) e devolve os dados coletados."""
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit deve ser um número inteiro maior que zero.")

    processes = []
    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = process.info
            memory_info = info["memory_info"]
            if memory_info:
                processes.append({
                    "pid": info["pid"],
                    "name": info["name"] or "Desconhecido",
                    "ram_mb": memory_info.rss / BYTES_PER_MB,
                    "create_time": process.create_time(),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    processes.sort(key=lambda item: item["ram_mb"], reverse=True)
    top_processes = processes[:limit]

    print("\n=== PROCESSOS COM MAIOR USO DE RAM ===")
    if top_processes:
        for process in top_processes:
            print(f"{process['name']} | PID: {process['pid']} | RAM: {process['ram_mb']:.1f} MB")
    else:
        print("Não foi possível obter informações de processos.")

    heavy_processes = [process for process in processes if process["ram_mb"] >= 500]
    print("\n=== PROCESSOS COM ALTO CONSUMO DE RAM (500 MB OU MAIS) ===")
    if heavy_processes:
        for process in heavy_processes:
            print(f"{process['name']} está usando {process['ram_mb']:.1f} MB de RAM.")
    else:
        print("Nenhum processo individual atingiu 500 MB.")
    return top_processes


def terminate_user_process(pid, expected_name, expected_create_time):
    """Encerra um processo selecionado, após validar que ainda é o mesmo processo.

    Nunca força o encerramento: se o aplicativo não responder ao pedido normal,
    o Shadow informa isso e deixa a decisão para a pessoa.
    """
    try:
        pid = int(pid)
        process = psutil.Process(pid)
        name = process.name() or "Desconhecido"

        if pid in (0, 1, os.getpid()):
            return {"success": False, "message": "Esse processo está protegido pelo Shadow."}
        if name.casefold() in PROTECTED_PROCESS_NAMES:
            return {"success": False, "message": "Esse processo essencial do sistema está protegido."}
        if name.casefold() != str(expected_name).casefold():
            return {"success": False, "message": "O processo mudou desde a análise. Atualize a leitura."}
        if abs(process.create_time() - float(expected_create_time)) > 0.01:
            return {"success": False, "message": "O PID foi reutilizado por outro processo. Atualize a leitura."}

        try:
            process_user = process.username()
            current_user = psutil.Process().username()
            if process_user.casefold() != current_user.casefold():
                return {"success": False, "message": "Por segurança, só é possível encerrar aplicativos da sua conta."}
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return {"success": False, "message": "Não foi possível confirmar o proprietário desse processo."}

        executable = process.exe()
        if IS_WINDOWS:
            windows_dir = os.environ.get("WINDIR", r"C:\Windows")
            try:
                if os.path.commonpath([os.path.abspath(executable), os.path.abspath(windows_dir)]).casefold() == os.path.abspath(windows_dir).casefold():
                    return {"success": False, "message": "Aplicativos do diretório do Windows estão protegidos."}
            except ValueError:
                pass

        if IS_WINDOWS:
            # WM_CLOSE pede que o aplicativo feche sua janela e salve/consulte
            # o usuário normalmente. Não usamos TerminateProcess como fallback.
            import ctypes

            user32 = ctypes.windll.user32
            windows = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def collect_windows(handle, _parameter):
                window_pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(handle, ctypes.byref(window_pid))
                if window_pid.value == pid:
                    windows.append(handle)
                return True

            callback = callback_type(collect_windows)
            user32.EnumWindows(callback, 0)
            if not windows:
                return {"success": False, "message": "Esse processo não tem uma janela que possa ser fechada com segurança. Ele não foi encerrado."}
            for handle in windows:
                user32.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE
        else:
            process.terminate()  # SIGTERM: pedido normal de encerramento no Linux.
        try:
            process.wait(timeout=3)
        except psutil.TimeoutExpired:
            return {"success": False, "message": "O aplicativo não respondeu ao pedido para fechar. Ele não foi forçado; feche-o pelo próprio aplicativo."}
        return {"success": True, "message": f"{name} foi encerrado."}
    except (ValueError, TypeError):
        return {"success": False, "message": "Identificação de processo inválida."}
    except psutil.NoSuchProcess:
        return {"success": False, "message": "Esse processo já foi fechado. Atualize a leitura."}
    except psutil.AccessDenied:
        return {"success": False, "message": "O sistema não permitiu encerrar esse processo."}
    except (OSError, psutil.Error):
        return {"success": False, "message": "Não foi possível encerrar esse processo."}


def show_top_cpu_processes(limit=10, sample_seconds=1):
    """Compara o uso de CPU dos processos durante uma amostra curta."""
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit deve ser um número inteiro maior que zero.")
    if sample_seconds <= 0:
        raise ValueError("sample_seconds deve ser maior que zero.")

    processes = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            process.cpu_percent(interval=None)  # A primeira leitura prepara a medição.
            processes.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    time.sleep(sample_seconds)
    cpu_processes = []
    for process in processes:
        try:
            cpu_processes.append({
                "pid": process.pid,
                "name": process.name() or "Desconhecido",
                "cpu_percent": process.cpu_percent(interval=None),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    cpu_processes.sort(key=lambda item: item["cpu_percent"], reverse=True)
    top_processes = cpu_processes[:limit]
    print("\n=== PROCESSOS COM MAIOR USO DE CPU ===")
    if top_processes:
        for process in top_processes:
            print(
                f"{process['name']} | PID: {process['pid']} | "
                f"CPU: {process['cpu_percent']:.1f}%"
            )
    else:
        print("Não foi possível obter informações de processos.")
    return top_processes


def recommend_actions(memory, cpu):
    """Gera sugestões informativas sem encerrar processos ou mudar o sistema."""
    recommendations = []
    if memory.available < BYTES_PER_GB and memory.percent >= 90:
        recommendations.append("A memória disponível está muito baixa; investigue os aplicativos que usam RAM.")
    elif memory.percent >= 80:
        recommendations.append("A RAM está bastante ocupada; confira os aplicativos em uso.")
    if cpu >= 85:
        recommendations.append("A CPU está bastante ocupada; confira tarefas pesadas em segundo plano.")
    if not recommendations:
        recommendations.append("Nenhuma pressão elevada foi identificada neste momento.")

    print("\n=== RECOMENDAÇÕES ===")
    for recommendation in recommendations:
        print(recommendation)
    print("\nO scanner não encerra processos automaticamente.")
    return recommendations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shadow PC Optimizer")
    parser.add_argument(
        "--console",
        action="store_true",
        help="executa o scanner no terminal em vez de abrir a janela",
    )
    parser.add_argument(
        "--monitor-seconds",
        type=int,
        default=5,
        help="duração do monitoramento do scanner em segundos (padrão: 5)",
    )
    arguments = parser.parse_args()

    if arguments.console:
        scan_system(monitor_duration=arguments.monitor_seconds)
    else:
        from app_webview import launch_gui

        launch_gui()
