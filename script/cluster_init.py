#!/usr/bin/env python3

import subprocess
import re
import json
import time
import argparse
import logging
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--debug", action="store_true", help="Enable debug logging")
parser.add_argument("--replicas", type=int, default=2, help="Count of VM's to create")
args = parser.parse_args()

logging.basicConfig(
    level=logging.DEBUG if args.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

COUNT_OF_NODES = args.replicas
BASE_DIR: Path = Path.home() / "git/infra-test"
TERRAFORM_DIR: Path = BASE_DIR / "terraform"
KUBESPRAY_DIR: Path = Path.home() / "git/kubespray"
ARGOCD_DIR: Path = BASE_DIR / "argocd"

class Colors:
    RUNNING = "\033[1;37m\033[44m" 
    COMMAND = "\033[36m"
    PATH = GREEN   = "\033[32m"
    FAILED = "\033[91m" 
    END = "\033[0m" 


def run_command(cmd: str, cwd: Path = Path.home(), check: bool = True) -> str:
    """Run bash command and print stdout in real-time"""

    logging.info(f"{Colors.RUNNING}Running command: {Colors.END}{Colors.COMMAND}{cmd}{Colors.END}")
    logging.debug(f"{Colors.RUNNING}Path: {Colors.END}{Colors.PATH}{cwd}{Colors.END}")

    cmd = list(cmd.strip().split())
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    output_lines = []

    for line in process.stdout:
        line = line.strip()
        output_lines.append(line)
        logging.info(line)  

    process.wait()
    if process.returncode != 0 and check:
        raise Exception(f"{Colors.FAILED}Command failed:{Colors.END} {' '.join(cmd)}")

    return "\n".join(output_lines)

def terraform_apply() -> tuple[list[str], list[str]]:
    """Applying terraform and returning json output"""
    logging.info("Applying Terraform...")

    if COUNT_OF_NODES > 10:
        raise "To many replicas"

    run_command(
        "terraform apply -auto-approve -input=false -no-color",
        cwd = TERRAFORM_DIR
    )
    output: str = run_command(
        "terraform output -json",
        cwd = TERRAFORM_DIR
    )

    output = json.loads(output)

    return output["external_ip_addresses"]["value"], output["internal_ip_addresses"]["value"]

def wait_for_ssh(ip: str, timeout: int = 300) -> None:
    """Ждём доступности SSH на указанном IP"""
    logging.info(f"Waiting for SSH on {ip}")
    start: float = time.time()
    while time.time() - start < timeout:
        try:
            run_command(["ssh", "-o", "StrictHostKeyChecking=no", ip, "echo ok"], check=True)
            logging.info(f"{ip} is ready")
            return
        except Exception:
            time.sleep(5)
    raise TimeoutError(f"SSH not ready for {ip} after {timeout} seconds")

def generate_inventory(pub1: str, pub2: str, priv1: str, priv2: str) -> None:
    """Генерация inventory для Kubespray"""
    inventory_path: Path = KUBESPRAY_DIR / "inventory/cluster/inventory.ini"
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    content: str = f"""
node1 ansible_host={pub1} ip={priv1} etcd_member_name=etcd1
node2 ansible_host={pub2} ip={priv2} etcd_member_name=etcd2

[kube_control_plane]
node1

[etcd:children]
kube_control_plane

[kube_node]
node1
node2
"""
    inventory_path.write_text(content)
    logging.info(f"Inventory written to {inventory_path}")

def configure_kubeconfig(pub1: str) -> None:
    """Копируем kubeconfig с master ноды и заменяем localhost на публичный IP"""
    kubeconfig: str = run_command([
        "ssh", "-o", "StrictHostKeyChecking=no", pub1, "sudo cat /etc/kubernetes/admin.conf"
    ])
    kubeconfig = kubeconfig.replace("127.0.0.1", pub1)
    kubeconfig_path: Path = Path.home() / ".kube/config"
    kubeconfig_path.write_text(kubeconfig)
    logging.info(f"Kubeconfig written to {kubeconfig_path}")

def deploy_argocd() -> None:
    """Развёртываем ArgoCD в кластер"""
    run_command(["kubectl", "create", "namespace", "argocd"], check=False)
    run_command([
        "kubectl", "apply", "-n", "argocd",
        "-f", "https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"
    ])
    run_command(["kubectl", "apply", "-f", str(ARGOCD_DIR / "root-app.yaml")])

def main() -> None:
    external_ip_list, internal_ip_list = terraform_apply()

    exit()
   # 2. Wait SSH
    wait_for_ssh(PUB1)
    wait_for_ssh(PUB2)

    # 3. Kubespray clone
    if not KUBESPRAY_DIR.exists():
        run_command(["git", "clone", "https://github.com/kubernetes-sigs/kubespray.git", str(KUBESPRAY_DIR)])
    
    generate_inventory(PUB1, PUB2, PRIV1, PRIV2)

    # 4. Run Ansible
    run_command([
        "ansible-playbook", 
        "-i", str(KUBESPRAY_DIR / "inventory/cluster/inventory.ini"),
        "cluster.yml",
        "-b", "-v"
    ], check=True)

    # 5. Configure kubeconfig
    configure_kubeconfig(PUB1)

    # 6. Deploy ArgoCD
    deploy_argocd()

if __name__ == "__main__":
    main()
