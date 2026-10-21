"""Leituras de conectividade sem alterar adaptadores, DNS ou roteador."""

import concurrent.futures
import ipaddress
import os
import platform
import re
import shutil
import subprocess

import psutil


PROBE_COUNT = 4
HOSTNAME_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_target(target):
    """Aceita somente um endereço IP ou nome DNS simples; argumentos nunca passam por shell."""
    value = str(target or "").strip().rstrip(".")
    if not value or len(value) > 253:
        return None
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    labels = value.split(".")
    if len(labels) < 2 or any(not HOSTNAME_LABEL.fullmatch(label) for label in labels):
        return None
    return value


def _default_gateway():
    if os.name == "nt":
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            return None
        command = (
            "Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' "
            "-ErrorAction SilentlyContinue | Sort-Object RouteMetric | "
            "Select-Object -First 1 -ExpandProperty NextHop"
        )
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=4, check=False,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}),
            )
            for line in result.stdout.splitlines():
                candidate = line.strip()
                try:
                    if ipaddress.ip_address(candidate).version == 4:
                        return candidate
                except ValueError:
                    continue
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None

    ip = shutil.which("ip")
    if ip:
        try:
            result = subprocess.run([ip, "-4", "route", "show", "default"],
                                    capture_output=True, text=True, timeout=2, check=False)
            match = re.search(r"\bvia\s+(\S+)", result.stdout)
            if match:
                return match.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Fallback do Linux sem depender do pacote iproute2.
    if platform.system() == "Linux":
        try:
            with open("/proc/net/route", encoding="ascii") as routes:
                next(routes, None)
                for line in routes:
                    fields = line.split()
                    if len(fields) > 2 and fields[1] == "00000000":
                        gateway = int(fields[2], 16)
                        return ".".join(str((gateway >> (8 * index)) & 255) for index in range(4))
        except (OSError, ValueError):
            pass
    return None


def network_overview():
    """Lista os adaptadores, estado e IPs locais sem expor endereços MAC."""
    stats = psutil.net_if_stats()
    addresses = psutil.net_if_addrs()
    adapters = []
    for name, interface_stats in stats.items():
        ips = []
        for address in addresses.get(name, []):
            family_name = getattr(address.family, "name", str(address.family))
            if family_name not in {"AF_INET", "AF_INET6"}:
                continue
            value = address.address.split("%", 1)[0]
            if value and value not in ips:
                ips.append(value)
        is_loopback = name.casefold() in {"lo", "loopback", "loopback pseudo-interface 1"}
        if not is_loopback and ips:
            try:
                is_loopback = all(ipaddress.ip_address(address).is_loopback for address in ips)
            except ValueError:
                pass
        if is_loopback:
            continue
        adapters.append({
            "name": name,
            "is_up": bool(interface_stats.isup),
            "speed_mbps": interface_stats.speed or None,
            "mtu": interface_stats.mtu or None,
            "addresses": ips,
        })
    adapters.sort(key=lambda item: (not item["is_up"], item["name"].casefold()))
    gateway = _default_gateway()
    return {
        "adapters": adapters,
        "gateway": gateway,
        "active_adapters": sum(1 for adapter in adapters if adapter["is_up"]),
        "message": "Adaptadores e rota padrão lidos localmente." if adapters else "Nenhum adaptador foi listado pelo sistema.",
    }


def _parse_rtt(output):
    # Inglês e português do Windows/Linux. `time<1ms` indica resolução menor que 1 ms,
    # não um valor numérico exato, portanto essa amostra não entra na média.
    match = re.search(r"(?:time|tempo)\s*([=<])\s*([\d.,]+)\s*ms", output, re.IGNORECASE)
    if not match:
        return None, False
    value = match.group(2).replace(",", ".")
    try:
        latency = float(value)
    except ValueError:
        return None, False
    return (None, True) if match.group(1) == "<" else (latency, False)


def _ping_once(host):
    ping = shutil.which("ping")
    if not ping:
        return {"success": False, "latency_ms": None, "error": "O comando ping não foi encontrado."}
    if os.name == "nt":
        command = [ping, "-n", "1", "-w", "1200", host]
    else:
        command = [ping, "-c", "1", "-W", "1", host]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=3, check=False,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}),
        )
        output = f"{result.stdout}\n{result.stderr}"
        succeeded = result.returncode == 0
        latency, below_resolution = _parse_rtt(output)
        error = None
        if not succeeded and re.search(r"could not find host|name or service not known|temporary failure in name resolution|unknown host|não foi possível localizar o host", output, re.IGNORECASE):
            error = "O nome do host não foi resolvido; pode haver um problema de DNS."
        return {"success": succeeded, "latency_ms": latency, "below_resolution": below_resolution, "error": error}
    except subprocess.TimeoutExpired:
        return {"success": False, "latency_ms": None, "error": "O teste excedeu o tempo de espera."}
    except OSError as error:
        return {"success": False, "latency_ms": None, "error": str(error)}


def test_host(host, probe_count=PROBE_COUNT):
    """Envia algumas sondas ICMP e resume somente respostas realmente medidas."""
    target = validate_target(host)
    if target is None:
        return {"success": False, "message": "Informe um endereço IP ou nome de host válido."}
    results = [_ping_once(target) for _ in range(max(1, min(int(probe_count), 8)))]
    received = sum(1 for result in results if result["success"])
    latencies = [result["latency_ms"] for result in results if result["latency_ms"] is not None]
    below_resolution = sum(1 for result in results if result.get("below_resolution"))
    errors = [result["error"] for result in results if result.get("error")]
    return {
        "success": True,
        "host": target,
        "sent": len(results),
        "received": received,
        "packet_loss_percent": round((len(results) - received) * 100 / len(results), 1),
        "min_ms": round(min(latencies), 2) if latencies else None,
        "average_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "max_ms": round(max(latencies), 2) if latencies else None,
        "latency_samples": len(latencies),
        "below_resolution_count": below_resolution,
        "error": errors[0] if errors else None,
    }


def run_connectivity_test(target):
    target = validate_target(target)
    if target is None:
        return {"success": False, "message": "Informe um IP ou domínio válido, sem protocolo ou caminho."}
    overview = network_overview()
    gateway = overview.get("gateway")
    requests = {"target": target}
    if gateway and gateway != target:
        requests["gateway"] = gateway

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as executor:
        futures = {executor.submit(test_host, host): key for key, host in requests.items()}
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()
    if gateway and gateway == target:
        results["gateway"] = results["target"]
    return {
        "success": True,
        "target": results["target"],
        "gateway_result": results.get("gateway"),
        "gateway": gateway,
        "diagnosis": diagnose_connectivity(overview, results.get("gateway"), results["target"]),
    }


def diagnose_connectivity(overview, gateway_result, target_result):
    """Sugere verificações sem afirmar a causa quando ICMP ou a rota não podem ser confirmados."""
    findings = []
    active = overview.get("active_adapters", 0)
    gateway = overview.get("gateway")
    if not active:
        findings.append({
            "severity": "high",
            "title": "Nenhum adaptador ativo identificado",
            "detail": "O sistema não listou interfaces de rede ativas nesta leitura.",
            "suggestion": "Confira se o Wi-Fi está ligado ou se o cabo Ethernet está conectado; depois tente novamente.",
        })

    if not gateway:
        findings.append({
            "severity": "medium",
            "title": "Gateway padrão não identificado",
            "detail": "O sistema não informou uma rota IPv4 padrão.",
            "suggestion": "Confira a conexão com o roteador e os detalhes da rede nas configurações do sistema.",
        })
    elif gateway_result and gateway_result["received"] == 0:
        findings.append({
            "severity": "medium",
            "title": "O gateway não respondeu às sondas ICMP",
            "detail": "Isso pode indicar uma falha local, mas alguns roteadores bloqueiam ping.",
            "suggestion": "Verifique Wi-Fi/cabo e acesso ao roteador; confirme também se o roteador permite respostas a ping.",
        })
    elif gateway_result and gateway_result["packet_loss_percent"] > 0:
        findings.append({
            "severity": "medium",
            "title": "Perda observada até o gateway",
            "detail": f"Perda de {gateway_result['packet_loss_percent']:.0f}% em {gateway_result['sent']} sondas curtas.",
            "suggestion": "Repita o teste. Se persistir, compare Wi-Fi com cabo e aproxime-se do roteador; interferência pode influenciar.",
        })

    if target_result.get("received", 0) == 0:
        title = "O destino não respondeu às sondas"
        detail = target_result.get("error") or "Todos os pacotes de teste ficaram sem resposta. O destino pode bloquear ICMP."
        suggestion = "Confirme o IP/domínio e teste outro destino. Para jogos, o servidor pode não responder a ping; confira também o indicador dentro do jogo."
        findings.append({"severity": "medium", "title": title, "detail": detail, "suggestion": suggestion})
    elif target_result.get("packet_loss_percent", 0) > 0:
        if gateway_result and gateway_result.get("packet_loss_percent") == 0:
            detail = "O gateway respondeu, mas houve perda no destino externo; a rota, o provedor ou o próprio destino podem influenciar."
        else:
            detail = f"Perda de {target_result['packet_loss_percent']:.0f}% nas sondas para o destino escolhido."
        findings.append({
            "severity": "medium",
            "title": "Perda de pacotes observada até o destino",
            "detail": detail,
            "suggestion": "Repita em horários diferentes e compare outro destino. Uma amostra ICMP curta não localiza sozinha onde ocorre a perda.",
        })

    if not findings:
        findings.append({
            "severity": "info",
            "title": "Sem sinais básicos de perda nesta amostra",
            "detail": f"O destino respondeu a {target_result.get('received', 0)} de {target_result.get('sent', 0)} sondas.",
            "suggestion": "Isso não garante estabilidade durante uma partida. Rota ao servidor, congestionamento e Wi-Fi variam ao longo do tempo.",
        })
    findings.append({
        "severity": "info",
        "title": "Ping depende da rota e do servidor",
        "detail": "Este teste mede respostas ICMP do destino escolhido, não o caminho completo nem o ping exibido pelo jogo.",
        "suggestion": "Use o endereço do servidor do jogo quando conhecido e compare com a medição interna do próprio jogo.",
    })
    return findings
