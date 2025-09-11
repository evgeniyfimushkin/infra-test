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
TERRAFORM_DIR: Path = BASE_DIR / "terraform/cluster"
KUBESPRAY_DIR: Path = Path.home() / "git/kubespray"
ARGOCD_DIR: Path = BASE_DIR / "argocd"

class Colors:
    RUNNING = "\033[1;37m\033[44m" 
    COMMAND = "\033[36m"
    GREEN = "\033[32m"
    PATH = GREEN
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

    logging.info(f"{Colors.GREEN}{COUNT_OF_NODES} vm's created successfully {Colors.END}")

    return output["external_ip_addresses"]["value"], output["internal_ip_addresses"]["value"]

def wait_for_ssh(ip_addresses: list[str], timeout: int = 300) -> None:
    """Waiting for SSH availability for VMs"""
    for ip in ip_addresses:
        logging.info(f"Waiting for SSH on {ip}")
        start = time.time()
        while True:
            try:
                run_command(f"ssh -o StrictHostKeyChecking=no {ip} echo ok", check=True)
                logging.info(f"{ip} is ready")
                break 
            except Exception:
                if time.time() - start > timeout:
                    raise TimeoutError(f"{Colors.FAILED}SSH not ready for {ip} after {timeout} seconds{Colors.END}")
                time.sleep(5)

def generate_inventory(external_ip_list: list[str], internal_ip_list: list[str]) -> None:
    """Generation inventory for Kubespray"""

    run_command(f"rm -rf {KUBESPRAY_DIR / 'inventory/cluster'}")
    run_command(f"cp -r {KUBESPRAY_DIR / 'inventory/sample'} {KUBESPRAY_DIR / 'inventory/cluster'}")

    inventory_path: Path = KUBESPRAY_DIR / "inventory/cluster/inventory.ini"
    lines = []
    for i in range(len(external_ip_list)):
        lines.append(f"node{i+1} ansible_host={external_ip_list[i]} ip={internal_ip_list[i]} etcd_member_name=etcd{i}")
        
    lines.append("\n[kube_control_plane]")
    lines.append("node1")

    lines.append("\n[etcd:children]")
    lines.append("kube_control_plane")

    lines.append("\n[kube_node]")
    for i in range(len(external_ip_list)):
        lines.append(f"node{i+1}")

    with open(inventory_path, "w") as f:
        f.write("\n".join(lines))

    with open(KUBESPRAY_DIR / "inventory/cluster/group_vars/k8s_cluster/k8s-cluster.yml", "a") as f:
        f.write(f"\nsupplementary_addresses_in_ssl_keys: [{external_ip_list[0]}]\n")

    print(f"{Colors.GREEN}Inventory written to {inventory_path}{Colors.END}")

def configure_kubeconfig(pub1: str) -> None:
    """Copying kubeconfig from master node and switch localhost on external IP"""
    kubeconfig_path = Path.home() / ".kube/config"
    kubeconfig_path.parent.mkdir(parents=True, exist_ok=True)
    ssh_proc = subprocess.Popen(
        ["ssh", "-o", "StrictHostKeyChecking=no", pub1, "sudo cat /etc/kubernetes/admin.conf"],
        stdout=subprocess.PIPE,
        text=True
    )

    with open(kubeconfig_path, "w", newline="\n") as f:
        for line in ssh_proc.stdout:
            line = line.replace("127.0.0.1", pub1)
            f.write(line)



    logging.info(f"{Colors.GREEN}Kubeconfig written to {kubeconfig_path}{Colors.END}")


def deploy_argocd() -> None:
    """Deploying ArgoCD"""
    if "argocd" not in run_command("kubectl get ns"):
        run_command("kubectl create namespace argocd")
    run_command("kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml")
    run_command(
        f"kubectl apply -f {str(ARGOCD_DIR / 'root-app.yaml')}",
        cwd = ARGOCD_DIR
    )


def main() -> None:

    external_ip_list, internal_ip_list = terraform_apply()

    wait_for_ssh(external_ip_list)

    if not KUBESPRAY_DIR.exists():
        run_command(f"git clone https://github.com/kubernetes-sigs/kubespray.git {str(KUBESPRAY_DIR)}")
    
    generate_inventory(external_ip_list, internal_ip_list)


    run_command(
            f"""
            ansible-playbook 
            -i {str(KUBESPRAY_DIR / 'inventory/cluster/inventory.ini')} 
            {str(KUBESPRAY_DIR / 'cluster.yml')} 
            -b 
            -v
            """,
            check=True,
            cwd=KUBESPRAY_DIR
    )


    configure_kubeconfig(external_ip_list[0])

    deploy_argocd()

if __name__ == "__main__":
    main()
